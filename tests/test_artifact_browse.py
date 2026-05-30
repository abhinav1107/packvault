from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from packvault.maven.paths import build_storage_key
from packvault.storage.local import LocalArtifactStore
from packvault.ui.artifacts import (
    infer_browse_level,
    is_version_directory,
    list_artifact_directory,
)


async def _bytes_iter(data: bytes):
    yield data


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("0.1.0", True),
        ("1.0-SNAPSHOT", True),
        ("simple-library", False),
    ],
)
def test_is_version_directory(name: str, expected: bool) -> None:
    assert is_version_directory(name) is expected


def test_infer_browse_level() -> None:
    assert infer_browse_level("", ["com"], []) == "repository"
    assert infer_browse_level("com/example", ["app"], []) == "browse"
    assert infer_browse_level("com/example/app", ["1.0", "2.0"], []) == "artifact"
    assert infer_browse_level("com/example/app/1.0", [], ["f.jar"]) == "version"


@pytest.mark.asyncio
async def test_list_artifact_directory_hides_sidecars() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = LocalArtifactStore(Path(tmp))
        base = "com/example/app/1.0"
        await store.put(
            build_storage_key("releases", f"{base}/app-1.0.jar"),
            _bytes_iter(b"jar"),
        )
        await store.put(
            build_storage_key("releases", f"{base}/app-1.0.jar.sha1"),
            _bytes_iter(b"sha"),
        )

        at_artifact = await list_artifact_directory(
            store,
            repository="releases",
            path_prefix="com/example/app",
        )
        assert at_artifact.level == "artifact"
        assert len(at_artifact.entries) == 1
        assert at_artifact.entries[0].name == "1.0"

        at_version = await list_artifact_directory(
            store,
            repository="releases",
            path_prefix=base,
        )
        assert at_version.level == "version"
        assert [entry.path for entry in at_version.entries] == [
            f"{base}/app-1.0.jar",
        ]


@pytest.mark.asyncio
async def test_local_list_prefix_level() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = LocalArtifactStore(Path(tmp))
        await store.put(
            build_storage_key("releases", "com/foo/a/1.0/a.jar"),
            _bytes_iter(b"x"),
        )
        await store.put(
            build_storage_key("releases", "com/foo/b/2.0/b.jar"),
            _bytes_iter(b"x"),
        )

        page = await store.list_prefix_level("releases/com/foo")
        assert page.directories == ["a", "b"]
        assert page.files == []
