from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from packvault.utils.errors import ForbiddenError, UnauthorizedError

Action = Literal["read", "write"]


@dataclass(frozen=True)
class Permission:
    repository: str
    actions: set[Action]


@dataclass(frozen=True)
class TokenPrincipal:
    name: str
    permissions: list[Permission]

    def can_read(self, repository: str) -> bool:
        return self._has(repository, "read")

    def can_write(self, repository: str) -> bool:
        return self._has(repository, "write")

    def _has(self, repository: str, action: Action) -> bool:
        for p in self.permissions:
            if p.repository == repository and action in p.actions:
                return True
        return False


@dataclass(frozen=True)
class SessionUser:
    subject: str
    email: str | None = None
    name: str | None = None
    provider: str = "local"


@dataclass
class AuthContext:
    token: TokenPrincipal | None = None
    user: SessionUser | None = None

    @property
    def is_authenticated(self) -> bool:
        return self.token is not None or self.user is not None


def require_token_read(ctx: AuthContext, repository: str) -> TokenPrincipal:
    if ctx.token is None:
        raise UnauthorizedError("Authentication required")
    if not ctx.token.can_read(repository):
        raise ForbiddenError("Read not permitted for this repository")
    return ctx.token


def require_token_write(ctx: AuthContext, repository: str) -> TokenPrincipal:
    if ctx.token is None:
        raise UnauthorizedError("Authentication required")
    if not ctx.token.can_write(repository):
        raise ForbiddenError("Write not permitted for this repository")
    return ctx.token
