"""
# Parks service

Domain service validating, filtering, and caching wind park locations.

The following can be imported from this module:
- `clear_cache`
- `list_parks`
"""

import logging
import time

import httpx
from pydantic import ValidationError

from smarthack.clients import supabase_parks
from smarthack.schemas.parks import Park

logger = logging.getLogger(__name__)

_TTL_SECONDS = 60
_cache: tuple[float, list[Park]] | None = None


async def list_parks(http: httpx.AsyncClient) -> list[Park]:
    """
    Retrieve and validate wind park locations with in-memory caching.

    Validates coordinates and silently skips malformed rows.

    :param http: Asynchronous HTTP client for upstream queries.

    :returns parks: List of validated `Park` model instances.
    :raises httpx.HTTPError: When the upstream client request fails.
    """
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _TTL_SECONDS:
        return _cache[1]

    parks: list[Park] = []
    raw_rows = await supabase_parks.fetch_parks(http)
    for row in raw_rows:
        try:
            parks.append(Park.model_validate(row))
        except ValidationError:
            logger.warning("Skipping park row with invalid data: id=%s", row.get("id"))

    _cache = (now, parks)
    return parks


def clear_cache() -> None:
    """
    Clear the cached park locations to force a fresh upstream request.

    :returns: None.
    """
    global _cache
    _cache = None


__all__ = ["clear_cache", "list_parks"]
