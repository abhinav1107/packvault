from __future__ import annotations

from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from packvault.api.deps import get_optional_session, get_state
from packvault.api.error_handling import UI_FORM_ERROR_MESSAGES
from packvault.auth.bootstrap import post_login_redirect_path
from packvault.auth.permissions import SessionUser
from packvault.observability.logging import audit_log
from packvault.runtime import AppState
from packvault.ui.artifacts import artifact_path_from_key, list_keys_under_prefix
from packvault.ui.branding import STATIC_FAVICON_PATH
from packvault.ui.package_actions import (
    delete_artifact_package,
    delete_artifact_version,
)
from packvault.ui.packages import (
    PackageSummary,
    artifact_file_download_path,
    artifact_file_type,
    build_package_detail,
    build_package_summaries,
)
from packvault.ui.templates_ctx import templates
from packvault.utils.request_id import get_request_id

router = APIRouter(tags=["ui"])


def _primary_app_path(redirect_url: str) -> str:
    return redirect_url


def _principal_name(user: SessionUser) -> str:
    return user.name or user.subject


def _package_detail_path(repository: str, artifact_path: str) -> str:
    return f"/packages/{quote(repository, safe='')}/{quote(artifact_path, safe='/')}"


def _packages_query(repository: str) -> str:
    return "/dashboard?" + urlencode({"repository": repository})


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


async def _package_summaries_for_repository(
    state: AppState,
    repository: str,
) -> list[PackageSummary]:
    keys = await list_keys_under_prefix(state.store, repository)
    artifact_paths = [artifact_path_from_key(key, repository) for key in keys]
    return build_package_summaries(repository, artifact_paths)


async def _repository_summaries_with_counts(state: AppState) -> list[dict]:
    rows = []
    for repo in _repository_summaries(state):
        packages = await _package_summaries_for_repository(state, repo["name"])
        rows.append(
            {
                "name": repo["name"],
                "allow_overwrite": repo["allow_overwrite"],
                "package_count": len(packages),
            }
        )
    return rows


async def _package_index_context(request: Request, user: SessionUser, state: AppState) -> dict:
    repositories = await _repository_summaries_with_counts(state)
    requested_repository = request.query_params.get("repository")
    repository = _selected_repository(state, requested_repository)
    query = request.query_params.get("q", "")
    sort = request.query_params.get("sort", "name")

    packages: list[PackageSummary] = []
    if repository is not None:
        packages = await _package_summaries_for_repository(state, repository)
        packages = _filter_packages(packages, query)
        packages = _sort_packages(packages, sort)

    return {
        "user": user,
        "repositories": repositories,
        "configured_repository_count": len(repositories),
        "repository": repository,
        "packages": packages,
        "query": query,
        "sort": sort,
        "providers": state.settings.auth.providers,
        "storage_backend": state.settings.storage.backend,
        "setup_complete": request.query_params.get("setup") == "complete",
    }


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
        return RedirectResponse(_primary_app_path(redirect_url), status_code=302)

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

    return templates.TemplateResponse(
        request,
        "packages.html",
        await _package_index_context(request, user, state),
    )


@router.get("/packages")
async def packages_page(
    request: Request,
    user: SessionUser | None = Depends(get_optional_session),
    state: AppState = Depends(get_state),
):
    if user is None:
        return RedirectResponse("/login", status_code=302)

    query = request.url.query
    location = "/dashboard" + (f"?{query}" if query else "")
    return RedirectResponse(location, status_code=302)


@router.get("/repositories")
async def repositories_page(
    request: Request,
    user: SessionUser | None = Depends(get_optional_session),
    state: AppState = Depends(get_state),
):
    if user is None:
        return RedirectResponse("/login", status_code=302)

    return RedirectResponse("/dashboard", status_code=302)


@router.get("/repositories/{repository}")
async def repository_detail_page(
    repository: str,
    request: Request,
    user: SessionUser | None = Depends(get_optional_session),
    state: AppState = Depends(get_state),
):
    if user is None:
        return RedirectResponse("/login", status_code=302)

    if repository not in state.repositories.names:
        raise HTTPException(status_code=404, detail="Repository not found")

    return RedirectResponse(_packages_query(repository), status_code=302)


@router.get("/packages/{repository}/{package_path:path}", response_class=HTMLResponse)
async def package_detail_page(
    repository: str,
    package_path: str,
    request: Request,
    user: SessionUser | None = Depends(get_optional_session),
    state: AppState = Depends(get_state),
):
    if user is None:
        return RedirectResponse("/login", status_code=302)

    if repository not in state.repositories.names:
        raise HTTPException(status_code=404, detail="Repository not found")

    keys = await list_keys_under_prefix(state.store, repository)
    artifact_paths = [artifact_path_from_key(key, repository) for key in keys]
    package = build_package_detail(repository, package_path, artifact_paths)

    if package is None:
        raise HTTPException(status_code=404, detail="Package not found")

    return templates.TemplateResponse(
        request,
        "package_detail.html",
        {
            "user": user,
            "repositories": _repository_summaries(state),
            "repository": repository,
            "package": package,
            "providers": state.settings.auth.providers,
            "storage_backend": state.settings.storage.backend,
            "artifact_file_type": artifact_file_type,
            "artifact_file_download_path": artifact_file_download_path,
        },
    )


@router.post("/package-actions/delete-version")
async def delete_package_version(
    request: Request,
    user: SessionUser | None = Depends(get_optional_session),
    state: AppState = Depends(get_state),
    repository: str = Form(...),
    artifact_path: str = Form(...),
    version: str = Form(...),
):
    if user is None:
        return RedirectResponse("/login", status_code=302)

    if repository not in state.repositories.names:
        raise HTTPException(status_code=404, detail="Repository not found")

    result = await delete_artifact_version(
        state.store,
        repository=repository,
        artifact_path=artifact_path,
        version=version,
    )
    audit_log(
        event="artifact_delete",
        repository=repository,
        path=result.prefix,
        principal=_principal_name(user),
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        status_code=200,
        request_id=get_request_id(),
        scope="version",
        deleted_count=result.deleted_count,
    )

    keys = await list_keys_under_prefix(state.store, repository)
    artifact_paths = [artifact_path_from_key(key, repository) for key in keys]
    package = build_package_detail(repository, artifact_path, artifact_paths)
    if package is None:
        return RedirectResponse(_packages_query(repository), status_code=303)

    return RedirectResponse(_package_detail_path(repository, artifact_path), status_code=303)


@router.post("/package-actions/delete-package")
async def delete_package(
    request: Request,
    user: SessionUser | None = Depends(get_optional_session),
    state: AppState = Depends(get_state),
    repository: str = Form(...),
    artifact_path: str = Form(...),
):
    if user is None:
        return RedirectResponse("/login", status_code=302)

    if repository not in state.repositories.names:
        raise HTTPException(status_code=404, detail="Repository not found")

    result = await delete_artifact_package(
        state.store,
        repository=repository,
        artifact_path=artifact_path,
    )
    audit_log(
        event="artifact_delete",
        repository=repository,
        path=result.prefix,
        principal=_principal_name(user),
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        status_code=200,
        request_id=get_request_id(),
        scope="artifact",
        deleted_count=result.deleted_count,
    )

    return RedirectResponse(_packages_query(repository), status_code=303)
