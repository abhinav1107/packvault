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

    artifact_page = await storage_client.get(
        "/artifacts?repository=releases&prefix=com/example/app"
    )
    assert artifact_page.status_code == 200
    assert "This raw storage browser is deprecated" in artifact_page.text
    assert "1.0/" in artifact_page.text
    assert "Delete entire artifact" in artifact_page.text
    assert "app-1.0.jar.sha1</code>" not in artifact_page.text

    version_page = await storage_client.get(
        "/artifacts?repository=releases&prefix=com/example/app/1.0"
    )
    assert version_page.status_code == 200
    assert "com/example/app/1.0/app-1.0.jar</code>" in version_page.text
    assert "Delete this version" in version_page.text
    assert "app-1.0.jar.sha1</code>" not in version_page.text


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
async def test_artifacts_delete_version_removes_sidecars(
    storage_client: AsyncClient,
) -> None:
    store: LocalArtifactStore = storage_client._store  # type: ignore[attr-defined]
    version_prefix = "com/example/app/1.0"
    await store.put(
        build_storage_key("releases", f"{version_prefix}/app-1.0.jar"),
        _bytes_iter(b"jar"),
    )
    await store.put(
        build_storage_key("releases", f"{version_prefix}/app-1.0.jar.sha1"),
        _bytes_iter(b"checksum"),
    )

    await _login(storage_client)

    delete = await storage_client.post(
        "/artifacts/delete-version",
        data={"repository": "releases", "prefix": version_prefix},
        follow_redirects=False,
    )
    assert delete.status_code == 303

    jar_key = build_storage_key("releases", f"{version_prefix}/app-1.0.jar")
    sha1_key = build_storage_key("releases", f"{version_prefix}/app-1.0.jar.sha1")
    assert await store.head(jar_key) is None
    assert await store.head(sha1_key) is None


@pytest.mark.asyncio
async def test_artifacts_delete_versions_multi_select(
    storage_client: AsyncClient,
) -> None:
    store: LocalArtifactStore = storage_client._store  # type: ignore[attr-defined]
    artifact_prefix = "com/example/pick"
    for version in ("1.0", "2.0", "3.0"):
        await store.put(
            build_storage_key("releases", f"{artifact_prefix}/{version}/lib.jar"),
            _bytes_iter(b"jar"),
        )

    await _login(storage_client)

    delete = await storage_client.post(
        "/artifacts/delete-versions",
        data={
            "repository": "releases",
            "prefix": artifact_prefix,
            "versions": ["1.0", "3.0"],
        },
        follow_redirects=False,
    )
    assert delete.status_code == 303

    assert await store.head(build_storage_key("releases", f"{artifact_prefix}/1.0/lib.jar")) is None
    assert (
        await store.head(build_storage_key("releases", f"{artifact_prefix}/2.0/lib.jar"))
        is not None
    )
    assert await store.head(build_storage_key("releases", f"{artifact_prefix}/3.0/lib.jar")) is None


@pytest.mark.asyncio
async def test_artifacts_delete_artifact_removes_all_versions(
    storage_client: AsyncClient,
) -> None:
    store: LocalArtifactStore = storage_client._store  # type: ignore[attr-defined]
    artifact_prefix = "com/example/multi"
    for version in ("1.0", "2.0"):
        await store.put(
            build_storage_key("releases", f"{artifact_prefix}/{version}/lib.jar"),
            _bytes_iter(b"jar"),
        )

    await _login(storage_client)

    delete = await storage_client.post(
        "/artifacts/delete-artifact",
        data={"repository": "releases", "prefix": artifact_prefix},
        follow_redirects=False,
    )
    assert delete.status_code == 303
    location = delete.headers["location"]
    assert "deleted_count=2" in location or "deleted=1" in location

    for version in ("1.0", "2.0"):
        assert (
            await store.head(build_storage_key("releases", f"{artifact_prefix}/{version}/lib.jar"))
            is None
        )


@pytest.mark.asyncio
async def test_primary_nav_hides_storage_browser(client: AsyncClient) -> None:
    await _login(client)
    response = await client.get("/dashboard")
    assert response.status_code == 200
    assert 'href="/artifacts"' not in response.text
    assert 'href="/repositories"' not in response.text
    assert 'href="/dashboard"' in response.text


@pytest.mark.asyncio
async def test_dashboard_does_not_render_raw_css(client: AsyncClient) -> None:
    await _login(client)

    response = await client.get("/dashboard")
    assert response.status_code == 200
    assert "Dashboard cleanup" not in response.text
    assert ".dashboard-hero" not in response.text


@pytest.mark.asyncio
async def test_dashboard_requires_session(client: AsyncClient) -> None:
    response = await client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


