from __future__ import annotations

import logging
from collections.abc import Generator

import pytest
from httpx import ASGITransport, AsyncClient

from packvault.config.settings import Settings
from packvault.main import create_app
from packvault.maven.paths import build_storage_key
from packvault.storage.local import LocalArtifactStore
from packvault.ui.artifacts import is_hidden_artifact_path
from tests.asgi_helpers import asgi_with_local_port
from tests.conftest import build_test_app_state


async def _bytes_iter(data: bytes):
    yield data


@pytest.fixture
async def storage_client(
    test_settings: Settings,
    temp_storage,
) -> Generator[AsyncClient]:
    store = LocalArtifactStore(temp_storage)
    app = create_app(test_settings)
    app.state.app_state = build_test_app_state(test_settings, store=store)
    transport = ASGITransport(
        app=asgi_with_local_port(app, test_settings.server.port),
        raise_app_exceptions=False,
    )
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac._store = store  # type: ignore[attr-defined]
        yield ac


async def _login(client: AsyncClient) -> None:
    response = await client.post(
        "/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )
    assert response.status_code == 303


@pytest.mark.parametrize(
    ("path", "hidden"),
    [
        ("com/example/app.jar", False),
        ("com/example/app.jar.sha1", True),
        ("com/example/app.jar.md5", True),
        ("com/example/app.jar.asc", True),
        ("com/example/maven-metadata.xml", True),
    ],
)
def test_is_hidden_artifact_path(path: str, hidden: bool) -> None:
    assert is_hidden_artifact_path(path) is hidden


@pytest.mark.asyncio
async def test_artifacts_requires_session(client: AsyncClient) -> None:
    response = await client.get("/artifacts", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


@pytest.mark.asyncio
async def test_artifacts_lists_and_hides_sidecars(storage_client: AsyncClient) -> None:
    store: LocalArtifactStore = storage_client._store  # type: ignore[attr-defined]
    await store.put(
        build_storage_key("releases", "com/example/app/1.0/app-1.0.jar"),
        _bytes_iter(b"jar"),
    )
    await store.put(
        build_storage_key("releases", "com/example/app/1.0/app-1.0.jar.sha1"),
        _bytes_iter(b"checksum"),
    )
    await store.put(
        build_storage_key("releases", "com/example/app/maven-metadata.xml"),
        _bytes_iter(b"<metadata/>"),
    )

    await _login(storage_client)

    response = await storage_client.get(
        "/artifacts?repository=releases&prefix=com/example/app"
    )
    assert response.status_code == 200
    assert "com/example/app/1.0/app-1.0.jar</code>" in response.text
    assert "app-1.0.jar.sha1</code>" not in response.text
    assert "com/example/app/maven-metadata.xml</code>" not in response.text


@pytest.mark.asyncio
async def test_artifacts_show_all_includes_sidecars(storage_client: AsyncClient) -> None:
    store: LocalArtifactStore = storage_client._store  # type: ignore[attr-defined]
    await store.put(
        build_storage_key("releases", "com/example/x.jar.sha1"),
        _bytes_iter(b"checksum"),
    )

    await _login(storage_client)

    response = await storage_client.get(
        "/artifacts?repository=releases&prefix=com/example&show_all=1"
    )
    assert response.status_code == 200
    assert "x.jar.sha1" in response.text


@pytest.mark.asyncio
async def test_artifacts_delete_and_audit_log(
    storage_client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store: LocalArtifactStore = storage_client._store  # type: ignore[attr-defined]
    path = "com/example/remove-me.jar"
    await store.put(build_storage_key("releases", path), _bytes_iter(b"jar"))

    await _login(storage_client)

    caplog.set_level(logging.INFO, logger="packvault.audit")

    delete = await storage_client.post(
        "/artifacts/delete",
        data={"repository": "releases", "path": path, "prefix": "com/example"},
        follow_redirects=False,
    )
    assert delete.status_code == 303
    assert "deleted=1" in delete.headers["location"]

    assert await store.head(build_storage_key("releases", path)) is None

    audit_records = [r for r in caplog.records if r.name == "packvault.audit"]
    assert audit_records
    assert audit_records[-1].getMessage() == "artifact_delete"
    extra = getattr(audit_records[-1], "extra_fields", {})
    assert extra.get("repository") == "releases"
    assert extra.get("path") == path
    assert extra.get("principal") == "admin"
    assert extra.get("status_code") == 200
    assert extra.get("request_id")


@pytest.mark.asyncio
async def test_dashboard_nav_includes_artifacts(client: AsyncClient) -> None:
    await _login(client)
    response = await client.get("/dashboard")
    assert response.status_code == 200
    assert 'href="/artifacts"' in response.text
    assert 'href="/dashboard"' in response.text
