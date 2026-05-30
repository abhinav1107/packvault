from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


def asgi_with_local_port(app: ASGIApp, port: int) -> ASGIApp:
    async def wrapped(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            host, _ = scope.get("server") or ("testserver", 0)
            scope = {**scope, "server": (host, port)}
        await app(scope, receive, send)

    return wrapped
