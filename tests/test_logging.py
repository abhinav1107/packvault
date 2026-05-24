from __future__ import annotations

import json
import logging

import pytest

from packvault.observability.logging import (
    JsonFormatter,
    StandardFormatter,
    resolve_logging_options,
    setup_logging,
)


def test_resolve_precedence_cli_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PACKVAULT_LOG_LEVEL", "ERROR")
    opts = resolve_logging_options(cli_level="DEBUG", settings_level="INFO")
    assert opts.level_name == "DEBUG"


def test_resolve_env_over_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PACKVAULT_LOG_LEVEL", "WARNING")
    opts = resolve_logging_options(settings_level="INFO")
    assert opts.level_name == "WARNING"


def test_warn_normalizes_to_warning() -> None:
    opts = resolve_logging_options(cli_level="warn")
    assert opts.level_name == "WARNING"


def test_json_formatter_includes_module_and_file() -> None:
    record = logging.LogRecord(
        name="packvault.api.routes_maven",
        level=logging.INFO,
        pathname=__file__,
        lineno=42,
        msg="hello",
        args=(),
        exc_info=None,
    )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["logger"] == "packvault.api.routes_maven"
    assert payload["module"] == "test_logging"
    assert payload["filename"] == "test_logging.py"
    assert payload["line"] == 42
    assert payload["message"] == "hello"
    assert "timestamp" in payload


def test_standard_formatter_includes_module_and_file() -> None:
    record = logging.LogRecord(
        name="packvault.main",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="started",
        args=(),
        exc_info=None,
    )
    line = StandardFormatter().format(record)
    assert "packvault.main" in line
    assert "test_logging" in line
    assert "started" in line


def test_setup_logging_standard(capsys) -> None:
    setup_logging(
        resolve_logging_options(cli_level="INFO", cli_format="standard"),
    )
    logging.getLogger("packvault.test").warning("visible")
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "packvault.test" in out
