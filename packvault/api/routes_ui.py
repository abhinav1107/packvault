from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from packvault.api.deps import get_optional_session, get_state
from packvault.api.error_handling import UI_FORM_ERROR_MESSAGES
from packvault.auth.bootstrap import post_login_redirect_path
from packvault.auth.permissions import SessionUser
from packvault.runtime import AppState
from packvault.ui.branding import STATIC_FAVICON_PATH
from packvault.ui.artifacts import artifact_path_from_key, list_keys_under_prefix
from packvault.ui.packages import PackageSummary, build_package_summaries
from packvault.ui.templates_ctx import templates

router = APIRouter(tags=["ui"])

def _repository_summaries(state: AppState) -> list[dict]:
    return [
        {"name": repo.name, "allow_overwrite": repo.allow_overwrite}
        for repo in state.settings.repositories
    ]


def _selected_repository(state: AppState, requested_repository: str | None) -> str | None:
    repository_names = [repo.name for repo in state.settings.repositories]
    if not repository_names:
        return None
    if requested_repository in repository_names:
        return requested_repository
    return repository_names[0]


def _filter_packages(packages: list[PackageSummary], query: str) -> list[PackageSummary]:
    normalized_query = query.strip().lower()
    if not normalized_query:
        return packages

    return [
        package
        for package in packages
        if normalized_query in package.package_name.lower()
        or normalized_query in package.group_id.lower()
        or normalized_query in package.artifact_id.lower()
        or normalized_query in package.latest_version.lower()
    ]


def _sort_packages(packages: list[PackageSummary], sort: str) -> list[PackageSummary]:
    if sort == "versions":
        return sorted(
            packages,
            key=lambda package: (-package.version_count, package.package_name),
        )

    return sorted(packages, key=lambda package: package.package_name)

@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    return FileResponse(STATIC_FAVICON_PATH, media_type="image/x-icon")


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
        redirect_url = post_login_redirect_path(
            user,
            state.settings,
            system_initialized=state.system_initialized,
        )
        return RedirectResponse(redirect_url, status_code=302)

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

    redirect_url = post_login_redirect_path(
        user,
        state.settings,
        system_initialized=state.system_initialized,
    )
    if redirect_url != "/dashboard":
        return RedirectResponse(redirect_url, status_code=302)

    repositories = _repository_summaries(state)

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

    setup_complete = request.query_params.get("setup") == "complete"

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "repositories": repositories,
            "snippets": snippets,
            "providers": state.settings.auth.providers,
            "storage_backend": state.settings.storage.backend,
            "setup_complete": setup_complete,
        },
    )

@router.get("/packages", response_class=HTMLResponse)
async def packages_page(
    request: Request,
    user: SessionUser | None = Depends(get_optional_session),
    state: AppState = Depends(get_state),
):
    if user is None:
        return RedirectResponse("/login", status_code=302)

    repositories = _repository_summaries(state)
    requested_repository = request.query_params.get("repository")
    repository = _selected_repository(state, requested_repository)
    query = request.query_params.get("q", "")
    sort = request.query_params.get("sort", "name")

    packages: list[PackageSummary] = []
    if repository is not None:
        keys = await list_keys_under_prefix(state.store, repository)
        artifact_paths = [artifact_path_from_key(key, repository) for key in keys]
        packages = build_package_summaries(repository, artifact_paths)
        packages = _filter_packages(packages, query)
        packages = _sort_packages(packages, sort)

    return templates.TemplateResponse(
        request,
        "packages.html",
        {
            "user": user,
            "repositories": repositories,
            "repository": repository,
            "packages": packages,
            "query": query,
            "sort": sort,
            "providers": state.settings.auth.providers,
            "storage_backend": state.settings.storage.backend,
        },
    )
