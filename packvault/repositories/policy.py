from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from packvault.utils.errors import ConflictError, NotFoundError


@dataclass(frozen=True)
class RepositoryPolicy:
    name: str
    allow_overwrite: bool

    def check_overwrite(self, *, exists: bool) -> None:
        if exists and not self.allow_overwrite:
            raise ConflictError("Artifact already exists and overwrite is disabled")


class RepositoryRegistry:
    def __init__(self, repositories: dict[str, RepositoryPolicy]) -> None:
        self._repositories = MappingProxyType(dict(repositories))

    @property
    def names(self) -> set[str]:
        return set(self._repositories.keys())

    def get(self, name: str) -> RepositoryPolicy | None:
        return self._repositories.get(name)

    def require(self, name: str) -> RepositoryPolicy:
        repo = self.get(name)
        if repo is None:
            raise NotFoundError(f"Repository '{name}' not found")
        return repo
