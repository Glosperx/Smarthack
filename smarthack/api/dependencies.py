"""
# API dependencies

FastAPI dependency providers for HTTP route handlers.

The following can be imported from this module:
- `get_http_client`
- `get_today`
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import Request
import httpx

from smarthack import config
from smarthack.utils.dates import today_in_tz


def get_http_client(request: Request) -> httpx.AsyncClient:
    """
    Retrieve the shared application HTTP client from application state.

    :param request: Incoming FastAPI HTTP request.

    :returns client: An open asynchronous HTTP client instance.
    """
    return request.app.state.http


def get_today() -> date:
    """
    Return today's date in the configured application timezone.

    :returns today: Calendar date object for the current day.
    """
    tz_name = config.timezone()
    return today_in_tz(tz_name, now=datetime.now(ZoneInfo(tz_name)))


__all__ = ["get_http_client", "get_today"]
