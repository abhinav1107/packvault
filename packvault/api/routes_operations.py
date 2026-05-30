from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response

from packvault.api.deps import get_optional_app_state
from packvault.observability.health import check_live, check_ready, check_startup
from packvault.observability.metrics import metrics_response
from packvault.runtime import AppState

router = APIRouter(tags=["operations"])

METRICS_MEDIA_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _probe_response(result) -> JSONResponse:
    return JSONResponse(
        content=result.as_dict(),
        status_code=200 if result.ok else 503,
    )


@router.get("/livez")
async def livez(state: AppState | None = Depends(get_optional_app_state)) -> JSONResponse:
    return _probe_response(check_live(state))


@router.get("/startupz")
async def startupz(state: AppState | None = Depends(get_optional_app_state)) -> JSONResponse:
    return _probe_response(check_startup(state))


@router.get("/readyz")
async def readyz(state: AppState | None = Depends(get_optional_app_state)) -> JSONResponse:
    return _probe_response(await check_ready(state))


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=metrics_response(), media_type=METRICS_MEDIA_TYPE)
