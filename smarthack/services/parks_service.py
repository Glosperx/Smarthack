"""
# Parks service

Domain service validating, filtering, and caching wind park locations and turbine diagnostics.

The following can be imported from this module:
- `clear_cache`
- `list_parks`
- `list_turbines_for_park`
"""

from datetime import date
import logging
import time
from typing import Any

import httpx
from pydantic import ValidationError

from smarthack.clients import supabase
from smarthack.constants import MAINTENANCE_TABLE
from smarthack.schemas.parks import Park, ParkTurbines, TurbinePrediction, TurbineToday

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
    raw_rows = await supabase.fetch_parks(http)
    for row in raw_rows:
        try:
            parks.append(Park.model_validate(row))
        except ValidationError:
            logger.warning("Skipping park row with invalid data: id=%s", row.get("id"))

    _cache = (now, parks)
    return parks


async def list_turbines_for_park(http: httpx.AsyncClient, park_id: int, day: date) -> ParkTurbines:
    """
    Retrieve wind turbines and today's maintenance predictions for a specific park.

    Filters and sorts turbines: riskiest turbines first, followed by turbines without predictions.

    :param http: Asynchronous HTTP client for upstream queries.
    :param park_id: Unique numeric identifier of the park.
    :param day: Target calendar date for prediction lookups.

    :returns result: `ParkTurbines` payload containing evaluated turbines.
    :raises httpx.HTTPError: When the upstream client request fails.
    """
    raw_rows = await supabase.fetch_turbines_with_predictions(http, park_id, day)
    turbines: list[TurbineToday] = []

    for row in raw_rows:
        preds: list[dict[str, Any]] = (
            row.get(MAINTENANCE_TABLE) or row.get("turbine_mentenance") or []
        )
        prediction: TurbinePrediction | None = None
        if preds:
            try:
                prediction = TurbinePrediction.model_validate(preds[0])
            except ValidationError:
                logger.warning("Bad maintenance row for turbine %s", row.get("id"))

        turbines.append(TurbineToday(id=row["id"], prediction=prediction))

    turbines.sort(
        key=lambda t: (
            t.prediction is None,
            -(t.prediction.daily_fault_probability if t.prediction else 0.0),
            t.id,
        )
    )
    return ParkTurbines(park_id=park_id, date=day, turbines=turbines)


def clear_cache() -> None:
    """
    Clear the cached park locations to force a fresh upstream request.

    :returns: None.
    """
    global _cache
    _cache = None


__all__ = ["clear_cache", "list_parks", "list_turbines_for_park"]
