from __future__ import annotations

from packvault.auth.passwords import verify_password
from packvault.auth.permissions import SessionUser
from packvault.config.settings import LocalAuthConfig
from packvault.utils.errors import UnauthorizedError


def authenticate_local(username: str, password: str, config: LocalAuthConfig) -> SessionUser:
    if not config.password_hash:
        raise UnauthorizedError("Local auth not configured")

    if username != config.username:
        raise UnauthorizedError("Invalid credentials")

    if not verify_password(password, config.password_hash):
        raise UnauthorizedError("Invalid credentials")

    return SessionUser(
        subject=config.username,
        email=None,
        name=config.username,
        provider="local",
    )
