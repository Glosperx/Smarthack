"""
# Unit tests for repair scheduling inside the dispatch agent

Covers the `schedule_repairs` node of the graph and the daily wind read that feeds it.
"""

from datetime import date, timedelta
from typing import Any

import httpx
import pytest

from smarthack import config
from smarthack.clients.crew_client import get_default_crew_client
from smarthack.clients.email_client import get_default_email_client
from smarthack.clients.voice_client import get_default_voice_client
from smarthack.services.agent import db_tools, tools
from smarthack.services.agent.graph import run_park_dispatch_agent
from smarthack.utils.dates import today_in_tz

WIND = [8.0, 3.0, 9.0, 5.0, 2.0, 7.0, 6.0]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run without an LLM key, with every crew available and a known wind forecast."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(
        "smarthack.services.agent.graph.get_daily_wind_forecast", lambda park_id, days: list(WIND)
    )
    get_default_crew_client().reset_crews()


def _turbine(turbine_id: int, days_to_failure: float) -> dict[str, Any]:
    """
    Build a triage item that needs repair.

    :param turbine_id: Turbine identifier.
    :param days_to_failure: Predicted days until failure.

    :returns item: Triage dictionary as the maintenance model produces it.
    """
    return {
        "turbine_id": turbine_id,
        "park_id": "wind_farm_a",
        "health_status": "WARNING",
        "fault_probability": 0.5,
        "days_to_failure": days_to_failure,
        "suspected_failure": "Gearbox Wear",
        "recommended_action": "Inspect.",
        "needs_repair": True,
    }


def test_two_turbines_get_different_calm_days() -> None:
    """Both turbines are repaired before failure, on the two calmest allowed days."""
    result = run_park_dispatch_agent(
        "wind_farm_a", triage_items=[_turbine(0, 4.0), _turbine(1, 4.0)]
    )

    today = today_in_tz(config.timezone())
    dates = {d["repair_date"] for d in result["alert_decisions"]}
    assert dates == {
        (today + timedelta(days=1)).isoformat(),
        (today + timedelta(days=3)).isoformat(),
    }
    assert all("Repair planned for" in d["decision_reason"] for d in result["alert_decisions"])


def test_email_and_voice_texts_carry_the_repair_day() -> None:
    """The crew is told the day in the message it receives, not only in the audit trail."""
    email_client = get_default_email_client()
    email_client.clear_history()
    voice_client = get_default_voice_client()
    voice_client.clear_history()
    today = today_in_tz(config.timezone())

    warning = {**_turbine(0, 4.0), "health_status": "WARNING", "fault_probability": 0.5}
    run_park_dispatch_agent("wind_farm_a", triage_items=[warning])
    critical = {**_turbine(1, 0.8), "health_status": "CRITICAL", "fault_probability": 0.95}
    run_park_dispatch_agent("wind_farm_a", triage_items=[critical])

    assert (today + timedelta(days=1)).isoformat() in email_client.get_email_history()[0]["body"]
    assert today.isoformat() in voice_client.get_call_history()[0]["synthesized_speech"]


def test_wind_forecast_failure_does_not_break_the_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the forecast cannot be read, the schedule falls back to an empty forecast."""

    def broken(park_id: str, days: int, today: date) -> list[float | None]:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(tools, "_use_database", lambda: True)
    monkeypatch.setattr(db_tools, "db_get_daily_wind", broken)

    assert tools.get_daily_wind_forecast("1") == []


def test_no_day_left_is_reported() -> None:
    """Two turbines due today and one crew: one is scheduled, the other is flagged."""
    result = run_park_dispatch_agent(
        "wind_farm_a", triage_items=[_turbine(0, 0.5), _turbine(1, 0.5)]
    )

    decisions = result["alert_decisions"]
    scheduled = [d for d in decisions if d["repair_date"] is not None]
    left_out = [d for d in decisions if d["repair_date"] is None]
    assert len(scheduled) == 1
    assert len(left_out) == 1
    assert scheduled[0]["repair_date"] == today_in_tz(config.timezone()).isoformat()
    assert "No repair day is left" in left_out[0]["decision_reason"]


def test_schedule_is_in_state() -> None:
    """The graph keeps the schedule keyed by turbine id."""
    result = run_park_dispatch_agent("wind_farm_a", triage_items=[_turbine(0, 4.0)])

    assert set(result["repair_schedule"]) == {0}
    assert result["repair_schedule"][0]["day"] == 1
    assert result["repair_schedule"][0]["wind_speed"] == 3.0


def test_nothing_to_repair_schedules_nothing() -> None:
    """A park with no failing turbine gets an empty schedule."""
    healthy = {**_turbine(0, 7.0), "needs_repair": False}
    result = run_park_dispatch_agent("wind_farm_a", triage_items=[healthy])

    assert result["repair_schedule"] == {}
    assert result["alert_decisions"] == []


def test_daily_wind_is_the_mean_of_hourly_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hourly 100 m speeds are averaged per local day; days without rows are None."""
    rows = [
        {"forecast_time": "2026-11-08T00:00:00+00:00", "wind_speed_100m": 4.0},
        {"forecast_time": "2026-11-08T12:00:00+00:00", "wind_speed_100m": 8.0},
        {"forecast_time": "2026-11-08T13:00:00+00:00", "wind_speed_100m": None},
        {"forecast_time": "2026-11-10T06:00:00+00:00", "wind_speed_100m": 5.0},
        {"forecast_time": "2026-11-20T06:00:00+00:00", "wind_speed_100m": 99.0},
    ]
    monkeypatch.setattr(db_tools, "select_rows", lambda relation, params=None: rows)
    monkeypatch.setattr(config, "timezone", lambda: "UTC")

    assert db_tools.db_get_daily_wind("1", 4, date(2026, 11, 8)) == [6.0, None, 5.0, None]
