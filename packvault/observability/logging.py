from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from packvault.utils.request_id import get_request_id

LogFormat = Literal["json", "standard"]
LogLevelName = Literal["DEBUG", "INFO", "WARNING", "WARN", "ERROR"]

LEVEL_NAMES: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
}

DEFAULT_LEVEL = "INFO"
DEFAULT_FORMAT: LogFormat = "json"

_SENSITIVE_FIELD_NAMES = {
    "authorization",
    "cookie",
    "password",
    "token",
    "raw_token",
    "client_secret",
    "session",
    "session_cookie",
}


@dataclass(frozen=True)
class LoggingOptions:
    level: int
    level_name: str
    format: LogFormat


def resolve_logging_options(
    *,
    cli_level: str | None = None,
    cli_format: str | None = None,
    settings_level: str | None = None,
    settings_format: str | None = None,
) -> LoggingOptions:
    """Resolve level/format with precedence: CLI > env > config > defaults."""
    level_name = (
        _normalize_level(cli_level)
        or _normalize_level(os.environ.get("PACKVAULT_LOG_LEVEL"))
        or _normalize_level(settings_level)
        or DEFAULT_LEVEL
    )
    fmt = (
        _normalize_format(cli_format)
        or _normalize_format(os.environ.get("PACKVAULT_LOG_FORMAT"))
        or _normalize_format(settings_format)
        or DEFAULT_FORMAT
    )
    return LoggingOptions(
        level=LEVEL_NAMES[level_name],
        level_name=level_name,
        format=fmt,
    )


def _normalize_level(value: str | None) -> str | None:
    if value is None:
        return None
    name = value.strip().upper()
    if name not in LEVEL_NAMES:
        raise ValueError(f"Invalid log level {value!r}; use DEBUG, INFO, WARN/WARNING, or ERROR")
    return "WARNING" if name == "WARN" else name


def _normalize_format(value: str | None) -> LogFormat | None:
    if value is None:
        return None
    fmt = value.strip().lower()
    if fmt not in ("json", "standard"):
        raise ValueError(f"Invalid log format {value!r}; use json or standard")
    return fmt  # type: ignore[return-value]


def _base_fields(record: logging.LogRecord) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": record.levelname,
        "logger": record.name,
        "module": record.module,
        "filename": record.filename,
        "line": record.lineno,
        "message": record.getMessage(),
    }
    rid = get_request_id()
    if rid:
        fields["request_id"] = rid
    if hasattr(record, "extra_fields"):
        fields.update(record.extra_fields)  # type: ignore[attr-defined]
    return fields


class JsonFormatter(logging.Formatter):
    """Structured JSON logs for production (design doc default)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = _base_fields(record)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class StandardFormatter(logging.Formatter):
    """Human-readable logs for local development."""

    def format(self, record: logging.LogRecord) -> str:
        fields = _base_fields(record)
        location = f"{fields['filename']}:{fields['line']}"
        line = (
            f"{fields['timestamp']} {fields['level']} "
            f"{fields['logger']} ({fields['module']}) [{location}] {fields['message']}"
        )
        if fields.get("request_id"):
            line += f" request_id={fields['request_id']}"
        for key, value in fields.items():
            if key not in {
                "timestamp",
                "level",
                "logger",
                "module",
                "filename",
                "line",
                "message",
                "request_id",
            }:
                line += f" {key}={value}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def setup_logging(options: LoggingOptions | None = None, **kwargs: Any) -> LoggingOptions:
    """Configure root logger. Pass LoggingOptions or keyword overrides for tests/CLI."""
    if options is None:
        options = resolve_logging_options(
            cli_level=kwargs.get("cli_level"),
            cli_format=kwargs.get("cli_format"),
            settings_level=kwargs.get("settings_level"),
            settings_format=kwargs.get("settings_format"),
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if options.format == "json" else StandardFormatter()
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(options.level)

    # Align common library loggers with app level.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        logging.getLogger(name).setLevel(options.level)

    return options


def _sanitize_log_fields(fields: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}

    for key, value in fields.items():
        normalized_key = key.lower()

        if any(sensitive in normalized_key for sensitive in _SENSITIVE_FIELD_NAMES):
            sanitized[key] = "[REDACTED]"
        else:
            sanitized[key] = value

    return sanitized


def audit_log(**fields: Any) -> None:
    """Structured audit entry for write operations (design doc section 15)."""
    logger = logging.getLogger("packvault.audit")
    safe_fields = _sanitize_log_fields(fields)
    logger.info("artifact_write", extra={"extra_fields": safe_fields})
