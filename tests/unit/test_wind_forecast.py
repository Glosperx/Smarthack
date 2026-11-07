"""Unit tests for the park wind forecast client, service and job."""

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from smarthack.clients.open_meteo import HOURLY_VARIABLES, fetch_hourly_forecasts
from smarthack.jobs.wind_forecast_job import run_once
from smarthack.schemas.wind_forecast import ForecastRunSummary
from smarthack.services.wind_forecast_service import build_rows, run_forecast_cycle
from smarthack.utils.dates import seconds_until_next_run

#: 2026-11-07T00:00:00Z in Unix seconds.
T0 = 1_794_009_600

_SERVICE = "smarthack.services.wind_forecast_service"


def _location(hours: int = 2) -> dict[str, Any]:
    """Build one location's Open-Meteo answer with `hours` hourly values."""
    hourly: dict[str, Any] = {"time": [T0 + 3600 * i for i in range(hours)]}
    for name in HOURLY_VARIABLES:
        hourly[name] = [float(i) for i in range(hours)]
    return {"hourly": hourly}


def _client(body: Any) -> httpx.AsyncClient:
    """Async client answering every request with `body` as JSON."""
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))
    )


def test_fetch_parses_several_locations() -> None:
    """A list answer yields one record list per location, times as aware UTC datetimes."""

    async def go() -> list[list[dict[str, Any]]]:
        async with _client([_location(), _location(3)]) as http:
            return await fetch_hourly_forecasts(http, [(45.0, 28.0), (44.0, 27.0)], 7)

    forecasts = asyncio.run(go())
    assert [len(f) for f in forecasts] == [2, 3]
    assert forecasts[0][1]["forecast_time"] == datetime(2026, 11, 7, 1, tzinfo=timezone.utc)
    assert forecasts[1][2]["wind_speed_100m"] == 2.0


def test_fetch_accepts_single_object_answer() -> None:
    """One location answers with a plain object, not a list."""

    async def go() -> list[list[dict[str, Any]]]:
        async with _client(_location()) as http:
            return await fetch_hourly_forecasts(http, [(45.0, 28.0)], 7)

    assert len(asyncio.run(go())) == 1


def test_fetch_rejects_count_mismatch() -> None:
    """Fewer forecasts than locations is an error, never a silent shift of parks."""

    async def go() -> None:
        async with _client([_location()]) as http:
            await fetch_hourly_forecasts(http, [(45.0, 28.0), (44.0, 27.0)], 7)

    with pytest.raises(ValueError):
        asyncio.run(go())


def test_build_rows_drops_non_finite() -> None:
    """NaN values become None so the row serialises to valid JSON."""
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)
    rows = build_rows(1, [{"forecast_time": now, "wind_speed_100m": float("nan")}], now)
    assert rows[0].wind_speed_100m is None
    assert rows[0].park_id == 1


def _run_cycle(
    parks: list[dict[str, Any]],
    forecasts: list[list[dict[str, Any]]],
    dry_run: bool = False,
) -> tuple[ForecastRunSummary, AsyncMock]:
    """Run the service with its clients patched; returns the summary and the replace mock."""
    replace = AsyncMock(return_value=sum(len(f) for f in forecasts))
    with (
        patch(f"{_SERVICE}.supabase.fetch_parks", AsyncMock(return_value=parks)),
        patch(f"{_SERVICE}.open_meteo.fetch_hourly_forecasts", AsyncMock(return_value=forecasts)),
        patch(f"{_SERVICE}.supabase.replace_wind_forecast", replace),
    ):
        summary = asyncio.run(run_forecast_cycle(httpx.AsyncClient(), dry_run=dry_run))
    return summary, replace


def test_cycle_replaces_table_with_every_park() -> None:
    """Parks without coordinates are skipped; the rest are written in one replace call."""
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)
    parks: list[dict[str, Any]] = [
        {"id": 1, "latitude": 45.0, "longitude": 28.0},
        {"id": 2, "latitude": None, "longitude": None},
        {"id": 3, "latitude": 44.0, "longitude": 27.0},
    ]
    recs = [{"forecast_time": now}]
    summary, replace = _run_cycle(parks, [recs, recs])
    assert (summary.parks, summary.rows, summary.written) == (2, 2, 2)
    assert replace.await_args is not None
    assert [r["park_id"] for r in replace.await_args.args[1]] == [1, 3]


def test_cycle_dry_run_writes_nothing() -> None:
    """A dry run fetches but never calls the replace function."""
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)
    parks = [{"id": 1, "latitude": 1.0, "longitude": 2.0}]
    summary, replace = _run_cycle(parks, [[{"forecast_time": now}]], dry_run=True)
    assert summary.rows == 1 and summary.written == 0
    replace.assert_not_awaited()


def test_cycle_keeps_previous_forecast_when_empty() -> None:
    """Parks exist but no hours came back: raise instead of wiping the table."""
    with pytest.raises(ValueError):
        _run_cycle([{"id": 1, "latitude": 1.0, "longitude": 2.0}], [[]])


def test_run_once_exit_codes() -> None:
    """Success exits 0; a failed refresh exits 1."""
    target = "smarthack.jobs.wind_forecast_job.run_forecast_cycle"
    ok = ForecastRunSummary(parks=1, rows=168, written=168)
    with patch(target, AsyncMock(return_value=ok)):
        assert asyncio.run(run_once()) == 0
    with patch(target, AsyncMock(side_effect=httpx.ConnectError("down"))):
        assert asyncio.run(run_once()) == 1


def test_twice_a_day_schedule() -> None:
    """With 720 minutes and a 5 minute offset, slots fall at 00:05 and 12:05."""
    morning = datetime(2026, 11, 7, 6, 0, tzinfo=timezone.utc)
    assert seconds_until_next_run(morning, 720, 5) == (6 * 60 + 5) * 60.0
    evening = datetime(2026, 11, 7, 20, 0, tzinfo=timezone.utc)
    assert seconds_until_next_run(evening, 720, 5) == (4 * 60 + 5) * 60.0
