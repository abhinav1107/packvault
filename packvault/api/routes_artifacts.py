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
    list_artifacts_for_ui,
    normalize_search_prefix,
)
from packvault.ui.templates_ctx import templates
from packvault.utils.errors import NotFoundError
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

    path_prefix = normalize_search_prefix(prefix_raw)

    result = await list_artifacts_for_ui(
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
            "items": result.items,
            "has_more": result.has_more,
            "next_cursor": result.continuation_token,
            "prev_cursor": cursor,
            "deleted": deleted,
            "artifacts_query": _artifacts_query,
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
        )
        raise

    redirect_prefix = prefix.strip() or _artifact_dir_prefix(maven_req.artifact_path)
    redirect_url = _artifacts_query(
        repository=maven_req.repository,
        prefix=redirect_prefix,
        show_all=show_all == "1",
        deleted=True,
    )
    return RedirectResponse(redirect_url, status_code=303)


def _artifact_dir_prefix(artifact_path: str) -> str:
    if "/" not in artifact_path:
        return ""
    return artifact_path.rsplit("/", 1)[0]
