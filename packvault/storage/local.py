from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO

import aiofiles
import aiofiles.os

from packvault.storage.base import ArtifactStore, ListPrefixResult, ObjectMeta
from packvault.utils.errors import ConflictError, NotFoundError, ServiceUnavailableError

_CHUNK_SIZE = 64 * 1024


class LocalArtifactStore(ArtifactStore):
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _resolve(self, key: str) -> Path:
        path = (self._root / key).resolve()

        if not path.is_relative_to(self._root):
            raise ValueError("Path escapes storage root")

        return path

    async def head(self, key: str) -> ObjectMeta | None:
        path = self._resolve(key)

        try:
            stat = await aiofiles.os.stat(path)
        except FileNotFoundError:
            return None
        except OSError as e:
            raise ServiceUnavailableError(f"Storage error: {e}") from e

        if not path.is_file():
            return None

        return ObjectMeta(key=key, size=stat.st_size)

    async def get(self, key: str) -> AsyncIterator[bytes]:
        path = self._resolve(key)

        if not path.is_file():
            raise NotFoundError("Artifact not found")

        async def iter_file() -> AsyncIterator[bytes]:
            try:
                async with aiofiles.open(path, "rb") as file:
                    while chunk := await file.read(_CHUNK_SIZE):
                        yield chunk
            except FileNotFoundError:
                raise NotFoundError("Artifact not found") from None
            except OSError as exc:
                raise ServiceUnavailableError(f"Storage error: {exc}") from exc

        return iter_file()

    async def put(
        self,
        key: str,
        body: AsyncIterator[bytes] | BinaryIO,
        *,
        content_type: str | None = None,
        if_none_match: bool = False,
    ) -> None:
        path = self._resolve(key)
        await aiofiles.os.makedirs(path.parent, exist_ok=True)

        if if_none_match and path.exists():
            raise ConflictError("Artifact already exists")

        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")

        try:
            async with aiofiles.open(temp_path, "xb") as f:
                if hasattr(body, "read"):
                    while chunk := body.read(_CHUNK_SIZE):  # type: ignore[union-attr]
                        if isinstance(chunk, str):
                            chunk = chunk.encode()
                        await f.write(chunk)
                else:
                    async for chunk in body: # type: ignore[union-attr]
                        await f.write(chunk)

            if if_none_match:
                try:
                    os.link(temp_path, path)
                except FileExistsError:
                    raise ConflictError("Artifact already exists") from None
                finally:
                    temp_path.unlink(missing_ok=True)
            else:
                os.replace(temp_path, path)

        except ConflictError:
            raise
        except OSError as exc:
            temp_path.unlink(missing_ok=True)
            raise ServiceUnavailableError(f"Storage error: {exc}") from exc
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    async def check_health(self) -> None:
        await aiofiles.os.makedirs(self._root, exist_ok=True)

        test = self._root / f".health.{uuid.uuid4().hex}"

        try:
            async with aiofiles.open(test, "x") as f:
                await f.write("ok")
            await aiofiles.os.remove(test)
        except OSError as e:
            raise ServiceUnavailableError(f"Local storage not writable: {e}") from e

    async def list_prefix(
        self,
        prefix: str,
        *,
        max_keys: int = 100,
        continuation_token: str | None = None,
    ) -> ListPrefixResult:
        base = self._resolve(prefix)

        if not base.exists():
            return ListPrefixResult(keys=[])

        if base.is_file():
            if continuation_token is not None:
                return ListPrefixResult(keys=[])
            return ListPrefixResult(keys=[prefix])

        keys: list[str] = []

        for path in base.rglob("*"):
            if path.is_file():
                keys.append(str(path.relative_to(self._root)))

        keys.sort()

        if continuation_token is not None:
            keys = [key for key in keys if key > continuation_token]

        page = keys[:max_keys]
        next_token = page[-1] if len(keys) > max_keys else None
        return ListPrefixResult(keys=page, continuation_token=next_token)

    async def delete(self, key: str) -> None:
        path = self._resolve(key)

        if not path.is_file():
            raise NotFoundError("Artifact not found")

        try:
            await aiofiles.os.remove(path)
        except FileNotFoundError:
            raise NotFoundError("Artifact not found") from None
        except OSError as exc:
            raise ServiceUnavailableError(f"Storage error: {exc}") from exc
