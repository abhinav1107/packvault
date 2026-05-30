from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from packvault.api.deps import get_optional_session, get_state
from packvault.api.error_handling import UI_FORM_ERROR_MESSAGES
from packvault.auth.permissions import SessionUser
from packvault.runtime import AppState
from packvault.ui.branding import STATIC_FAVICON_PATH
from packvault.ui.templates_ctx import templates

router = APIRouter(tags=["ui"])

_FAVICON_PATH = STATIC_FAVICON_PATH


@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    return FileResponse(_FAVICON_PATH, media_type="image/x-icon")


@router.get("/favicon.ico/", include_in_schema=False)
async def favicon_trailing_slash() -> RedirectResponse:
    return RedirectResponse("/favicon.ico", status_code=301)


def _login_context(state: AppState, request: Request) -> dict:
    error_code = request.query_params.get("error")
    error_message = UI_FORM_ERROR_MESSAGES.get(error_code) if error_code else None
    reference_id = request.query_params.get("ref")

    return {
        "providers": state.settings.auth.providers,
        "public_url": state.settings.server.public_url,
        "error_message": error_message,
        "reference_id": reference_id,
    }


@router.get("/", response_class=HTMLResponse)
async def landing(
    request: Request,
    user: SessionUser | None = Depends(get_optional_session),
    state: AppState = Depends(get_state),
):
    if user:
        return RedirectResponse("/dashboard", status_code=302)

    return templates.TemplateResponse(
        request,
        "login.html",
        _login_context(state, request),
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    state: AppState = Depends(get_state),
):
    return templates.TemplateResponse(
        request,
        "login.html",
        _login_context(state, request),
    )


@router.get("/logged-out", response_class=HTMLResponse)
async def logged_out_page(request: Request):
    return templates.TemplateResponse(request, "logged_out.html", {})


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: SessionUser | None = Depends(get_optional_session),
    state: AppState = Depends(get_state),
):
    if user is None:
        return RedirectResponse("/login", status_code=302)

    repositories = [
        {"name": repo.name, "allow_overwrite": repo.allow_overwrite}
        for repo in state.settings.repositories
    ]

    base_url = state.settings.server.public_url.rstrip("/")

    snippets = []
    for repo in repositories:
        name = repo["name"]
        url = f"{base_url}/{name}"

        snippets.append(
            {
                "name": name,
                "url": url,
                "gradle": f'''maven {{
    url = uri("{url}")
    credentials {{
        username = "YOUR_TOKEN_NAME"
        password = findProperty("packvaultToken") as String? ?: System.getenv("PACKVAULT_TOKEN")
    }}
}}''',
                "maven": f'''<repository>
  <id>packvault-{name}</id>
  <url>{url}</url>
</repository>''',
            }
        )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "repositories": repositories,
            "snippets": snippets,
            "providers": state.settings.auth.providers,
            "storage_backend": state.settings.storage.backend,
        },
    )
