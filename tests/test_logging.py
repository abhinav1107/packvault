from __future__ import annotations

import logging

import pytest
from httpx import ASGITransport, AsyncClient

from packvault.config.settings import Settings
from packvault.main import create_app
from packvault.observability.logging import LoggingOptions, setup_http_access_logging
from tests.asgi_helpers import asgi_with_local_port
from tests.test_health import _make_app_state


@pytest.mark.asyncio
async def test_app_access_log_middleware_logs_ui_requests(
    caplog: pytest.LogCaptureFixture,
    test_settings: Settings,
) -> None:
    setup_http_access_logging(LoggingOptions(level=logging.INFO, level_name="INFO", format="json"))
    http_logger = logging.getLogger("packvault.http")
    for handler in list(http_logger.handlers):
        http_logger.removeHandler(handler)
    http_logger.propagate = True
    caplog.set_level(logging.INFO, logger="packvault.http")

    app = create_app(test_settings)
    app.state.app_state = _make_app_state(test_settings, startup_complete=True)
    transport = ASGITransport(app=asgi_with_local_port(app, test_settings.server.port))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/login")

    assert response.status_code == 200
    assert any(
        record.name == "packvault.http" and "GET /login HTTP" in record.message
        for record in caplog.records
    )