@pytest.mark.asyncio
async def test_packages_page_redirects_to_dashboard(client: AsyncClient) -> None:
    response = await client.get("/packages", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"

    await _login(client)
    redirect = await client.get(
        "/packages?repository=releases&q=demo&sort=versions",
        follow_redirects=False,
    )
    assert redirect.status_code == 302
    assert (
        redirect.headers["location"]
        == "/dashboard?repository=releases&q=demo&sort=versions"
    )


@pytest.mark.asyncio
async def test_packages_page_lists_and_filters_package_summaries(
    storage_client: AsyncClient,
) -> None:
    store: LocalArtifactStore = storage_client._store  # type: ignore[attr-defined]
    await store.put(
        build_storage_key("releases", "com/example/simple-library/0.1.0/simple-library-0.1.0.jar"),
        _bytes_iter(b"jar"),
    )
    await store.put(
        build_storage_key("releases", "com/example/simple-library/0.1.0/simple-library-0.1.0.pom"),
        _bytes_iter(b"pom"),
    )
    await store.put(
        build_storage_key("releases", "org/acme/demo-client/1.0.0/demo-client-1.0.0.jar"),
        _bytes_iter(b"jar"),
    )

    await _login(storage_client)

    page = await storage_client.get("/dashboard?repository=releases")
    assert page.status_code == 200
    assert "<h1>Dashboard</h1>" in page.text
    assert "com.example:simple-library" in page.text
    assert "org.acme:demo-client" in page.text
    assert 'href="/packages/releases/com/example/simple-library"' in page.text
    raw_storage_link = "/artifacts?repository=releases&amp;prefix=com/example/simple-library"
    assert raw_storage_link not in page.text

    assert "2 configured" in page.text
    assert "2 packages" in page.text
    assert "0 packages" in page.text

    by_group = await storage_client.get("/dashboard?repository=releases&q=com.example")
    assert by_group.status_code == 200
    assert "com.example:simple-library" in by_group.text
    assert "org.acme:demo-client" not in by_group.text

    by_artifact = await storage_client.get("/dashboard?repository=releases&q=demo-client")
    assert by_artifact.status_code == 200
    assert "org.acme:demo-client" in by_artifact.text
    assert "com.example:simple-library" not in by_artifact.text

    by_version = await storage_client.get("/dashboard?repository=releases&q=0.1.0")
    assert by_version.status_code == 200
    assert "com.example:simple-library" in by_version.text
    assert "org.acme:demo-client" not in by_version.text


@pytest.mark.asyncio
async def test_package_detail_shows_versions_files_links_and_actions(
    storage_client: AsyncClient,
) -> None:
    store: LocalArtifactStore = storage_client._store  # type: ignore[attr-defined]
    await store.put(
        build_storage_key(
            "releases",
            "com/example/simple-library/0.1.0/simple-library-0.1.0.jar",
        ),
        _bytes_iter(b"jar"),
    )
    await store.put(
        build_storage_key(
            "releases",
            "com/example/simple-library/0.1.0/simple-library-0.1.0.pom",
        ),
        _bytes_iter(b"pom"),
    )
    await store.put(
        build_storage_key(
            "releases",
            "com/example/simple-library/0.1.0/simple-library-0.1.0.jar.sha1",
        ),
        _bytes_iter(b"checksum"),
    )

    await _login(storage_client)

    response = await storage_client.get("/packages/releases/com/example/simple-library")
    assert response.status_code == 200
    assert "com.example:simple-library" in response.text
    assert "com/example/simple-library" in response.text
    assert "Latest version" in response.text
    assert "0.1.0" in response.text
    assert "Versions" in response.text
    assert "<span>Files</span>" in response.text
    assert "&lt;groupId&gt;com.example&lt;/groupId&gt;" in response.text
    assert "implementation(&#34;com.example:simple-library:0.1.0&#34;)" in response.text
    assert "simple-library-0.1.0.jar" in response.text
    assert "simple-library-0.1.0.pom" in response.text
    assert "simple-library-0.1.0.jar.sha1" not in response.text
    assert "JAR" in response.text
    assert "POM" in response.text
    assert (
        'href="/releases/com/example/simple-library/0.1.0/simple-library-0.1.0.jar"'
    ) in response.text
    assert (
        "/artifacts?repository=releases&amp;prefix=com/example/simple-library/0.1.0"
    ) in response.text
    assert "2 configured" in response.text
    assert "1 package" in response.text
    assert "0 packages" in response.text
    assert 'action="/package-actions/confirm-delete-version"' in response.text
    assert 'action="/package-actions/confirm-delete-package"' in response.text


@pytest.mark.asyncio
async def test_package_detail_unknown_repository_and_package_return_404(
    storage_client: AsyncClient,
) -> None:
    await _login(storage_client)

    unknown_repo = await storage_client.get("/packages/missing/com/example/app")
    assert unknown_repo.status_code == 404

    unknown_package = await storage_client.get("/packages/releases/com/example/missing")
    assert unknown_package.status_code == 404


@pytest.mark.asyncio
async def test_package_delete_version_requires_confirmation_before_delete(
    storage_client: AsyncClient,
) -> None:
    store: LocalArtifactStore = storage_client._store  # type: ignore[attr-defined]
    artifact_path = "com/example/confirm-version"
    jar_key = build_storage_key(
        "releases",
        f"{artifact_path}/1.0/confirm-version-1.0.jar",
    )
    await store.put(jar_key, _bytes_iter(b"jar"))

    await _login(storage_client)

    confirm = await storage_client.post(
        "/package-actions/confirm-delete-version",
        data={
            "repository": "releases",
            "artifact_path": artifact_path,
            "version": "1.0",
        },
    )
    assert confirm.status_code == 200
    assert "Delete version 1.0?" in confirm.text
    assert "Confirm delete version 1.0" in confirm.text
    assert "2 configured" in confirm.text
    assert "1 package" in confirm.text
    assert "0 packages" in confirm.text
    assert 'action="/package-actions/delete-version"' in confirm.text
    assert await store.head(jar_key) is not None


@pytest.mark.asyncio
async def test_package_delete_package_requires_confirmation_before_delete(
    storage_client: AsyncClient,
) -> None:
    store: LocalArtifactStore = storage_client._store  # type: ignore[attr-defined]
    artifact_path = "com/example/confirm-package"
    jar_key = build_storage_key(
        "releases",
        f"{artifact_path}/1.0/confirm-package-1.0.jar",
    )
    await store.put(jar_key, _bytes_iter(b"jar"))

    await _login(storage_client)

    confirm = await storage_client.post(
        "/package-actions/confirm-delete-package",
        data={"repository": "releases", "artifact_path": artifact_path},
    )
    assert confirm.status_code == 200
    assert "Delete package com.example:confirm-package?" in confirm.text
    assert "Confirm delete package com.example:confirm-package" in confirm.text
    assert "2 configured" in confirm.text
    assert "1 package" in confirm.text
    assert "0 packages" in confirm.text
    assert 'action="/package-actions/delete-package"' in confirm.text
    assert await store.head(jar_key) is not None


@pytest.mark.asyncio
async def test_package_delete_version_removes_files_sidecars_and_redirects_to_detail(
    storage_client: AsyncClient,
) -> None:
    store: LocalArtifactStore = storage_client._store  # type: ignore[attr-defined]
    artifact_path = "com/example/app"
    for version in ("1.0", "2.0"):
        await store.put(
            build_storage_key(
                "releases",
                f"{artifact_path}/{version}/app-{version}.jar",
            ),
            _bytes_iter(b"jar"),
        )
        await store.put(
            build_storage_key(
                "releases",
                f"{artifact_path}/{version}/app-{version}.pom",
            ),
            _bytes_iter(b"pom"),
        )
    await store.put(
        build_storage_key("releases", f"{artifact_path}/1.0/app-1.0.jar.sha1"),
        _bytes_iter(b"checksum"),
    )
    await store.put(
        build_storage_key("releases", f"{artifact_path}/maven-metadata.xml"),
        _bytes_iter(b"<metadata/>"),
    )

    await _login(storage_client)

    delete = await storage_client.post(
        "/package-actions/delete-version",
        data={
            "repository": "releases",
            "artifact_path": artifact_path,
            "version": "1.0",
        },
        follow_redirects=False,
    )
    assert delete.status_code == 303
    assert delete.headers["location"] == "/packages/releases/com/example/app"

    removed_jar = build_storage_key("releases", f"{artifact_path}/1.0/app-1.0.jar")
    removed_pom = build_storage_key("releases", f"{artifact_path}/1.0/app-1.0.pom")
    removed_sha1 = build_storage_key(
        "releases",
        f"{artifact_path}/1.0/app-1.0.jar.sha1",
    )
    remaining_jar = build_storage_key("releases", f"{artifact_path}/2.0/app-2.0.jar")
    metadata = build_storage_key("releases", f"{artifact_path}/maven-metadata.xml")

    assert await store.head(removed_jar) is None
    assert await store.head(removed_pom) is None
    assert await store.head(removed_sha1) is None
    assert await store.head(remaining_jar) is not None
    assert await store.head(metadata) is not None


@pytest.mark.asyncio
async def test_package_delete_last_version_redirects_to_index(
    storage_client: AsyncClient,
) -> None:
    store: LocalArtifactStore = storage_client._store  # type: ignore[attr-defined]
    artifact_path = "com/example/solo"
    await store.put(
        build_storage_key("releases", f"{artifact_path}/1.0/solo-1.0.jar"),
        _bytes_iter(b"jar"),
    )

    await _login(storage_client)

    delete = await storage_client.post(
        "/package-actions/delete-version",
        data={
            "repository": "releases",
            "artifact_path": artifact_path,
            "version": "1.0",
        },
        follow_redirects=False,
    )
    assert delete.status_code == 303
    assert delete.headers["location"] == "/dashboard?repository=releases"


@pytest.mark.asyncio
async def test_package_delete_package_removes_all_versions_metadata_and_hides_package(
    storage_client: AsyncClient,
) -> None:
    store: LocalArtifactStore = storage_client._store  # type: ignore[attr-defined]
    artifact_path = "com/example/remove-all"
    for version in ("1.0", "2.0"):
        await store.put(
            build_storage_key(
                "releases",
                f"{artifact_path}/{version}/remove-all-{version}.jar",
            ),
            _bytes_iter(b"jar"),
        )
        await store.put(
            build_storage_key(
                "releases",
                f"{artifact_path}/{version}/remove-all-{version}.pom",
            ),
            _bytes_iter(b"pom"),
        )
        await store.put(
            build_storage_key(
                "releases",
                f"{artifact_path}/{version}/remove-all-{version}.jar.sha1",
            ),
            _bytes_iter(b"checksum"),
        )
    await store.put(
        build_storage_key("releases", f"{artifact_path}/maven-metadata.xml"),
        _bytes_iter(b"<metadata/>"),
    )

    await _login(storage_client)

    delete = await storage_client.post(
        "/package-actions/delete-package",
        data={"repository": "releases", "artifact_path": artifact_path},
        follow_redirects=False,
    )
    assert delete.status_code == 303
    assert delete.headers["location"] == "/dashboard?repository=releases"

    version_one_jar = build_storage_key(
        "releases",
        f"{artifact_path}/1.0/remove-all-1.0.jar",
    )
    version_two_pom = build_storage_key(
        "releases",
        f"{artifact_path}/2.0/remove-all-2.0.pom",
    )
    version_two_sha1 = build_storage_key(
        "releases",
        f"{artifact_path}/2.0/remove-all-2.0.jar.sha1",
    )
    metadata = build_storage_key("releases", f"{artifact_path}/maven-metadata.xml")

    assert await store.head(version_one_jar) is None
    assert await store.head(version_two_pom) is None
    assert await store.head(version_two_sha1) is None
    assert await store.head(metadata) is None

    index = await storage_client.get("/dashboard?repository=releases")
    assert "com.example:remove-all" not in index.text

    detail = await storage_client.get("/packages/releases/com/example/remove-all")
    assert detail.status_code == 404


@pytest.mark.asyncio
async def test_package_actions_require_login_and_validate_repository(
    client: AsyncClient,
) -> None:
    unauthenticated = await client.post(
        "/package-actions/delete-version",
        data={
            "repository": "releases",
            "artifact_path": "com/example/app",
            "version": "1.0",
        },
        follow_redirects=False,
    )
    assert unauthenticated.status_code == 302
    assert unauthenticated.headers["location"] == "/login"

    await _login(client)
    invalid_repo = await client.post(
        "/package-actions/delete-package",
        data={"repository": "missing", "artifact_path": "com/example/app"},
        follow_redirects=False,
    )
    assert invalid_repo.status_code == 404


@pytest.mark.asyncio
async def test_repositories_page_redirects_to_dashboard(
    storage_client: AsyncClient,
) -> None:
    store: LocalArtifactStore = storage_client._store  # type: ignore[attr-defined]
    await store.put(
        build_storage_key("releases", "com/example/app/1.0/app-1.0.jar"),
        _bytes_iter(b"jar"),
    )

    await _login(storage_client)

    response = await storage_client.get("/repositories", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"


@pytest.mark.asyncio
async def test_repository_detail_redirects_to_filtered_dashboard(
    storage_client: AsyncClient,
) -> None:
    store: LocalArtifactStore = storage_client._store  # type: ignore[attr-defined]
    await store.put(
        build_storage_key("releases", "com/example/app/1.0/app-1.0.jar"),
        _bytes_iter(b"jar"),
    )

    await _login(storage_client)

    response = await storage_client.get("/repositories/releases", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard?repository=releases"


@pytest.mark.asyncio
async def test_repositories_require_login_and_unknown_repository_returns_404(
    client: AsyncClient,
) -> None:
    unauthenticated = await client.get("/repositories", follow_redirects=False)
    assert unauthenticated.status_code == 302
    assert unauthenticated.headers["location"] == "/login"

    await _login(client)
    missing = await client.get("/repositories/missing")
    assert missing.status_code == 404
