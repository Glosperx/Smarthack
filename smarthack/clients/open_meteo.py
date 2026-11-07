"""
# Open-Meteo client

Outbound HTTP client for the Open-Meteo forecast API (free, no key). Asks for several
locations in one request, which the API supports with comma-separated coordinates, and
returns one list of hourly records per location, in the order the locations were given.

Times are requested as Unix seconds, so they are UTC instants with no timezone parsing.

The following can be imported from this module:
- `HOURLY_VARIABLES`
- `fetch_hourly_forecasts`
"""

from datetime import datetime, timezone
from itertools import batched
from typing import Any

import httpx

from smarthack import config

#: Hourly variables requested, named as Open-Meteo and the `park_wind_forecast` table name them.
HOURLY_VARIABLES: tuple[str, ...] = (
    "wind_speed_10m",
    "wind_speed_100m",
    "wind_direction_10m",
    "wind_direction_100m",
    "wind_gusts_10m",
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "surface_pressure",
)

#: Locations per request; keeps the URL short and well within the API's per-call limits.
_LOCATIONS_PER_REQUEST = 50


def _parse_location(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Turn one location's `hourly` block into a list of records, one per hour.

    :param payload: One location's response object, with `hourly.time` in Unix seconds.

    :returns records: Dicts with `forecast_time` (aware UTC datetime) and one key per variable.
    """
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    records: list[dict[str, Any]] = []
    for i, ts in enumerate(times):
        record: dict[str, Any] = {"forecast_time": datetime.fromtimestamp(ts, tz=timezone.utc)}
        for name in HOURLY_VARIABLES:
            values = hourly.get(name) or []
            record[name] = values[i] if i < len(values) else None
        records.append(record)
    return records


async def fetch_hourly_forecasts(
    http: httpx.AsyncClient,
    locations: list[tuple[float, float]],
    forecast_days: int,
) -> list[list[dict[str, Any]]]:
    """
    Fetch the hourly forecast for each location.

    :param http: Shared asynchronous HTTP client.
    :param locations: `(latitude, longitude)` pairs.
    :param forecast_days: Days of forecast, starting today (UTC).

    :returns forecasts: One list of hourly records per location, in the order given.
    :raises httpx.HTTPError: When a request fails or Open-Meteo answers with an error status.
    :raises ValueError: When the answer does not hold one forecast per location asked for.
    """
    forecasts: list[list[dict[str, Any]]] = []
    for chunk in batched(locations, _LOCATIONS_PER_REQUEST):
        resp = await http.get(
            config.open_meteo_url(),
            params={
                "latitude": ",".join(f"{lat:.5f}" for lat, _ in chunk),
                "longitude": ",".join(f"{lon:.5f}" for _, lon in chunk),
                "hourly": ",".join(HOURLY_VARIABLES),
                "forecast_days": forecast_days,
                "wind_speed_unit": "ms",
                "timezone": "GMT",
                "timeformat": "unixtime",
            },
        )
        resp.raise_for_status()
        body = resp.json()
        # One location answers with an object, several with a list of objects.
        payloads = body if isinstance(body, list) else [body]
        if len(payloads) != len(chunk):
            raise ValueError(
                f"Open-Meteo returned {len(payloads)} forecasts for {len(chunk)} locations"
            )
        forecasts.extend(_parse_location(p) for p in payloads)
    return forecasts


__all__ = ["HOURLY_VARIABLES", "fetch_hourly_forecasts"]
