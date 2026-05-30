from __future__ import annotations

import argparse
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from packvault.__version__ import __version__
from packvault.api.routes_auth import router as auth_router
from packvault.api.routes_maven import router as maven_router
from packvault.api.routes_operations import router as operations_router
from packvault.api.routes_ping import router as ping_router
from packvault.api.routes_ui import router as ui_router
from packvault.auth.google import create_google_oauth
from packvault.auth.sessions import SessionManager
from packvault.auth.tokens import TokenRegistry
from packvault.config.settings import Settings, load_settings
from packvault.observability.logging import (
    build_uvicorn_log_config,
    resolve_logging_options,
    setup_logging,
)
from packvault.observability.port_routing import (
    AppAccessLogMiddleware,
    OperationsAccessLogMiddleware,
    PortRestrictionMiddleware,
)
from packvault.repositories.registry import build_registry
from packvault.runtime import AppState
from packvault.security.headers import SecurityHeadersMiddleware
from packvault.storage.factory import create_artifact_store
from packvault.utils.errors import PackVaultError
from packvault.utils.request_id import get_request_id, new_request_id, request_id_var

logger = logging.getLogger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or new_request_id()
        token = request_id_var.set(request_id)

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_var.reset(token)


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or load_settings(_config_path_from_env())

    @asynccontextmanager
    async def lifespan(fastapi_app: FastAPI):
        store = create_artifact_store(cfg)

        app_state = AppState(
            settings=cfg,
            store=store,
            repositories=build_registry(cfg),
            tokens=TokenRegistry.from_config(cfg.auth.tokens),
            sessions=SessionManager(cfg.server.session_secret),
            google_oauth=create_google_oauth(cfg),
        )

        fastapi_app.state.app_state = app_state

        await store.check_health()

        app_state.startup_complete = True

        logger.info(
            "PackVault %s startup complete (storage=%s, app=%s:%s, operations=%s:%s)",
            __version__,
            cfg.storage.backend,
            cfg.server.host,
            cfg.server.port,
            cfg.server.host,
            cfg.server.operations_port,
        )

        yield

        app_state.shutting_down = True
        logger.info("PackVault %s shutting down", __version__)

    app = FastAPI(title="PackVault", version=__version__, lifespan=lifespan)

    app.add_middleware(
        PortRestrictionMiddleware,
        main_port=cfg.server.port,
        operations_port=cfg.server.operations_port,
    )
    app.add_middleware(
        AppAccessLogMiddleware,
        main_port=cfg.server.port,
    )
    app.add_middleware(
        OperationsAccessLogMiddleware,
        operations_port=cfg.server.operations_port,
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=cfg.server.session_secret,
        session_cookie="packvault_session",
        https_only=cfg.server.public_url.startswith("https://"),
        same_site="lax",
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(PackVaultError)
    async def packvault_error_handler(_request: Request, exc: PackVaultError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                },
                "request_id": get_request_id(),
            },
        )

    static_dir = Path(__file__).parent / "ui" / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(ping_router)
    app.include_router(operations_router)
    app.include_router(ui_router)
    app.include_router(auth_router)
    app.include_router(maven_router)

    return app


def _config_path_from_env() -> Path | None:
    path = os.environ.get("PACKVAULT_CONFIG")
    return Path(path) if path else None


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PackVault Maven artifact gateway")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARN", "WARNING", "ERROR"],
        help="Log level (overrides PACKVAULT_LOG_LEVEL and config)",
    )
    parser.add_argument(
        "--log-format",
        choices=["json", "standard"],
        help="Log format (overrides PACKVAULT_LOG_FORMAT and config)",
    )
    return parser


async def _serve(app: FastAPI, settings: Settings, log_level: str, log_config: dict) -> None:
    host = settings.server.host
    main_config = uvicorn.Config(
        app,
        host=host,
        port=settings.server.port,
        log_level=log_level,
        log_config=log_config,
        lifespan="off",
        access_log=False,
    )
    ops_config = uvicorn.Config(
        app,
        host=host,
        port=settings.server.operations_port,
        log_level=log_level,
        log_config=log_config,
        lifespan="off",
        access_log=False,
    )

    logger.info(
        "PackVault listening on %s:%s (app) and %s:%s (operations)",
        host,
        settings.server.port,
        host,
        settings.server.operations_port,
    )

    async with app.router.lifespan_context(app):
        await asyncio.gather(
            uvicorn.Server(main_config).serve(),
            uvicorn.Server(ops_config).serve(),
        )


def main() -> None:
    parser = _build_arg_parser()
    args, _unknown = parser.parse_known_args()

    settings = load_settings(_config_path_from_env())

    log_opts = resolve_logging_options(
        cli_level=args.log_level,
        cli_format=args.log_format,
        settings_level=settings.logging.level,
        settings_format=settings.logging.format,
    )

    setup_logging(log_opts)
    log_config = build_uvicorn_log_config(log_opts)
    logger.info("PackVault %s starting", __version__)

    app = create_app(settings)
    log_level = log_opts.level_name.lower()

    asyncio.run(_serve(app, settings, log_level, log_config))


if __name__ == "__main__":
    main()
