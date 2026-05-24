"""Generic OIDC provider support — v1.1+."""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth

from packvault.config.settings import OidcAuthConfig, Settings


def create_oidc_oauth(settings: Settings) -> OAuth | None:
    if "oidc" not in settings.auth.providers or settings.auth.oidc is None:
        return None
    oauth = OAuth()
    cfg: OidcAuthConfig = settings.auth.oidc
    redirect = cfg.redirect_uri or f"{settings.server.public_url.rstrip('/')}/auth/oidc/callback"
    oauth.register(
        name="oidc",
        client_id=cfg.client_id,
        client_secret=cfg.client_secret,
        server_metadata_url=f"{cfg.issuer.rstrip('/')}/.well-known/openid-configuration",
        client_kwargs={"scope": " ".join(cfg.scopes)},
        redirect_uri=redirect,
    )
    return oauth
