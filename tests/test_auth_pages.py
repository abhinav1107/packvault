from __future__ import annotations

from collections.abc import Generator

import pytest
from httpx import ASGITransport, AsyncClient

from packvault.api.error_handling import UI_FORM_ERROR_MESSAGES
from packvault.config.settings import GoogleAuthConfig, Settings
from packvault.main import create_app
from tests.asgi_helpers import asgi_with_local_port
from tests.conftest import build_test_app_state


@pytest.fixture
async def google_client(test_settings: Settings) -> Generator[AsyncClient]:
    settings = test_settings.model_copy(deep=True)
    settings.auth.providers = ["google"]
    settings.auth.google = GoogleAuthConfig(
        client_id="test-google-client",
        client_secret="test-google-secret",
    )

    app = create_app(settings)
    app.state.app_state = build_test_app_state(settings)
    transport = ASGITransport(
        app=asgi_with_local_port(app, settings.server.port),
        raise_app_exceptions=False,
    )
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_favicon_does_not_hit_maven_api(client: AsyncClient) -> None:
    response = await client.get("/favicon.ico", follow_redirects=False)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")

    trailing = await client.get("/favicon.ico/", follow_redirects=False)
    assert trailing.status_code == 301
    assert trailing.headers["location"] == "/favicon.ico"


@pytest.mark.asyncio
async def test_branding_icons_are_served(client: AsyncClient) -> None:
    for size in (16, 32, 180, 512):
        response = await client.get(f"/static/branding/icon-{size}.png")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"


@pytest.mark.asyncio
async def test_login_page_shows_error_banner(client: AsyncClient) -> None:
    ref = "test-ref-abc123"
    response = await client.get(f"/login?error=unauthorized&ref={ref}")
    assert response.status_code == 200
    assert 'class="banner error"' in response.text
    assert UI_FORM_ERROR_MESSAGES["unauthorized"] in response.text
    assert ref in response.text
    assert "Reference:" in response.text


@pytest.mark.asyncio
async def test_login_page_ignores_unknown_error_code(client: AsyncClient) -> None:
    response = await client.get("/login?error=not_a_real_code&ref=xyz")
    assert response.status_code == 200
    assert "banner error" not in response.text


@pytest.mark.asyncio
async def test_successful_login_redirects_to_packages(client: AsyncClient) -> None:
    response = await client.post(
        "/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/packages"


@pytest.mark.asyncio
async def test_logout_redirects_to_logged_out(client: AsyncClient) -> None:
    login = await client.post(
        "/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    logout = await client.get("/logout", follow_redirects=False)
    assert logout.status_code == 303
    assert logout.headers["location"] == "/logged-out"
    assert logout.cookies.get("packvault_session") in (None, "")


@pytest.mark.asyncio
async def test_logged_out_page_has_sign_in_link(client: AsyncClient) -> None:
    response = await client.get("/logged-out")
    assert response.status_code == 200
    assert "Signed out" in response.text
    assert 'href="/login"' in response.text


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
async def test_google_login_disabled_redirects_to_login(client: AsyncClient) -> None:
    response = await client.get("/auth/google/login", follow_redirects=False)
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/login?error=unavailable&ref=")

    login_page = await client.get(location)
    assert login_page.status_code == 200
    assert UI_FORM_ERROR_MESSAGES["unavailable"] in login_page.text


@pytest.mark.asyncio
async def test_google_callback_without_oauth_state_redirects_to_login(
    google_client: AsyncClient,
) -> None:
    response = await google_client.get("/auth/google/callback", follow_redirects=False)
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/login?error=google_sign_in_failed&ref=")

    login_page = await google_client.get(location)
    assert login_page.status_code == 200
    assert UI_FORM_ERROR_MESSAGES["google_sign_in_failed"] in login_page.text
