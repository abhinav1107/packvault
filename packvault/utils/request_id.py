from __future__ import annotations

import uuid
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def new_request_id() -> str:
    return str(uuid.uuid4())


def get_request_id() -> str:
    return request_id_var.get() or ""
