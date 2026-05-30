from __future__ import annotations

import logging
from collections.abc import Generator

import pytest
from httpx import ASGITransport, AsyncClient

from packvault.api.error_handling import UI_FORM_ERROR_MESSAGES
from packvault.auth.google import create_google_oauth
from packvault.auth.sessions import SessionManager
from packvault.auth.tokens import TokenRegistry
from packvault.config.settings import Settings
from packvault.main import create_app
from packvault.repositories.registry import build_registry
from packvault.runtime import AppState
from packvault.storage.factory import create_artifact_store
from tests.asgi_helpers import asgi_with_local_port


@pytest.fixture
async def client_with_boom_route(
    test_settings: Settings,
) -> Generator[AsyncClient]:
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

    @app.get("/test-boom")
    async def _boom() -> None:
        raise RuntimeError("secret internal detail")

    transport = ASGITransport(
        app=asgi_with_local_port(app, test_settings.server.port),
        raise_app_exceptions=False,
    )
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_maven_unauthorized_returns_json(client: AsyncClient) -> None:
    response = await client.get("releases/com/example/missing/1.0.0/x.jar")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert payload["error"]["code"] == "unauthorized"
    assert payload["request_id"]
    assert response.headers.get("X-Request-ID") == payload["request_id"]


@pytest.mark.asyncio
async def test_maven_not_found_returns_json(client: AsyncClient) -> None:
    import base64

    creds = base64.b64encode(b"ci-publisher:ci-secret").decode()
    headers = {"Authorization": f"Basic {creds}"}
    response = await client.get(
        "releases/com/example/missing/9.9.9/missing.jar",
        headers=headers,
    )
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_ui_unknown_path_returns_html_error_page(client: AsyncClient) -> None:
    response = await client.get(
        "/does-not-exist/",
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 404
    assert "text/html" in response.headers["content-type"]
    assert "Something went wrong" in response.text
    assert "Reference:" in response.text
    assert response.headers.get("X-Request-ID")


@pytest.mark.asyncio
async def test_failed_login_redirects_with_form_error(client: AsyncClient) -> None:
    response = await client.post(
        "/login",
        data={"username": "admin", "password": "wrong"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/login?error=unauthorized&ref=")

    login_page = await client.get(location)
    assert login_page.status_code == 200
    assert UI_FORM_ERROR_MESSAGES["unauthorized"] in login_page.text
    ref = location.split("ref=", 1)[1]
    assert ref in login_page.text


@pytest.mark.asyncio
async def test_google_login_disabled_returns_html_error(client: AsyncClient) -> None:
    response = await client.get(
        "/auth/google/login",
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 401
    assert "text/html" in response.headers["content-type"]
    assert "Sign in is required" in response.text
    assert "Reference:" in response.text


@pytest.mark.asyncio
async def test_unhandled_ui_error_returns_html_without_details(
    client_with_boom_route: AsyncClient,
) -> None:
    response = await client_with_boom_route.get(
        "/test-boom",
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 500
    assert "text/html" in response.headers["content-type"]
    assert "secret internal detail" not in response.text
    assert "Reference:" in response.text


@pytest.mark.asyncio
async def test_errors_logged_with_request_id(
    caplog: pytest.LogCaptureFixture,
    client: AsyncClient,
) -> None:
    caplog.set_level(logging.ERROR, logger="packvault.api.error_handling")

    response = await client.get("releases/com/example/missing/1.0.0/x.jar")

    error_records = [
        r
        for r in caplog.records
        if r.name == "packvault.api.error_handling" and r.levelno >= logging.ERROR
    ]
    assert error_records
    extra = getattr(error_records[-1], "extra_fields", {})
    assert extra.get("route") == "/releases/com/example/missing/1.0.0/x.jar"
    assert response.headers.get("X-Request-ID")
