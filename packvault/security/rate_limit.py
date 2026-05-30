from __future__ import annotations

import threading
import time


class FixedWindowRateLimiter:
    """In-memory per-key fixed-window rate limiter (thread-safe)."""

    def __init__(self, max_requests: int, window_seconds: float = 60.0) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._windows: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()

        with self._lock:
            count, window_start = self._windows.get(key, (0, now))

            if now - window_start >= self._window_seconds:
                count = 0
                window_start = now

            if count >= self._max_requests:
                return False

            self._windows[key] = (count + 1, window_start)
            return True

    @property
    def retry_after_seconds(self) -> int:
        return max(1, int(self._window_seconds))
