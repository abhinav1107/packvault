from __future__ import annotations

import time

from packvault.security.rate_limit import FixedWindowRateLimiter


def test_global_rate_limit_is_shared_across_keys() -> None:
    limiter = FixedWindowRateLimiter(max_requests=2, window_seconds=60.0)

    assert limiter.allow("global")
    assert limiter.allow("global")
    assert not limiter.allow("global")


def test_rate_limit_resets_after_window() -> None:
    limiter = FixedWindowRateLimiter(max_requests=1, window_seconds=0.05)

    assert limiter.allow("global")
    assert not limiter.allow("global")

    time.sleep(0.06)

    assert limiter.allow("global")
