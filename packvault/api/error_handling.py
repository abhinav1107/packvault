from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from packvault.api.deps import get_optional_app_state
from packvault.utils.errors import NotFoundError, PackVaultError, UnauthorizedError
from packvault.utils.request_id import get_request_id

logger = logging.getLogger(__name__)

_OPERATIONS_PATHS = frozenset({"/ping", "/livez", "/readyz", "/startupz", "/metrics"})
_UI_EXACT_PATHS = frozenset({"/", "/login", "/dashboard", "/logout", "/logged-out"})
_UI_PATH_PREFIXES = ("/auth/google/",)

UI_FORM_ERROR_MESSAGES: dict[str, str] = {
    "unauthorized": "Sign-in failed. Check your username and password and try again.",
    "google_sign_in_failed": "Google sign-in failed or was cancelled. Please try again.",
    "forbidden": "You do not have permission to perform that action.",
    "unavailable": "Sign-in is temporarily unavailable. Please try again later.",
}

_GOOGLE_OAUTH_UNAVAILABLE_MESSAGES = frozenset(
    {
        "google sso disabled",
        "google sso not configured",
        "local login disabled",
    }
)


def _known_repositories(request: Request) -> set[str]:
    state = get_optional_app_state(request)
    if state is None:
        return set()
    return state.repositories.names


def is_maven_api_path(path: str, known_repositories: set[str]) -> bool:
    if not path.startswith("/"):
        return False
    segment = path.lstrip("/").split("/", 1)[0]
    return bool(segment) and segment in known_repositories


def wants_html_error_response(request: Request) -> bool:
    path = request.url.path

    if path in _OPERATIONS_PATHS:
        return False

    if is_maven_api_path(path, _known_repositories(request)):
        return False

    if path in _UI_EXACT_PATHS:
        return True

    if any(path.startswith(prefix) for prefix in _UI_PATH_PREFIXES):
        return True

    if request.method == "POST" and path == "/login":
        return True

    accept = request.headers.get("accept", "").lower()
    if "text/html" in accept:
        return True

    content_type = request.headers.get("content-type", "").lower()
    return "application/x-www-form-urlencoded" in content_type


def request_user_label(request: Request) -> str | None:
    state = get_optional_app_state(request)
    if state is None:
        return None

    cookie = request.cookies.get("packvault_session")
    if not cookie:
        return None

    user = state.sessions.load(cookie)
    if user is None:
        return None

    return user.name or user.subject


def log_request_error(request: Request, exc: BaseException) -> None:
    if isinstance(exc, NotFoundError) and not is_maven_api_path(
        request.url.path,
        _known_repositories(request),
    ):
        return

    extra: dict[str, Any] = {
        "route": request.url.path,
        "method": request.method,
        "error_type": type(exc).__name__,
    }
    user = request_user_label(request)
    if user:
        extra["user"] = user

    if isinstance(exc, PackVaultError):
        extra["error_code"] = exc.code
        extra["status_code"] = exc.status_code

    logger.error(
        "request failed",
        exc_info=exc,
        extra={"extra_fields": extra},
    )


def safe_message_for_packvault_error(exc: PackVaultError) -> str:
    messages: dict[str, str] = {
        "bad_request": "The request could not be processed.",
        "unauthorized": "Sign in is required to continue.",
        "forbidden": "You do not have permission for this action.",
        "not_found": "The page or resource was not found.",
        "conflict": "The request could not be completed because of a conflict.",
        "service_unavailable": "The service is temporarily unavailable. Please try again later.",
        "packvault_error": "Something went wrong. Please try again later.",
    }
    return messages.get(exc.code, messages["packvault_error"])


def safe_message_for_http_status(status_code: int) -> str:
    if status_code == 404:
        return "The page or resource was not found."
    if status_code == 405:
        return "That action is not allowed."
    if status_code < 500:
        return "The request could not be completed."
    return "Something went wrong. Please try again later."


def json_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
            },
            "request_id": get_request_id(),
        },
    )


def html_error_response(
    templates: Jinja2Templates,
    request: Request,
    *,
    status_code: int,
    message: str,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "message": message,
            "request_id": get_request_id(),
        },
        status_code=status_code,
    )


def login_form_error_redirect(error_code: str) -> RedirectResponse:
    request_id = get_request_id()
    return RedirectResponse(
        url=f"/login?error={error_code}&ref={request_id}",
        status_code=303,
    )


def login_error_code_for_unauthorized(exc: UnauthorizedError, path: str) -> str:
    if path.startswith("/auth/google/"):
        if exc.message.lower() in _GOOGLE_OAUTH_UNAVAILABLE_MESSAGES:
            return "unavailable"
        return "google_sign_in_failed"
    return "unauthorized"


def should_redirect_unauthorized_to_login(request: Request) -> bool:
    path = request.url.path
    if request.method == "POST" and path == "/login":
        return True
    return path.startswith("/auth/google/")


def resolve_response_for_packvault_error(
    request: Request,
    exc: PackVaultError,
    templates: Jinja2Templates,
) -> Response:
    if isinstance(exc, UnauthorizedError) and should_redirect_unauthorized_to_login(
        request
    ):
        return login_form_error_redirect(
            login_error_code_for_unauthorized(exc, request.url.path)
        )

    if wants_html_error_response(request):
        return html_error_response(
            templates,
            request,
            status_code=exc.status_code,
            message=safe_message_for_packvault_error(exc),
        )

    return json_error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
    )


def resolve_response_for_http_exception(
    request: Request,
    exc: StarletteHTTPException,
    templates: Jinja2Templates,
) -> Response:
    if wants_html_error_response(request):
        return html_error_response(
            templates,
            request,
            status_code=exc.status_code,
            message=safe_message_for_http_status(exc.status_code),
        )

    detail = exc.detail
    message = detail if isinstance(detail, str) else safe_message_for_http_status(exc.status_code)

    return json_error_response(
        status_code=exc.status_code,
        code="http_error",
        message=message,
    )


def resolve_response_for_unhandled_exception(
    request: Request,
    templates: Jinja2Templates,
) -> Response:
    if wants_html_error_response(request):
        return html_error_response(
            templates,
            request,
            status_code=500,
            message=safe_message_for_http_status(500),
        )

    return json_error_response(
        status_code=500,
        code="internal_error",
        message="Internal server error",
    )
