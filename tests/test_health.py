from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from packvault.auth.passwords import hash_password
from packvault.auth.sessions import SessionManager
from packvault.auth.tokens import TokenRegistry
from packvault.config.settings import AuthConfig, LocalAuthConfig, ServerConfig, Settings
from packvault.main import create_app
from packvault.observability.health import check_live, check_ready, check_startup
from packvault.repositories.registry import build_registry
from packvault.runtime import AppState
from packvault.storage.local import LocalArtifactStore
from tests.asgi_helpers import asgi_with_local_port


def make_test_settings() -> Settings:
    return Settings(
        server=ServerConfig(session_secret="test-session-secret"),
        auth=AuthConfig(
            providers=["local"],
            local=LocalAuthConfig(
                username="admin",
                password_hash=hash_password("admin"),
            ),
        ),
    )


def _make_app_state(settings: Settings, *, startup_complete: bool) -> AppState:
    return AppState(
        settings=settings,
        store=LocalArtifactStore(Path(settings.storage.local.root)),
        repositories=build_registry(settings),
        tokens=TokenRegistry.from_config([]),
        sessions=SessionManager(settings.server.session_secret),
        startup_complete=startup_complete,
    )


@pytest.mark.asyncio
async def test_probe_functions() -> None:
    settings = make_test_settings()

    with tempfile.TemporaryDirectory() as tmp:
        store = LocalArtifactStore(Path(tmp))
        state = AppState(
            settings=settings,
            store=store,
            repositories=build_registry(settings),
            tokens=TokenRegistry.from_config([]),
            sessions=SessionManager(settings.server.session_secret),
            startup_complete=False,
        )

        assert check_live(state).ok
        assert not check_startup(state).ok
        assert not (await check_ready(state)).ok

        await store.check_health()
        state.startup_complete = True

        assert check_startup(state).ok
        assert (await check_ready(state)).ok

        state.shutting_down = True

        assert not check_live(state).ok
        assert not (await check_ready(state)).ok
        assert check_startup(state).ok


@pytest.mark.asyncio
async def test_health_endpoints_on_operations_port(test_settings: Settings) -> None:
    app = create_app(test_settings)
    app.state.app_state = _make_app_state(test_settings, startup_complete=True)

    transport = ASGITransport(
        app=asgi_with_local_port(app, test_settings.server.operations_port)
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/livez")).status_code == 200
        assert (await client.get("/startupz")).json()["status"] == "started"
        assert (await client.get("/readyz")).json()["status"] == "ready"
        assert (await client.get("/metrics")).status_code == 200


@pytest.mark.asyncio
async def test_health_endpoints_not_on_main_port(test_settings: Settings) -> None:
    app = create_app(test_settings)
    app_state = _make_app_state(test_settings, startup_complete=True)
    app.state.app_state = app_state

    transport = ASGITransport(app=asgi_with_local_port(app, test_settings.server.port))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/livez")).status_code == 404
        assert (await client.get("/startupz")).status_code == 404
        assert (await client.get("/readyz")).status_code == 404
        assert (await client.get("/metrics")).status_code == 404


@pytest.mark.asyncio
async def test_operations_port_rejects_app_routes(test_settings: Settings) -> None:
    app = create_app(test_settings)
    app.state.app_state = _make_app_state(test_settings, startup_complete=True)

    transport = ASGITransport(
        app=asgi_with_local_port(app, test_settings.server.operations_port)
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/ping")).status_code == 404
        assert (await client.get("/dashboard")).status_code == 404


@pytest.mark.asyncio
async def test_readyz_fails_when_not_started(test_settings: Settings) -> None:
    app = create_app(test_settings)
    app.state.app_state = _make_app_state(test_settings, startup_complete=False)

    transport = ASGITransport(
        app=asgi_with_local_port(app, test_settings.server.operations_port)
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/livez")).status_code == 200
        assert (await client.get("/startupz")).status_code == 503
        assert (await client.get("/readyz")).status_code == 503
