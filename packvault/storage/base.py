from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import BinaryIO

from packvault.utils.errors import NotFoundError


@dataclass(frozen=True)
class ObjectMeta:
    key: str
    size: int
    etag: str | None = None
    content_type: str | None = None


@dataclass(frozen=True)
class ListPrefixResult:
    keys: list[str]
    continuation_token: str | None = None


@dataclass(frozen=True)
class ListDirectoryResult:
    """Immediate children under a storage prefix (one directory level)."""

    directories: list[str]
    files: list[str]
    continuation_token: str | None = None
    has_more: bool = False


class ArtifactStore(ABC):
    @abstractmethod
    async def head(self, key: str) -> ObjectMeta | None:
        """Return object metadata, or None when the object does not exist."""

    @abstractmethod
    async def get(self, key: str) -> AsyncIterator[bytes]:
        """Return an async byte iterator for an object."""

    @abstractmethod
    async def put(
        self,
        key: str,
        body: AsyncIterator[bytes] | BinaryIO,
        *,
        content_type: str | None = None,
        if_none_match: bool = False,
    ) -> None:
        """Upload an object.

        If if_none_match is true, the backend must fail when the object already exists.
        """

    async def exists(self, key: str) -> bool:
        """Return true when the object exists."""
        return await self.head(key) is not None

    @abstractmethod
    async def check_health(self) -> None:
        """Raise if storage is unavailable."""

    @abstractmethod
    async def list_prefix(
        self,
        prefix: str,
        *,
        max_keys: int = 100,
        continuation_token: str | None = None,
        start_after: str | None = None,
    ) -> ListPrefixResult:
        """List object keys under a prefix with pagination."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete an object. Raises NotFoundError when the object does not exist."""

    @abstractmethod
    async def list_prefix_level(
        self,
        prefix: str,
        *,
        max_entries: int = 100,
        continuation_token: str | None = None,
    ) -> ListDirectoryResult:
        """List immediate child directories and files under a prefix."""

    async def delete_many(self, keys: list[str]) -> None:
        """Delete multiple objects. Missing keys are ignored."""
        for key in keys:
            try:
                await self.delete(key)
            except NotFoundError:
                continue
