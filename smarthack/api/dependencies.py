"""
# API dependencies

FastAPI dependency providers for HTTP route handlers.

The following can be imported from this module:
- `get_http_client`
"""

from fastapi import Request
import httpx


def get_http_client(request: Request) -> httpx.AsyncClient:
    """
    Retrieve the shared application HTTP client from application state.

    :param request: Incoming FastAPI HTTP request.

    :returns client: An open asynchronous HTTP client instance.
    """
    return request.app.state.http


__all__ = ["get_http_client"]
