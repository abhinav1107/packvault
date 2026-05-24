from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from packvault.api.deps import get_optional_session, get_state
from packvault.auth.permissions import SessionUser
from packvault.runtime import AppState

router = APIRouter(tags=["ui"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "ui" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _login_context(state: AppState) -> dict:
    return {
        "providers": state.settings.auth.providers,
        "public_url": state.settings.server.public_url,
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
        _login_context(state),
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    state: AppState = Depends(get_state),
):
    return templates.TemplateResponse(
        request,
        "login.html",
        _login_context(state),
    )


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
