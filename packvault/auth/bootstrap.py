from __future__ import annotations

from packvault.auth.permissions import SessionUser
from packvault.config.settings import Settings


def is_bootstrap_admin(user: SessionUser, settings: Settings) -> bool:
    return (
        user.provider == "local"
        and user.subject == settings.auth.local.username
    )


def post_login_redirect_path(
    user: SessionUser,
    settings: Settings,
    *,
    system_initialized: bool,
) -> str:
    if (
        settings.database_enabled
        and is_bootstrap_admin(user, settings)
        and not system_initialized
    ):
        return "/setup"
    return "/dashboard"
