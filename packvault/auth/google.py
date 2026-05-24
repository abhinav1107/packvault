from __future__ import annotations

from typing import Any

from authlib.integrations.starlette_client import OAuth

from packvault.auth.permissions import SessionUser
from packvault.config.settings import GoogleAuthConfig, Settings
from packvault.utils.errors import UnauthorizedError


def create_google_oauth(settings: Settings) -> OAuth | None:
    if "google" not in settings.auth.providers or settings.auth.google is None:
        return None

    oauth = OAuth()
    cfg: GoogleAuthConfig = settings.auth.google

    redirect_uri = cfg.redirect_uri or (
        f"{settings.server.public_url.rstrip('/')}/auth/google/callback"
    )

    oauth.register(
        name="google",
        client_id=cfg.client_id,
        client_secret=cfg.client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
        redirect_uri=redirect_uri,
    )

    return oauth


def user_from_google_claims(userinfo: dict[str, Any]) -> SessionUser:
    subject = userinfo.get("sub")
    if not isinstance(subject, str) or not subject:
        raise UnauthorizedError("Google login did not return a valid subject")

    email = userinfo.get("email")
    if email is not None and not isinstance(email, str):
        email = None

    name = userinfo.get("name")
    if name is not None and not isinstance(name, str):
        name = None

    return SessionUser(
        subject=subject,
        email=email,
        name=name,
        provider="google",
    )
