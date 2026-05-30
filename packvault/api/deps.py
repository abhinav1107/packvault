from __future__ import annotations

import base64
import binascii

from fastapi import Depends, Request
from starlette.datastructures import Headers

from packvault.auth.permissions import AuthContext, SessionUser
from packvault.config.settings import Settings
from packvault.runtime import AppState
from packvault.utils.errors import UnauthorizedError


def get_state(request: Request) -> AppState:
    return request.app.state.app_state  # type: ignore[attr-defined]


def get_optional_app_state(request: Request) -> AppState | None:
    return getattr(request.app.state, "app_state", None)


def get_settings(state: AppState = Depends(get_state)) -> Settings:
    return state.settings


def _parse_basic_auth(headers: Headers) -> tuple[str, str] | None:
    auth = headers.get("Authorization")

    if not auth:
        return None

    scheme, _, value = auth.partition(" ")

    if scheme.lower() != "basic" or not value.strip():
        return None

    try:
        decoded = base64.b64decode(value.strip(), validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise UnauthorizedError("Invalid Basic authentication header") from None

    if ":" not in decoded:
        raise UnauthorizedError("Invalid Basic authentication header")

    username, _, password = decoded.partition(":")

    if not username or not password:
        raise UnauthorizedError("Invalid Basic authentication header")

    return username, password


async def get_auth_context(
    request: Request,
    state: AppState = Depends(get_state),
) -> AuthContext:
    ctx = AuthContext()

    basic = _parse_basic_auth(request.headers)

    if basic is not None:
        username, password = basic
        ctx.token = state.tokens.authenticate(username, password)

    session_cookie = request.cookies.get("packvault_session")

    if session_cookie:
        user = state.sessions.load(session_cookie)
        if user:
            ctx.user = user

    return ctx


async def get_optional_session(
    request: Request,
    state: AppState = Depends(get_state),
) -> SessionUser | None:
    cookie = request.cookies.get("packvault_session")

    if not cookie:
        return None

    return state.sessions.load(cookie)
