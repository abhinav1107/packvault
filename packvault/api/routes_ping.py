from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse, Response

from packvault.api.deps import get_state
from packvault.runtime import AppState
from packvault.security.rate_limit import FixedWindowRateLimiter

logger = logging.getLogger("packvault.access")

router = APIRouter(tags=["health"])

_GLOBAL_PING_KEY = "global"
_limiters: dict[int, FixedWindowRateLimiter] = {}


def _limiter_for(settings: AppState) -> FixedWindowRateLimiter:
    limit = settings.settings.server.ping_rate_limit_per_minute
    limiter = _limiters.get(limit)

    if limiter is None:
        limiter = FixedWindowRateLimiter(max_requests=limit, window_seconds=60.0)
        _limiters[limit] = limiter

    return limiter


def _client_ip(request: Request) -> str:
    if request.client is None:
        return "unknown"
    return request.client.host


@router.get("/ping")
async def ping(request: Request, state: AppState = Depends(get_state)) -> Response:
    limiter = _limiter_for(state)
    client_ip = _client_ip(request)

    if not limiter.allow(_GLOBAL_PING_KEY):
        logger.info("ping rate limited client=%s", client_ip)
        return PlainTextResponse(
            "too many requests",
            status_code=429,
            headers={"Retry-After": str(limiter.retry_after_seconds)},
        )

    logger.info("ping client=%s", client_ip)
    return PlainTextResponse("pong", media_type="text/plain")
