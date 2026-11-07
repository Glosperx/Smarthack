"""
# Wind forecast service

Refreshes `public.park_wind_forecast`: reads every park's coordinates, fetches the hourly
7-day forecast from Open-Meteo, and replaces the whole table with it.

All or nothing: the table is replaced only when every park's forecast arrived. When
Open-Meteo fails, the previous forecast stays in place, a few hours older, rather than
being replaced by a partial one that would silently drop parks.

The following can be imported from this module:
- `build_rows`
- `run_forecast_cycle`
"""

from datetime import datetime, timezone
import logging
import time
from typing import Any

import httpx

from smarthack.clients import open_meteo, supabase
from smarthack.constants import WIND_FORECAST_DAYS
from smarthack.schemas.wind_forecast import ForecastRunSummary, WindForecastRow

logger = logging.getLogger(__name__)


def build_rows(
    park_id: int, records: list[dict[str, Any]], fetched_at: datetime
) -> list[WindForecastRow]:
    """
    Validate one park's hourly records into table rows.

    :param park_id: Wind park identifier.
    :param records: Hourly records from `open_meteo.fetch_hourly_forecasts`.
    :param fetched_at: Instant of the refresh, written on every row.

    :returns rows: One validated row per forecast hour.
    """
    return [WindForecastRow(park_id=park_id, fetched_at=fetched_at, **r) for r in records]


async def run_forecast_cycle(
    http: httpx.AsyncClient, *, dry_run: bool = False
) -> ForecastRunSummary:
    """
    Fetch the forecast for every park and replace the table's contents with it.

    :param http: Shared asynchronous HTTP client.
    :param dry_run: If True, fetches and validates but writes nothing.

    :returns summary: Parks asked for, rows built and rows written.
    :raises httpx.HTTPError: When Supabase or Open-Meteo fails; the table is then untouched.
    :raises ValueError: When parks exist but no forecast row could be built.
    """
    started = time.monotonic()
    summary = ForecastRunSummary()

    parks = [
        p
        for p in await supabase.fetch_parks(http)
        if p.get("latitude") is not None and p.get("longitude") is not None
    ]
    summary.parks = len(parks)

    rows: list[WindForecastRow] = []
    if parks:
        forecasts = await open_meteo.fetch_hourly_forecasts(
            http,
            [(float(p["latitude"]), float(p["longitude"])) for p in parks],
            WIND_FORECAST_DAYS,
        )
        fetched_at = datetime.now(timezone.utc)
        for park, records in zip(parks, forecasts, strict=True):
            rows.extend(build_rows(int(park["id"]), records, fetched_at))
        if not rows:
            raise ValueError("Open-Meteo returned no forecast hours; keeping the previous forecast")
    summary.rows = len(rows)

    if not dry_run:
        summary.written = await supabase.replace_wind_forecast(
            http, [r.model_dump(mode="json") for r in rows]
        )

    summary.duration_s = round(time.monotonic() - started, 3)
    return summary


__all__ = ["build_rows", "run_forecast_cycle"]
