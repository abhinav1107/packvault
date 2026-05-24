from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from packvault.observability.health import check_live, check_ready, check_startup
from packvault.observability.metrics import metrics_response
from packvault.runtime import AppState

router = APIRouter(tags=["health"])


def _get_app_state(request: Request) -> AppState | None:
    return getattr(request.app.state, "app_state", None)


def _probe_response(result) -> JSONResponse:
    return JSONResponse(
        content=result.as_dict(),
        status_code=200 if result.ok else 503,
    )


@router.get("/livez")
async def livez(request: Request) -> JSONResponse:
    return _probe_response(check_live(_get_app_state(request)))


@router.get("/startupz")
async def startupz(request: Request) -> JSONResponse:
    return _probe_response(check_startup(_get_app_state(request)))


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    return _probe_response(await check_ready(_get_app_state(request)))


@router.get("/metrics")
async def metrics() -> Response:
    return Response(
        content=metrics_response(),
        media_type="text/plain; version=0.0.4; charset=utf-8"
    )
