from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from packvault.api.deps import get_optional_session, get_state
from packvault.auth.bootstrap import post_login_redirect_path
from packvault.auth.permissions import SessionUser
from packvault.maven.paths import parse_maven_request
from packvault.observability.logging import audit_log
from packvault.runtime import AppState
from packvault.ui.artifacts import (
    breadcrumb_segments,
    delete_under_prefix,
    list_artifact_directory,
    normalize_search_prefix,
    parent_artifact_prefix,
)
from packvault.ui.templates_ctx import templates
from packvault.utils.errors import BadRequestError, NotFoundError
from packvault.utils.request_id import get_request_id

router = APIRouter(tags=["ui"])


def _principal_name(user: SessionUser) -> str:
    return user.name or user.subject


def _repository_names(state: AppState) -> list[str]:
    return [repo.name for repo in state.settings.repositories]


def _selected_repository(state: AppState, requested: str | None) -> str:
    names = _repository_names(state)
    if requested and requested in names:
        return requested
    return names[0]


def _artifacts_query(
    *,
    repository: str,
    prefix: str = "",
    show_all: bool = False,
    cursor: str | None = None,
    deleted: bool = False,
    deleted_count: int | None = None,
    delete_scope: str | None = None,
) -> str:
    params: dict[str, str] = {"repository": repository}
    if prefix:
        params["prefix"] = prefix
    if show_all:
        params["show_all"] = "1"
    if cursor:
        params["cursor"] = cursor
    if deleted:
        params["deleted"] = "1"
    if deleted_count is not None:
        params["deleted_count"] = str(deleted_count)
    if delete_scope:
        params["delete_scope"] = delete_scope
    return "/artifacts?" + urlencode(params)


async def _require_dashboard_user(
    request: Request,
    user: SessionUser | None,
    state: AppState,
) -> SessionUser | RedirectResponse:
    if user is None:
        return RedirectResponse("/login", status_code=302)

    redirect_url = post_login_redirect_path(
        user,
        state.settings,
        system_initialized=state.system_initialized,
    )
    if redirect_url != "/dashboard":
        return RedirectResponse(redirect_url, status_code=302)

    return user


@router.get("/artifacts", response_class=HTMLResponse)
async def artifacts_page(
    request: Request,
    user: SessionUser | None = Depends(get_optional_session),
    state: AppState = Depends(get_state),
):
    auth_result = await _require_dashboard_user(request, user, state)
    if isinstance(auth_result, RedirectResponse):
        return auth_result
    user = auth_result

    repository = _selected_repository(state, request.query_params.get("repository"))
    prefix_raw = request.query_params.get("prefix", "")
    show_all = request.query_params.get("show_all") == "1"
    cursor = request.query_params.get("cursor")
    deleted = request.query_params.get("deleted") == "1"
    deleted_count_raw = request.query_params.get("deleted_count")
    delete_scope = request.query_params.get("delete_scope")

    deleted_count: int | None = None
    if deleted_count_raw and deleted_count_raw.isdigit():
        deleted_count = int(deleted_count_raw)

    path_prefix = normalize_search_prefix(prefix_raw)

    browse = await list_artifact_directory(
        state.store,
        repository=repository,
        path_prefix=path_prefix,
        show_all=show_all,
        continuation_token=cursor,
    )

    return templates.TemplateResponse(
        request,
        "artifacts.html",
        {
            "user": user,
            "repositories": _repository_names(state),
            "repository": repository,
            "prefix": path_prefix,
            "show_all": show_all,
            "entries": browse.entries,
            "browse_level": browse.level,
            "can_delete_artifact": browse.can_delete_artifact,
            "can_delete_version": browse.can_delete_version,
            "can_select_versions": browse.can_select_versions,
            "has_more": browse.has_more,
            "next_cursor": browse.continuation_token,
            "prev_cursor": cursor,
            "deleted": deleted,
            "deleted_count": deleted_count,
            "delete_scope": delete_scope,
            "artifacts_query": _artifacts_query,
            "parent_prefix": parent_artifact_prefix(path_prefix),
            "breadcrumbs": breadcrumb_segments(path_prefix),
        },
    )


@router.post("/artifacts/delete")
async def delete_artifact(
    request: Request,
    user: SessionUser | None = Depends(get_optional_session),
    state: AppState = Depends(get_state),
    repository: str = Form(...),
    path: str = Form(...),
    prefix: str = Form(""),
    show_all: str = Form(""),
):
    auth_result = await _require_dashboard_user(request, user, state)
    if isinstance(auth_result, RedirectResponse):
        return auth_result
    user = auth_result

    known = set(_repository_names(state))
    maven_req = parse_maven_request(repository, path, known_repositories=known)
    principal = _principal_name(user)
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    request_id = get_request_id()

    try:
        await state.store.delete(maven_req.storage_key)
        audit_log(
            event="artifact_delete",
            repository=maven_req.repository,
            path=maven_req.artifact_path,
            principal=principal,
            client_ip=client_ip,
            user_agent=user_agent,
            status_code=200,
            request_id=request_id,
            scope="file",
        )
    except NotFoundError:
        audit_log(
            event="artifact_delete",
            repository=maven_req.repository,
            path=maven_req.artifact_path,
            principal=principal,
            client_ip=client_ip,
            user_agent=user_agent,
            status_code=404,
            request_id=request_id,
            scope="file",
        )
        raise

    redirect_prefix = prefix.strip() or parent_artifact_prefix(maven_req.artifact_path)
    redirect_url = _artifacts_query(
        repository=maven_req.repository,
        prefix=redirect_prefix,
        show_all=show_all == "1",
        deleted=True,
        deleted_count=1,
        delete_scope="file",
    )
    return RedirectResponse(redirect_url, status_code=303)


