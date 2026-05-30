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
from packvault.main import create_app
from packvault.repositories.registry import build_registry
from packvault.runtime import AppState
from packvault.storage.factory import create_artifact_store
from tests.asgi_helpers import asgi_with_local_port


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
    app_state = AppState(
        settings=test_settings,
        store=create_artifact_store(test_settings),
        repositories=build_registry(test_settings),
        tokens=TokenRegistry.from_config(test_settings.auth.tokens),
        sessions=SessionManager(test_settings.server.session_secret),
        google_oauth=create_google_oauth(test_settings),
        startup_complete=True,
    )
    app.state.app_state = app_state
    transport = ASGITransport(
        app=asgi_with_local_port(app, test_settings.server.port),
        raise_app_exceptions=False,
    )
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
