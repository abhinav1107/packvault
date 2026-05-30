from __future__ import annotations

import logging

from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("packvault.operations")
http_logger = logging.getLogger("packvault.http")

DEFAULT_OPERATIONS_PORT = 9090
OPERATIONS_PATHS = frozenset({"/livez", "/startupz", "/readyz", "/metrics"})


def normalize_path(path: str) -> str:
    if path != "/" and path.endswith("/"):
        return path.rstrip("/")
    return path


def local_port(scope: Scope) -> int | None:
    server = scope.get("server")
    if server is None:
        return None
    return server[1]


class PortRestrictionMiddleware:
    """Restrict routes by the local TCP port serving the request."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        main_port: int,
        operations_port: int = DEFAULT_OPERATIONS_PORT,
    ) -> None:
        self.app = app
        self.main_port = main_port
        self.operations_port = operations_port

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        port = local_port(scope)
        path = normalize_path(scope["path"])

        if port == self.operations_port:
            if path not in OPERATIONS_PATHS:
                await Response(status_code=404)(scope, receive, send)
                return
        elif port == self.main_port:
            if path in OPERATIONS_PATHS:
                await Response(status_code=404)(scope, receive, send)
                return
        else:
            await Response(status_code=404)(scope, receive, send)
            return

        await self.app(scope, receive, send)


def request_target(scope: Scope) -> str:
    path = scope["path"]
    query = scope.get("query_string", b"")
    if query:
        return f"{path}?{query.decode()}"
    return path


class AppAccessLogMiddleware:
    """Uvicorn-style INFO access log for the main application port."""

    def __init__(self, app: ASGIApp, *, main_port: int) -> None:
        self.app = app
        self.main_port = main_port

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or local_port(scope) != self.main_port:
            await self.app(scope, receive, send)
            return

        status_code = 500
        client = scope.get("client") or ("unknown", 0)
        client_addr = f"{client[0]}:{client[1]}"

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        await self.app(scope, receive, send_wrapper)
        http_logger.info(
            '%s - "%s %s HTTP/%s" %s',
            client_addr,
            scope["method"],
            request_target(scope),
            scope["http_version"],
            status_code,
        )


class OperationsAccessLogMiddleware:
    """Structured DEBUG access log for operations-port requests."""

    def __init__(self, app: ASGIApp, *, operations_port: int = DEFAULT_OPERATIONS_PORT) -> None:
        self.app = app
        self.operations_port = operations_port

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or local_port(scope) != self.operations_port:
            await self.app(scope, receive, send)
            return

        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        await self.app(scope, receive, send_wrapper)
        logger.debug(
            "operations request method=%s path=%s status=%s client=%s",
            scope["method"],
            normalize_path(scope["path"]),
            status_code,
            scope.get("client", ("unknown", 0))[0],
        )
