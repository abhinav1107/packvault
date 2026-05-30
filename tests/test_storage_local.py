from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from packvault.storage.cached import CachedArtifactStore
from packvault.storage.local import LocalArtifactStore
from packvault.utils.errors import ConflictError, NotFoundError


@pytest.mark.asyncio
async def test_local_exclusive_put() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = LocalArtifactStore(Path(tmp))
        await store.put("releases/a/b.jar", _bytes_iter(b"one"), if_none_match=True)
        with pytest.raises(ConflictError):
            await store.put("releases/a/b.jar", _bytes_iter(b"two"), if_none_match=True)


@pytest.mark.asyncio
async def test_local_list_prefix_pagination() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = LocalArtifactStore(Path(tmp))
        keys = [
            "releases/com/example/a.jar",
            "releases/com/example/b.jar",
            "releases/com/example/c.jar",
            "releases/com/example/d.jar",
        ]
        for key in keys:
            await store.put(key, _bytes_iter(b"artifact"))

        first_page = await store.list_prefix("releases/com/example", max_keys=2)
        assert first_page.keys == keys[:2]
        assert first_page.continuation_token == keys[1]

        second_page = await store.list_prefix(
            "releases/com/example",
            max_keys=2,
            continuation_token=first_page.continuation_token,
        )
        assert second_page.keys == keys[2:]
        assert second_page.continuation_token is None

        all_keys: list[str] = []
        token: str | None = None
        while True:
            page = await store.list_prefix(
                "releases/com/example",
                max_keys=1,
                continuation_token=token,
            )
            all_keys.extend(page.keys)
            token = page.continuation_token
            if token is None:
                break

        assert all_keys == keys


@pytest.mark.asyncio
async def test_local_list_prefix_empty_and_single_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = LocalArtifactStore(Path(tmp))

        empty = await store.list_prefix("releases/missing")
        assert empty.keys == []
        assert empty.continuation_token is None

        await store.put("releases/single.jar", _bytes_iter(b"one"))
        single = await store.list_prefix("releases/single.jar")
        assert single.keys == ["releases/single.jar"]
        assert single.continuation_token is None

        after_cursor = await store.list_prefix(
            "releases/single.jar",
            continuation_token="releases/single.jar",
        )
        assert after_cursor.keys == []


@pytest.mark.asyncio
async def test_local_delete() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = LocalArtifactStore(Path(tmp))
        key = "releases/com/example/app.jar"
        await store.put(key, _bytes_iter(b"artifact"))

        await store.delete(key)
        assert await store.head(key) is None

        with pytest.raises(NotFoundError):
            await store.delete(key)


@pytest.mark.asyncio
async def test_cached_delete_evicts_cache_entry() -> None:
    with tempfile.TemporaryDirectory() as primary_dir, tempfile.TemporaryDirectory() as cache_dir:
        primary = LocalArtifactStore(Path(primary_dir))
        cache = LocalArtifactStore(Path(cache_dir))
        store = CachedArtifactStore(primary, cache_root=Path(cache_dir))
        key = "releases/com/example/app.jar"

        await store.put(key, _bytes_iter(b"artifact"))
        assert await cache.head(key) is not None

        await store.delete(key)
        assert await primary.head(key) is None
        assert await cache.head(key) is None


@pytest.mark.asyncio
async def test_cached_list_prefix_delegates_to_primary() -> None:
    with tempfile.TemporaryDirectory() as primary_dir, tempfile.TemporaryDirectory() as cache_dir:
        primary = LocalArtifactStore(Path(primary_dir))
        store = CachedArtifactStore(primary, cache_root=Path(cache_dir))
        await primary.put("releases/a.jar", _bytes_iter(b"a"))
        await primary.put("releases/b.jar", _bytes_iter(b"b"))

        result = await store.list_prefix("releases", max_keys=1)
        assert result.keys == ["releases/a.jar"]
        assert result.continuation_token == "releases/a.jar"


async def _bytes_iter(data: bytes):
    yield data
