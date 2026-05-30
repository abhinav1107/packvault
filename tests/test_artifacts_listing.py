from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from packvault.storage.local import LocalArtifactStore
from packvault.ui.artifacts import list_artifacts_for_ui


async def _bytes_iter(data: bytes):
    yield data


@pytest.mark.asyncio
async def test_list_artifacts_for_ui_filters_and_paginates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = LocalArtifactStore(Path(tmp))
        keys = [
            "releases/com/example/a.jar",
            "releases/com/example/a.jar.sha1",
            "releases/com/example/b.jar",
            "releases/com/example/c.jar",
        ]
        for key in keys:
            await store.put(key, _bytes_iter(b"x"))

        first = await list_artifacts_for_ui(
            store,
            repository="releases",
            path_prefix="com/example",
            page_size=2,
        )
        assert [item.path for item in first.items] == [
            "com/example/a.jar",
            "com/example/b.jar",
        ]
        assert first.has_more
        assert first.continuation_token == "releases/com/example/b.jar"

        second = await list_artifacts_for_ui(
            store,
            repository="releases",
            path_prefix="com/example",
            continuation_token=first.continuation_token,
            page_size=2,
        )
        assert [item.path for item in second.items] == ["com/example/c.jar"]
        assert not second.has_more
