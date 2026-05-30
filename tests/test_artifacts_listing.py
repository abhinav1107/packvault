from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from packvault.storage.local import LocalArtifactStore
from packvault.ui.artifacts import (
    decode_ui_list_cursor,
    encode_ui_list_cursor,
    list_artifacts_for_ui,
)


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
        assert decode_ui_list_cursor(first.continuation_token or "") == (
            None,
            "releases/com/example/b.jar",
        )

        second = await list_artifacts_for_ui(
            store,
            repository="releases",
            path_prefix="com/example",
            continuation_token=first.continuation_token,
            page_size=2,
        )
        assert [item.path for item in second.items] == ["com/example/c.jar"]
        assert not second.has_more


def test_ui_list_cursor_roundtrip() -> None:
    encoded = encode_ui_list_cursor(
        storage_token="opaque-s3-token",
        start_after="releases/com/example/a.jar",
    )
    assert decode_ui_list_cursor(encoded) == (
        "opaque-s3-token",
        "releases/com/example/a.jar",
    )


def test_ui_list_cursor_legacy_local_key() -> None:
    assert decode_ui_list_cursor("releases/com/example/b.jar") == (
        None,
        "releases/com/example/b.jar",
    )
