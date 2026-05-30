from __future__ import annotations

import logging

import pytest
from httpx import ASGITransport, AsyncClient

from packvault.auth.passwords import hash_password
from packvault.auth.sessions import SessionManager
from packvault.auth.tokens import TokenRegistry
from packvault.config.settings import AuthConfig, LocalAuthConfig, ServerConfig, Settings
from packvault.db.engine import create_database_manager
from packvault.main import create_app
from packvault.repositories.registry import build_registry
from packvault.runtime import AppState
from packvault.secrets.encryption import EncryptionContext
from packvault.secrets.protector import SecretProtector
from packvault.storage.local import LocalArtifactStore
from tests.asgi_helpers import asgi_with_local_port


def _app_state(settings: Settings, store: LocalArtifactStore) -> AppState:
    database = create_database_manager(settings.database.url)
    encryption = EncryptionContext(enabled=False, key=None, fingerprint=None)
    return AppState(
        settings=settings,
        store=store,
        repositories=build_registry(settings),
        tokens=TokenRegistry.from_config([]),
        sessions=SessionManager(settings.server.session_secret),
        database=database,
        encryption=encryption,
        secret_protector=SecretProtector(encryption),
        startup_complete=True,
    )


@pytest.mark.asyncio
async def test_ping_rate_limited_globally(temp_storage) -> None:
    settings = Settings(
        storage={"backend": "local", "local": {"root": str(temp_storage)}},
        server=ServerConfig(
            session_secret="test-session-secret",
            ping_rate_limit_per_minute=3,
        ),
        auth=AuthConfig(
            providers=["local"],
            local=LocalAuthConfig(
                username="admin",
                password_hash=hash_password("admin"),
            ),
        ),
    )
    app = create_app(settings)
    app.state.app_state = _app_state(settings, LocalArtifactStore(temp_storage))

    transport = ASGITransport(app=asgi_with_local_port(app, settings.server.port))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(3):
            assert (await client.get("/ping")).status_code == 200

        limited = await client.get("/ping")

    assert limited.status_code == 429
    assert limited.text == "too many requests"
    assert limited.headers.get("retry-after") == "60"


@pytest.mark.asyncio
async def test_ping_logs_at_info(caplog: pytest.LogCaptureFixture, temp_storage) -> None:
    settings = Settings(
        storage={"backend": "local", "local": {"root": str(temp_storage)}},
        server=ServerConfig(session_secret="test-session-secret"),
        auth=AuthConfig(
            providers=["local"],
            local=LocalAuthConfig(
                username="admin",
                password_hash=hash_password("admin"),
            ),
        ),
    )
    app = create_app(settings)
    app.state.app_state = _app_state(settings, LocalArtifactStore(temp_storage))

    caplog.set_level(logging.INFO, logger="packvault.access")
    transport = ASGITransport(app=asgi_with_local_port(app, settings.server.port))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ping")

    assert response.status_code == 200
    assert any("ping client=" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_operations_requests_log_at_debug_only(
    caplog: pytest.LogCaptureFixture,
    test_settings: Settings,
) -> None:
    from tests.test_health import _make_app_state

    app = create_app(test_settings)
    app.state.app_state = _make_app_state(test_settings, startup_complete=True)

    caplog.set_level(logging.INFO, logger="packvault.operations")
    transport = ASGITransport(
        app=asgi_with_local_port(app, test_settings.server.operations_port)
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/livez")

    assert response.status_code == 200
    assert not any(record.name == "packvault.operations" for record in caplog.records)

    caplog.set_level(logging.DEBUG, logger="packvault.operations")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/livez")

    assert response.status_code == 200
    assert any(
        record.name == "packvault.operations" and "operations request" in record.message
        for record in caplog.records
    )
