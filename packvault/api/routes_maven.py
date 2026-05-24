from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse

from packvault.api.deps import get_auth_context, get_state
from packvault.auth.permissions import (
    AuthContext,
    require_token_read,
    require_token_write,
)
from packvault.maven.content_types import guess_content_type
from packvault.maven.paths import parse_maven_request
from packvault.observability.logging import audit_log
from packvault.observability.metrics import (
    AUTH_FAILURES,
    DOWNLOAD_BYTES,
    MAVEN_DURATION,
    MAVEN_REQUESTS,
    STORAGE_OPS,
    UPLOAD_BYTES,
)
from packvault.runtime import AppState
from packvault.utils.errors import BadRequestError, NotFoundError, PackVaultError, UnauthorizedError

router = APIRouter(tags=["maven"])


def _backend_label(state: AppState) -> str:
    return state.settings.storage.backend


async def _authenticate_read(
    ctx: AuthContext,
    repository: str,
    state: AppState,
) -> None:
    if ctx.token is not None:
        require_token_read(ctx, repository)
        return

    if state.settings.security.anonymous_read:
        return

    raise UnauthorizedError("Authentication required")


async def _authenticate_write(ctx: AuthContext, repository: str) -> None:
    require_token_write(ctx, repository)


def _record_request(method: str, repository: str, status: int, elapsed: float) -> None:
    MAVEN_REQUESTS.labels(method=method, repository=repository, status=str(status)).inc()
    MAVEN_DURATION.labels(method=method, repository=repository).observe(elapsed)


def _parse_content_length(request: Request) -> int | None:
    content_length = request.headers.get("content-length")

    if not content_length:
        return None

    try:
        declared_size = int(content_length)
    except ValueError:
        raise BadRequestError("Invalid Content-Length") from None

    if declared_size < 0:
        raise BadRequestError("Invalid Content-Length")

    return declared_size


def _audit_failed_write(
    *,
    request: Request,
    repository: str,
    path: str,
    principal: str,
    status_code: int,
    bytes_uploaded: int = 0,
) -> None:
    audit_log(
        repository=repository,
        path=path,
        principal=principal,
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        status_code=status_code,
        bytes_uploaded=bytes_uploaded,
    )


@router.api_route("/{repository}/{artifact_path:path}", methods=["GET", "HEAD"])
async def get_artifact(
    repository: str,
    artifact_path: str,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    state: AppState = Depends(get_state),
) -> Response:
    start = time.perf_counter()
    metric_repository = repository

    try:
        maven_req = parse_maven_request(
            repository,
            artifact_path,
            known_repositories=state.repositories.names,
        )
        metric_repository = maven_req.repository

        await _authenticate_read(ctx, maven_req.repository, state)

        meta = await state.store.head(maven_req.storage_key)
        STORAGE_OPS.labels(operation="head", backend=_backend_label(state)).inc()

        if meta is None:
            raise NotFoundError("Artifact not found")

        content_type = meta.content_type or guess_content_type(maven_req.artifact_path)

        if request.method == "HEAD":
            _record_request(
                request.method,
                metric_repository,
                200,
                time.perf_counter() - start,
            )
            return Response(
                status_code=200,
                headers={
                    "Content-Length": str(meta.size),
                    "Content-Type": content_type,
                },
            )

        stream = await state.store.get(maven_req.storage_key)
        STORAGE_OPS.labels(operation="get", backend=_backend_label(state)).inc()

        async def body() -> AsyncIterator[bytes]:
            async for chunk in stream:
                DOWNLOAD_BYTES.labels(repository=metric_repository).inc(len(chunk))
                yield chunk

        _record_request(
            request.method,
            metric_repository,
            200,
            time.perf_counter() - start,
        )

        return StreamingResponse(
            body(),
            media_type=content_type,
            headers={"Content-Length": str(meta.size)},
        )

    except UnauthorizedError:
        AUTH_FAILURES.labels(kind="maven").inc()
        _record_request(request.method, metric_repository, 401, time.perf_counter() - start)
        raise

    except PackVaultError as exc:
        _record_request(
            request.method,
            metric_repository,
            exc.status_code,
            time.perf_counter() - start,
        )
        raise


@router.put("/{repository}/{artifact_path:path}")
async def put_artifact(
    repository: str,
    artifact_path: str,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    state: AppState = Depends(get_state),
) -> Response:
    start = time.perf_counter()
    uploaded = 0
    metric_repository = repository
    audit_repository = repository
    audit_path = artifact_path
    principal_name = ctx.token.name if ctx.token else "unknown"

    try:
        maven_req = parse_maven_request(
            repository,
            artifact_path,
            known_repositories=state.repositories.names,
        )
        metric_repository = maven_req.repository
        audit_repository = maven_req.repository
        audit_path = maven_req.artifact_path

        await _authenticate_write(ctx, maven_req.repository)

        repo_policy = state.repositories.require(maven_req.repository)

        declared_size = _parse_content_length(request)
        if declared_size is not None and declared_size > state.settings.server.max_upload_bytes:
            raise BadRequestError("Upload too large")

        exists = await state.store.exists(maven_req.storage_key)
        STORAGE_OPS.labels(operation="head", backend=_backend_label(state)).inc()

        repo_policy.check_overwrite(exists=exists)

        request_body = request.stream()

        async def counting_stream() -> AsyncIterator[bytes]:
            nonlocal uploaded

            async for chunk in request_body:
                uploaded += len(chunk)

                if uploaded > state.settings.server.max_upload_bytes:
                    raise BadRequestError("Upload too large")

                yield chunk

        content_type = request.headers.get("content-type") or guess_content_type(
            maven_req.artifact_path
        )

        await state.store.put(
            maven_req.storage_key,
            counting_stream(),
            content_type=content_type,
            if_none_match=not repo_policy.allow_overwrite,
        )

        STORAGE_OPS.labels(operation="put", backend=_backend_label(state)).inc()
        UPLOAD_BYTES.labels(repository=metric_repository).inc(uploaded)

        audit_log(
            repository=audit_repository,
            path=audit_path,
            principal=principal_name,
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            status_code=201,
            bytes_uploaded=uploaded,
        )

        _record_request("PUT", metric_repository, 201, time.perf_counter() - start)
        return Response(status_code=201)

    except UnauthorizedError:
        AUTH_FAILURES.labels(kind="maven").inc()
        _record_request("PUT", metric_repository, 401, time.perf_counter() - start)

        _audit_failed_write(
            request=request,
            repository=audit_repository,
            path=audit_path,
            principal=principal_name,
            status_code=401,
            bytes_uploaded=uploaded,
        )

        raise

    except PackVaultError as exc:
        _record_request("PUT", metric_repository, exc.status_code, time.perf_counter() - start)

        _audit_failed_write(
            request=request,
            repository=audit_repository,
            path=audit_path,
            principal=principal_name,
            status_code=exc.status_code,
            bytes_uploaded=uploaded,
        )

        raise