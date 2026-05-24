from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from packvault.runtime import AppState
from packvault.utils.errors import ServiceUnavailableError


@dataclass
class ProbeResult:
    ok: bool
    status: str
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        if self.detail:
            payload["detail"] = self.detail
        return payload


def check_live(state: AppState | None) -> ProbeResult:
    """Liveness: process is up and not shutting down. No dependency I/O."""
    if state is None:
        return ProbeResult(ok=True, status="ok")
    if state.shutting_down:
        return ProbeResult(ok=False, status="shutting_down", detail="process is terminating")
    return ProbeResult(ok=True, status="ok")


def check_startup(state: AppState | None) -> ProbeResult:
    """Startup: one-time initialization finished (storage checked at boot)."""
    if state is None or not state.startup_complete:
        return ProbeResult(ok=False, status="starting", detail="initialization in progress")
    return ProbeResult(ok=True, status="started")


async def check_ready(state: AppState | None) -> ProbeResult:
    """Readiness: safe to receive traffic; re-checks storage each call."""
    if state is None or not state.startup_complete:
        return ProbeResult(ok=False, status="starting", detail="initialization in progress")

    if state.shutting_down:
        return ProbeResult(ok=False, status="shutting_down", detail="process is terminating")

    try:
        await state.store.check_health()
    except ServiceUnavailableError as e:
        return ProbeResult(ok=False, status="not_ready", detail=e.message)
    except Exception:
        return ProbeResult(
            ok=False,
            status="not_ready",
            detail="unexpected readiness check failure",
        )

    return ProbeResult(ok=True, status="ready")
