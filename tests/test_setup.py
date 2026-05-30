from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from packvault.auth.passwords import hash_password
from packvault.auth.tokens import hash_token
from packvault.config.settings import Settings
from packvault.db.engine import create_database_manager
from packvault.main import create_app
from packvault.setup.service import run_migrations
from tests.asgi_helpers import asgi_with_local_port
from tests.conftest import build_test_app_state


def _database_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
def postgres_settings(temp_storage) -> Settings | None:
    url = _database_url()
    if not url:
        return None

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
        database={"url": url},
        secrets={"encrypt_at_rest": False},
    )


@pytest.fixture
async def postgres_fresh_client(
    postgres_settings: Settings | None,
) -> AsyncGenerator[AsyncClient | None]:
    if postgres_settings is None:
        yield None
        return

    database = create_database_manager(postgres_settings.database.url)
    database.initialize()

    async with database.session() as session:
        await session.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await session.execute(text("CREATE SCHEMA public"))
        await session.commit()

    app = create_app(postgres_settings)
    app.state.app_state = build_test_app_state(postgres_settings, system_initialized=False)

    transport = ASGITransport(
        app=asgi_with_local_port(app, postgres_settings.server.port),
        raise_app_exceptions=False,
    )
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await database.close()


@pytest.fixture
async def postgres_client(
    postgres_settings: Settings | None,
) -> AsyncGenerator[AsyncClient | None]:
    if postgres_settings is None:
        yield None
        return

    database = create_database_manager(postgres_settings.database.url)
    database.initialize()
    run_migrations(postgres_settings.database.url)

    async with database.session() as session:
        await session.execute(
            text(
                "TRUNCATE token_permissions, tokens, group_permissions, "
                "user_groups, groups, users, system_state RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()

    app = create_app(postgres_settings)
    app.state.app_state = build_test_app_state(postgres_settings, system_initialized=False)

    transport = ASGITransport(
        app=asgi_with_local_port(app, postgres_settings.server.port),
        raise_app_exceptions=False,
    )
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await database.close()


@pytest.mark.asyncio
async def test_bootstrap_login_redirects_to_setup_when_database_configured(
    postgres_client: AsyncClient | None,
) -> None:
    if postgres_client is None:
        pytest.skip("TEST_DATABASE_URL not set")

    response = await postgres_client.post(
        "/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/setup"


@pytest.mark.asyncio
async def test_setup_initialize_once(postgres_fresh_client: AsyncClient | None) -> None:
    if postgres_fresh_client is None:
        pytest.skip("TEST_DATABASE_URL not set")

    login = await postgres_fresh_client.post(
        "/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )

    init = await postgres_fresh_client.post(
        "/admin/setup/initialize",
        cookies=login.cookies,
        headers={"Accept": "application/json"},
    )
    assert init.status_code == 200
    assert init.json()["status"] == "initialized"

    repeat = await postgres_fresh_client.post(
        "/admin/setup/initialize",
        cookies=login.cookies,
        headers={"Accept": "application/json"},
    )
    assert repeat.status_code == 409
    assert repeat.json()["error"]["code"] == "conflict"


@pytest.mark.asyncio
async def test_setup_initialize_from_empty_database(
    postgres_fresh_client: AsyncClient | None,
) -> None:
    if postgres_fresh_client is None:
        pytest.skip("TEST_DATABASE_URL not set")

    login = await postgres_fresh_client.post(
        "/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )

    init = await postgres_fresh_client.post(
        "/admin/setup/initialize",
        cookies=login.cookies,
        follow_redirects=False,
    )
    assert init.status_code == 303
    assert init.headers["location"] == "/dashboard?setup=complete"


@pytest.mark.asyncio
async def test_setup_page_shows_already_completed_after_initialize(
    postgres_client: AsyncClient | None,
) -> None:
    if postgres_client is None:
        pytest.skip("TEST_DATABASE_URL not set")

    login = await postgres_client.post(
        "/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )
    await postgres_client.post(
        "/admin/setup/initialize",
        cookies=login.cookies,
        headers={"Accept": "application/json"},
    )

    setup_page = await postgres_client.get("/setup", cookies=login.cookies)
    assert setup_page.status_code == 200
    assert "already completed" in setup_page.text.lower()


@pytest.mark.asyncio
async def test_initialize_imports_token_hashes(
    postgres_client: AsyncClient | None,
    postgres_settings: Settings | None,
) -> None:
    if postgres_client is None or postgres_settings is None:
        pytest.skip("TEST_DATABASE_URL not set")

    login = await postgres_client.post(
        "/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )
    await postgres_client.post(
        "/admin/setup/initialize",
        cookies=login.cookies,
        headers={"Accept": "application/json"},
    )

    database = create_database_manager(postgres_settings.database.url)
    database.initialize()
    async with database.session() as session:
        tokens = (await session.execute(text("SELECT name, token_hash FROM tokens"))).all()
        state = (
            await session.execute(
                text("SELECT initialized, initialized_by FROM system_state WHERE id = 1")
            )
        ).one()

    await database.close()

    assert len(tokens) == 1
    assert tokens[0][0] == "ci-publisher"
    assert tokens[0][1] == hash_token("ci-secret")
    assert state.initialized is True
    assert state.initialized_by == "admin"


@pytest.mark.asyncio
async def test_setup_requires_bootstrap_admin(client: AsyncClient) -> None:
    response = await client.get("/setup", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"
