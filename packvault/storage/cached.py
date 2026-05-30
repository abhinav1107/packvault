from __future__ import annotations

import os
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO

import aiofiles
import aiofiles.os

from packvault.storage.base import ArtifactStore, ListPrefixResult, ObjectMeta
from packvault.storage.local import LocalArtifactStore
from packvault.utils.errors import NotFoundError, ServiceUnavailableError

_CHUNK_SIZE = 64 * 1024


class CachedArtifactStore(ArtifactStore):
    """Read-through cache wrapper for object-storage-backed artifact storage.

    The wrapped primary store remains the source of truth.

    Cache behavior:
    - cache is checked first for safe cacheable objects
    - cache miss reads from primary and writes a temp cache file
    - temp file is atomically promoted only after a successful full read
    - cache failures do not fail successful primary reads
    - writes go to primary first, then best-effort cache population
    """

    def __init__(
        self,
        primary: ArtifactStore,
        *,
        cache_root: Path,
        metadata_ttl_seconds: int = 60,
        snapshot_ttl_seconds: int = 300,
    ) -> None:
        self._primary = primary
        self._cache = LocalArtifactStore(cache_root)
        self._cache_root = cache_root.resolve()
        self._metadata_ttl_seconds = metadata_ttl_seconds
        self._snapshot_ttl_seconds = snapshot_ttl_seconds

    async def head(self, key: str) -> ObjectMeta | None:
        if self._is_cacheable(key):
            cached = await self._cache.head(key)
            if cached is not None and self._is_cache_fresh(key):
                return cached

        return await self._primary.head(key)

    async def get(self, key: str) -> AsyncIterator[bytes]:
        if self._is_cacheable(key):
            cached = await self._cache.head(key)
            if cached is not None and self._is_cache_fresh(key):
                return await self._cache.get(key)

        primary_stream = await self._primary.get(key)

        if not self._is_cacheable(key):
            return primary_stream

        return self._stream_and_cache(key, primary_stream)

    async def put(
        self,
        key: str,
        body: AsyncIterator[bytes] | BinaryIO,
        *,
        content_type: str | None = None,
        if_none_match: bool = False,
    ) -> None:
        """Write to primary storage and best-effort populate local cache.

        For async iterators, this method writes the request stream to a temp file
        first so the same content can be sent to primary and cache safely.

        This avoids consuming the iterator once and having nothing left for cache.
        """

        temp_path: Path | None = None

        try:
            with self._new_temp_file("packvault-cache-put-") as temp:
                temp_path = Path(temp.name)

            async with aiofiles.open(temp_path, "wb") as temp_file:
                if hasattr(body, "read"):
                    while chunk := body.read(_CHUNK_SIZE):  # type: ignore[union-attr]
                        if isinstance(chunk, str):
                            chunk = chunk.encode()
                        await temp_file.write(chunk)
                else:
                    async for chunk in body:  # type: ignore[union-attr]
                        await temp_file.write(chunk)

            with temp_path.open("rb") as primary_body:
                await self._primary.put(
                    key,
                    primary_body,
                    content_type=content_type,
                    if_none_match=if_none_match,
                )

            if self._is_cacheable(key):
                try:
                    with temp_path.open("rb") as cache_body:
                        await self._cache.put(
                            key,
                            cache_body,
                            content_type=content_type,
                            if_none_match=False,
                        )
                except Exception:
                    # Cache population must not turn a successful primary write
                    # into a failed upload.
                    pass

        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    async def check_health(self) -> None:
        await self._primary.check_health()

        try:
            await self._cache.check_health()
        except ServiceUnavailableError:
            # Primary storage is the source of truth.
            # Cache health should not make the whole store unavailable.
            pass

    async def list_prefix(
        self,
        prefix: str,
        *,
        max_keys: int = 100,
        continuation_token: str | None = None,
    ) -> ListPrefixResult:
        return await self._primary.list_prefix(
            prefix,
            max_keys=max_keys,
            continuation_token=continuation_token,
        )

    async def delete(self, key: str) -> None:
        await self._primary.delete(key)

        try:
            await self._cache.delete(key)
        except NotFoundError:
            pass
        except Exception:
            # Cache eviction must not turn a successful primary delete into a failure.
            pass

    def _is_cacheable(self, key: str) -> bool:
        """Return whether a key is safe/useful to cache.

        v1 policy:
        - Do not cache Maven metadata.
        - Do not cache snapshot paths.
        - Cache release artifacts, POMs, and checksum files.
        """

        normalized = key.strip("/")

        if not normalized:
            return False

        name = normalized.rsplit("/", 1)[-1]

        if name == "maven-metadata.xml":
            return False

        if "SNAPSHOT" in normalized.upper():
            return False

        return True

    def _is_cache_fresh(self, key: str) -> bool:
        """Return whether a cached object is still fresh.

        Immutable release artifacts are considered fresh indefinitely.

        Metadata and snapshots are not cached by v1 policy, but this method keeps
        TTL support available for later policy expansion.
        """

        normalized = key.strip("/")
        name = normalized.rsplit("/", 1)[-1]

        if name == "maven-metadata.xml":
            return self._cache_age_seconds(key) <= self._metadata_ttl_seconds

        if "SNAPSHOT" in normalized.upper():
            return self._cache_age_seconds(key) <= self._snapshot_ttl_seconds

        return True

    def _cache_age_seconds(self, key: str) -> float:
        path = self._resolve_cache_path(key)

        try:
            stat = path.stat()
        except FileNotFoundError:
            return float("inf")

        return time.time() - stat.st_mtime

    def _resolve_cache_path(self, key: str) -> Path:
        path = (self._cache_root / key).resolve()

        if not path.is_relative_to(self._cache_root):
            raise ValueError("Path escapes cache root")

        return path

    async def _stream_and_cache(
        self,
        key: str,
        primary_stream: AsyncIterator[bytes],
    ) -> AsyncIterator[bytes]:
        path = self._resolve_cache_path(key)
        await aiofiles.os.makedirs(path.parent, exist_ok=True)

        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")

        async def iterator() -> AsyncIterator[bytes]:
            cache_file = None

            try:
                try:
                    cache_file = await aiofiles.open(temp_path, "xb")
                except OSError:
                    cache_file = None

                async for chunk in primary_stream:
                    if cache_file is not None:
                        try:
                            await cache_file.write(chunk)
                        except OSError:
                            await cache_file.close()
                            cache_file = None
                            temp_path.unlink(missing_ok=True)

                    yield chunk

                if cache_file is not None:
                    await cache_file.close()
                    os.replace(temp_path, path)

            except NotFoundError:
                if cache_file is not None:
                    await cache_file.close()
                temp_path.unlink(missing_ok=True)
                raise

            except Exception:
                if cache_file is not None:
                    await cache_file.close()
                temp_path.unlink(missing_ok=True)
                raise

        return iterator()

    @staticmethod
    def _new_temp_file(prefix: str):
        return __import__("tempfile").NamedTemporaryFile(
            prefix=prefix,
            delete=False,
        )