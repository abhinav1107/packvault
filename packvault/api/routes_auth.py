from __future__ import annotations

from typing import Annotated

from authlib.integrations.base_client.errors import OAuthError
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response

from packvault.api.deps import get_state
from packvault.api.error_handling import log_request_error, login_form_error_redirect
from packvault.auth.bootstrap import post_login_redirect_path
from packvault.auth.google import user_from_google_claims
from packvault.auth.local import authenticate_local
from packvault.runtime import AppState
from packvault.utils.errors import UnauthorizedError

router = APIRouter(tags=["auth"])

_SESSION_COOKIE = "packvault_session"


def _cookie_secure(state: AppState) -> bool:
    return state.settings.server.public_url.startswith("https://")


def _set_session_cookie(response: Response, session: str, state: AppState) -> None:
    response.set_cookie(
        _SESSION_COOKIE,
        session,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(state),
    )


def _delete_session_cookie(response: Response, state: AppState) -> None:
    response.delete_cookie(
        _SESSION_COOKIE,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(state),
    )


@router.post("/login")
async def login_post(
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    state: AppState = Depends(get_state),
) -> RedirectResponse:
    if "local" not in state.settings.auth.providers:
        raise UnauthorizedError("Local login disabled")

    user = authenticate_local(username, password, state.settings.auth.local)
    session = state.sessions.create(user)

    redirect_url = post_login_redirect_path(
        user,
        state.settings,
        system_initialized=state.system_initialized,
    )
    response = RedirectResponse(url=redirect_url, status_code=303)
    _set_session_cookie(response, session, state)

    return response


@router.get("/logout")
async def logout(state: AppState = Depends(get_state)) -> RedirectResponse:
    response = RedirectResponse(url="/logged-out", status_code=303)
    _delete_session_cookie(response, state)
    return response


@router.get("/auth/google/login")
async def google_login(request: Request, state: AppState = Depends(get_state)):
    if "google" not in state.settings.auth.providers:
        raise UnauthorizedError("Google SSO disabled")

    if state.google_oauth is None:
        raise UnauthorizedError("Google SSO not configured")

    redirect_uri = state.settings.auth.google.redirect_uri if state.settings.auth.google else ""

    if not redirect_uri:
        redirect_uri = f"{state.settings.server.public_url.rstrip('/')}/auth/google/callback"

    return await state.google_oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/auth/google/callback")
async def google_callback(
        request: Request,
        state: AppState = Depends(get_state),
) -> RedirectResponse:
    if "google" not in state.settings.auth.providers:
        raise UnauthorizedError("Google SSO disabled")

    if state.google_oauth is None:
        raise UnauthorizedError("Google SSO not configured")

    try:
        token = await state.google_oauth.google.authorize_access_token(request)
    except OAuthError as exc:
        log_request_error(request, exc)
        return login_form_error_redirect("google_sign_in_failed")

    userinfo = token.get("userinfo")
    if not userinfo:
        userinfo = await state.google_oauth.google.parse_id_token(request, token)

    user = user_from_google_claims(userinfo)
    session = state.sessions.create(user)

    redirect_url = post_login_redirect_path(
        user,
        state.settings,
        system_initialized=state.system_initialized,
    )
    response = RedirectResponse(url=redirect_url, status_code=303)
    _set_session_cookie(response, session, state)

    return response
