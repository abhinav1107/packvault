from __future__ import annotations

import base64

import pytest
from httpx import AsyncClient


def _basic(username: str, password: str) -> dict[str, str]:
    creds = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


@pytest.mark.asyncio
async def test_put_and_get_artifact(client: AsyncClient) -> None:
    path = "releases/com/example/demo/1.0.0/demo-1.0.0.jar"
    body = b"fake-jar-content"
    headers = _basic("ci-publisher", "ci-secret")

    put = await client.put(path, content=body, headers=headers)
    assert put.status_code == 201

    get = await client.get(path, headers=headers)
    assert get.status_code == 200
    assert get.content == body


@pytest.mark.asyncio
async def test_immutable_release_conflict(client: AsyncClient) -> None:
    path = "releases/com/example/immutable/1.0.0/immutable-1.0.0.jar"
    headers = _basic("ci-publisher", "ci-secret")

    assert (await client.put(path, content=b"v1", headers=headers)).status_code == 201
    second = await client.put(path, content=b"v2", headers=headers)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_snapshot_overwrite(client: AsyncClient) -> None:
    path = "snapshots/com/example/snap/1.0.0-SNAPSHOT/snap-1.0.0-SNAPSHOT.jar"
    headers = _basic("ci-publisher", "ci-secret")

    assert (await client.put(path, content=b"v1", headers=headers)).status_code == 201
    assert (await client.put(path, content=b"v2", headers=headers)).status_code == 201
    get = await client.get(path, headers=headers)
    assert get.content == b"v2"


@pytest.mark.asyncio
async def test_unauthorized_without_token(client: AsyncClient) -> None:
    path = "releases/com/example/private/1.0.0/private-1.0.0.jar"
    assert (await client.get(path)).status_code == 401


@pytest.mark.asyncio
async def test_read_forbidden_without_scope(client: AsyncClient) -> None:
    path = "snapshots/com/example/nope/1.0.0-SNAPSHOT/x.jar"
    headers = _basic("app-reader", "reader-secret")
    assert (await client.get(path, headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_not_found(client: AsyncClient) -> None:
    headers = _basic("ci-publisher", "ci-secret")
    resp = await client.get("releases/com/missing/artifact/9.9.9/missing.jar", headers=headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_ping_endpoint(client: AsyncClient) -> None:
    response = await client.get("/ping")
    assert response.status_code == 200
    assert response.text == "pong"


@pytest.mark.asyncio
async def test_health_endpoints_not_on_main_port(client: AsyncClient) -> None:
    assert (await client.get("/livez", follow_redirects=True)).status_code == 404
    assert (await client.get("/metrics", follow_redirects=True)).status_code == 404


@pytest.mark.asyncio
async def test_ui_login_and_dashboard(client: AsyncClient) -> None:
    login = await client.post(
        "/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )

    assert login.status_code == 303
    assert "packvault_session" in login.cookies
    assert "packvault_session" in client.cookies

    dash = await client.get("/dashboard")

    assert dash.status_code == 200
    assert "releases" in dash.text
