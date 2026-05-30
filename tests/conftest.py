from __future__ import annotations

import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from packvault.auth.google import create_google_oauth
from packvault.auth.passwords import hash_password
from packvault.auth.sessions import SessionManager
from packvault.auth.tokens import TokenRegistry, hash_token
from packvault.config.settings import Settings
from packvault.db.engine import create_database_manager
from packvault.main import create_app
from packvault.repositories.registry import build_registry
from packvault.runtime import AppState
from packvault.secrets.encryption import EncryptionContext
from packvault.secrets.protector import SecretProtector
from packvault.storage.factory import create_artifact_store
from tests.asgi_helpers import asgi_with_local_port


def build_test_app_state(
    settings: Settings,
    *,
    system_initialized: bool = False,
    store=None,
) -> AppState:
    database = create_database_manager(settings.database.url)
    encryption = EncryptionContext(enabled=False, key=None, fingerprint=None)
    secret_protector = SecretProtector(encryption)
    if database.enabled:
        database.initialize()

    return AppState(
        settings=settings,
        store=store or create_artifact_store(settings),
        repositories=build_registry(settings),
        tokens=TokenRegistry.from_config(settings.auth.tokens),
        sessions=SessionManager(settings.server.session_secret),
        database=database,
        encryption=encryption,
        secret_protector=secret_protector,
        google_oauth=create_google_oauth(settings),
        system_initialized=system_initialized,
        startup_complete=True,
    )


@pytest.fixture
def temp_storage() -> Generator[Path]:
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def test_settings(temp_storage: Path) -> Settings:
    return Settings(
        storage={
            "backend": "local",
            "local": {"root": str(temp_storage)},
        },
        auth={
            "providers": ["local"],
            "local": {
                "username": "admin",
                "password_hash": hash_password("admin"),
            },
            "tokens": [
                {
                    "name": "ci-publisher",
                    "token_hash": hash_token("ci-secret"),
                    "permissions": [
                        {"repository": "releases", "actions": ["read", "write"]},
                        {"repository": "snapshots", "actions": ["read", "write"]},
                    ],
                },
                {
                    "name": "app-reader",
                    "token_hash": hash_token("reader-secret"),
                    "permissions": [
                        {"repository": "releases", "actions": ["read"]},
                    ],
                },
            ],
        },
        repositories=[
            {"name": "releases", "allow_overwrite": False},
            {"name": "snapshots", "allow_overwrite": True},
        ],
        security={"anonymous_read": False},
        server={
            "public_url": "http://test",
            "session_secret": "test-secret",
            "max_upload_bytes": 10_000_000,
        },
    )


@pytest.fixture
async def client(test_settings: Settings) -> Generator[AsyncClient]:
    app = create_app(test_settings)
    app.state.app_state = build_test_app_state(test_settings)
    transport = ASGITransport(
        app=asgi_with_local_port(app, test_settings.server.port),
        raise_app_exceptions=False,
    )
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
