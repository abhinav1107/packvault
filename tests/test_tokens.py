from __future__ import annotations

import pytest

from packvault.auth.tokens import TokenRegistry, hash_token, verify_token_hash
from packvault.config.settings import TokenConfig, TokenPermission
from packvault.utils.errors import UnauthorizedError


def test_hash_and_verify() -> None:
    raw = "my-secret-token"
    stored = hash_token(raw)
    assert verify_token_hash(raw, stored)
    assert not verify_token_hash("wrong", stored)
    assert not verify_token_hash(raw, "plaintext-secret")
    assert not verify_token_hash(raw, "")


def test_expired_token() -> None:
    registry = TokenRegistry.from_config(
        [
            TokenConfig(
                name="t",
                token_hash=hash_token("secret"),
                expires_at="2020-01-01T00:00:00Z",
                permissions=[TokenPermission(repository="releases", actions=["read"])],
            )
        ]
    )
    with pytest.raises(UnauthorizedError):
        registry.authenticate("t", "secret")
