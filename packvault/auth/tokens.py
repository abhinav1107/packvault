from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime

from packvault.auth.permissions import Permission, TokenPrincipal
from packvault.config.settings import TokenConfig
from packvault.utils.errors import UnauthorizedError


def hash_token(raw_token: str) -> str:
    digest = hashlib.sha256(raw_token.encode()).hexdigest()
    return f"sha256:{digest}"


def verify_token_hash(raw_token: str, stored_hash: str) -> bool:
    if not raw_token or not stored_hash.startswith("sha256:"):
        return False

    return hmac.compare_digest(stored_hash, hash_token(raw_token))


def _normalize_expiry(expires_at: datetime | None) -> datetime | None:
    if expires_at is None:
        return None

    if expires_at.tzinfo is None:
        return expires_at.replace(tzinfo=UTC)

    return expires_at.astimezone(UTC)


@dataclass(frozen=True)
class TokenRegistry:
    tokens: dict[str, TokenConfig]

    @classmethod
    def from_config(cls, tokens: list[TokenConfig]) -> TokenRegistry:
        return cls({token.name: token for token in tokens})

    def authenticate(self, username: str, password: str) -> TokenPrincipal:
        token_cfg = self.tokens.get(username)

        if token_cfg is None:
            raise UnauthorizedError("Invalid credentials")

        if not verify_token_hash(password, token_cfg.token_hash):
            raise UnauthorizedError("Invalid credentials")

        expiry = _normalize_expiry(token_cfg.expires_at)
        if expiry is not None and datetime.now(UTC) > expiry:
            raise UnauthorizedError("Token expired")

        permissions = [
            Permission(repository=permission.repository, actions=set(permission.actions))
            for permission in token_cfg.permissions
        ]

        return TokenPrincipal(name=token_cfg.name, permissions=permissions)
