"""
# Unit tests for the Supabase-backed agent tools

Rows from the database are mocked at the client boundary; no network is used.
"""

from datetime import date, timedelta
from typing import Any

import pytest

from smarthack.services.agent import db_tools, tools


def _row(turbine_id: int, days: int, status: str, sub: str, cum: float) -> dict[str, Any]:
    """Build one `upward_turbine_mentenance` row."""
    return {
        "entry_id": 1,
        "predicted_date": (date.today() + timedelta(days=days)).isoformat(),
        "daily_fault_probability": 0.1,
        "cumulative_fault_probability": cum,
        "status": status,
        "suspected_subsystem": sub,
        "turbine_id": turbine_id,
        "park_id": 3,
        "park_name": "P",
    }


def test_turbines_aggregated_per_turbine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Worst status wins per turbine; WATCH-only turbines are not repair candidates."""
    rows = [
        _row(1, 5, "WATCH", "gearbox", 0.3),
        _row(1, 2, "CRITICAL", "bearing", 0.9),
        _row(2, 3, "WATCH", "oil", 0.2),
    ]
    monkeypatch.setattr(db_tools, "select_rows", lambda rel, params=None: rows)

    result = db_tools.db_get_turbines_needing_attention("3")

    assert [r["turbine_id"] for r in result] == [1]
    assert result[0]["health_status"] == "CRITICAL"
    assert result[0]["days_to_failure"] == 2.0
    assert result[0]["suspected_failure"] == "bearing"
    assert result[0]["fault_probability"] == 0.9


def test_crews_map_employees(monkeypatch: pytest.MonkeyPatch) -> None:
    """Employees become crew dicts keyed by stringified id."""
    emp = [
        {
            "id": 7,
            "full_nama": "Ana",
            "phone_number": "+40",
            "email": "a@x.ro",
            "is_manager": True,
            "park_id": 3,
        }
    ]
    monkeypatch.setattr(db_tools, "select_rows", lambda rel, params=None: emp)

    crews = db_tools.db_get_available_crews("3")

    assert crews[0]["crew_id"] == "7"
    assert crews[0]["crew_name"] == "Ana"
    assert crews[0]["contact_email"] == "a@x.ro"


def test_turbine_location_parses_geojson(monkeypatch: pytest.MonkeyPatch) -> None:
    """The park's GeoJSON point yields (lat, lon)."""

    def fake(rel: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
        """Return a turbine, then its park."""
        if rel == "turbine":
            return [{"id": 1, "park_id": 3}]
        return [{"id": 3, "location": {"type": "Point", "coordinates": [26.1, 44.4]}}]

    monkeypatch.setattr(db_tools, "select_rows", fake)

    loc = db_tools.db_get_turbine_location(1)

    assert loc is not None
    assert (loc["latitude"], loc["longitude"]) == (44.4, 26.1)


def test_tools_use_database_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """`AGENT_DATA_SOURCE=supabase` routes the tools to the database module."""
    monkeypatch.setenv("AGENT_DATA_SOURCE", "supabase")
    monkeypatch.setattr(db_tools, "db_get_available_crews", lambda park_id: [{"crew_id": "9"}])

    assert tools.get_available_crews_tool("3") == [{"crew_id": "9"}]
