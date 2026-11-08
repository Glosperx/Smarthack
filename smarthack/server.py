"""
# HTTP service

A minimal ASGI application served by Uvicorn. `GET /health` reports liveness.

The following can be imported from this module:
- `app`
"""

from collections.abc import Awaitable, Callable
from typing import Any


async def app(
    scope: dict[str, Any],
    receive: Callable[[], Awaitable[dict[str, Any]]],
    send: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    """
    Handle ASGI lifecycle events and HTTP health requests.

    :param scope: The connection metadata supplied by the server.
    :param receive: Receive the next event from the server.
    :param send: Send an event to the server.
    """
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1000})
        return

    if scope["path"] != "/health":
        status, body = 404, b'{"detail":"Not Found"}'
    elif scope["method"] not in {"GET", "HEAD"}:
        status, body = 405, b'{"detail":"Method Not Allowed"}'
    else:
        status, body = 200, b'{"status":"ok"}'

    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    if status == 405:
        headers.append((b"allow", b"GET, HEAD"))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": b"" if scope["method"] == "HEAD" else body})


__all__ = ["app"]