@router.post("/artifacts/delete-version")
async def delete_version(
    request: Request,
    user: SessionUser | None = Depends(get_optional_session),
    state: AppState = Depends(get_state),
    repository: str = Form(...),
    prefix: str = Form(...),
    show_all: str = Form(""),
):
    return await _delete_scoped_prefix(
        request,
        user,
        state,
        repository=repository,
        prefix=prefix,
        show_all=show_all,
        scope="version",
        redirect_prefix=parent_artifact_prefix(normalize_search_prefix(prefix)),
    )


@router.post("/artifacts/delete-artifact")
async def delete_artifact_tree(
    request: Request,
    user: SessionUser | None = Depends(get_optional_session),
    state: AppState = Depends(get_state),
    repository: str = Form(...),
    prefix: str = Form(...),
    show_all: str = Form(""),
):
    normalized = normalize_search_prefix(prefix)
    return await _delete_scoped_prefix(
        request,
        user,
        state,
        repository=repository,
        prefix=normalized,
        show_all=show_all,
        scope="artifact",
        redirect_prefix=parent_artifact_prefix(normalized),
    )


@router.post("/artifacts/delete-versions")
async def delete_versions(
    request: Request,
    user: SessionUser | None = Depends(get_optional_session),
    state: AppState = Depends(get_state),
    repository: str = Form(...),
    prefix: str = Form(...),
    versions: list[str] = Form(default=[]),
    show_all: str = Form(""),
):
    auth_result = await _require_dashboard_user(request, user, state)
    if isinstance(auth_result, RedirectResponse):
        return auth_result
    user = auth_result

    if not versions:
        raise BadRequestError("Select at least one version to delete")

    artifact_prefix = normalize_search_prefix(prefix)
    total_deleted = 0
    principal = _principal_name(user)
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    request_id = get_request_id()

    for version in versions:
        version_prefix = normalize_search_prefix(f"{artifact_prefix}/{version}")
        try:
            result = await delete_under_prefix(
                state.store,
                repository=repository,
                path_prefix=version_prefix,
            )
        except NotFoundError:
            continue
        total_deleted += result.deleted_count
        audit_log(
            event="artifact_delete",
            repository=repository,
            path=version_prefix,
            principal=principal,
            client_ip=client_ip,
            user_agent=user_agent,
            status_code=200,
            request_id=request_id,
            scope="version",
            deleted_count=result.deleted_count,
        )

    if total_deleted == 0:
        raise NotFoundError("No artifacts found for selected versions")

    redirect_url = _artifacts_query(
        repository=repository,
        prefix=artifact_prefix,
        show_all=show_all == "1",
        deleted=True,
        deleted_count=total_deleted,
        delete_scope="version",
    )
    return RedirectResponse(redirect_url, status_code=303)


async def _delete_scoped_prefix(
    request: Request,
    user: SessionUser | None,
    state: AppState,
    *,
    repository: str,
    prefix: str,
    show_all: str,
    scope: str,
    redirect_prefix: str,
) -> RedirectResponse:
    auth_result = await _require_dashboard_user(request, user, state)
    if isinstance(auth_result, RedirectResponse):
        return auth_result
    user = auth_result

    normalized_prefix = normalize_search_prefix(prefix)
    principal = _principal_name(user)
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    request_id = get_request_id()

    try:
        result = await delete_under_prefix(
            state.store,
            repository=repository,
            path_prefix=normalized_prefix,
        )
        audit_log(
            event="artifact_delete",
            repository=repository,
            path=result.prefix,
            principal=principal,
            client_ip=client_ip,
            user_agent=user_agent,
            status_code=200,
            request_id=request_id,
            scope=scope,
            deleted_count=result.deleted_count,
        )
    except NotFoundError:
        audit_log(
            event="artifact_delete",
            repository=repository,
            path=normalized_prefix,
            principal=principal,
            client_ip=client_ip,
            user_agent=user_agent,
            status_code=404,
            request_id=request_id,
            scope=scope,
        )
        raise

    redirect_url = _artifacts_query(
        repository=repository,
        prefix=redirect_prefix,
        show_all=show_all == "1",
        deleted=True,
        deleted_count=result.deleted_count,
        delete_scope=scope,
    )
    return RedirectResponse(redirect_url, status_code=303)
