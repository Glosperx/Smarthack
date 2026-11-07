"""
# Integration tests for /api/parks endpoints

Verifies park querying, turbine diagnostics, schema filtering, error handling, and caching.
"""

from collections.abc import Iterator
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import pytest
import respx

from smarthack.api.app import create_app
from smarthack.api.dependencies import get_today
from smarthack.services.parks_service import clear_cache

pytestmark = pytest.mark.integration

PARKS_URL = "https://test-project.supabase.co/rest/v1/park_map?select=id,name,latitude,longitude&order=id.asc&limit=1000"


@pytest.fixture(autouse=True)
def _reset_parks_cache(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Ensure a clean cache and valid configuration for each test."""
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "test-api-key")
    monkeypatch.setenv("SMARTHACK_TIMEZONE", "UTC")
    clear_cache()
    yield
    clear_cache()


@respx.mock
def test_get_parks_success() -> None:
    """Test that valid park records with name and coordinates are returned."""
    mock_data = [
        {"id": 1, "name": "Alpha Ridge", "latitude": 44.4323, "longitude": 26.1063},
        {"id": 2, "name": "Beta Plains", "latitude": 45.9432, "longitude": 24.9668},
    ]
    respx.get(PARKS_URL).respond(status_code=200, json=mock_data)

    with TestClient(create_app()) as client:
        response = client.get("/api/parks")

    assert response.status_code == 200
    parks = response.json()
    assert len(parks) == 2
    assert parks[0] == {"id": 1, "name": "Alpha Ridge", "latitude": 44.4323, "longitude": 26.1063}
    assert parks[1] == {"id": 2, "name": "Beta Plains", "latitude": 45.9432, "longitude": 24.9668}


@respx.mock
def test_get_parks_skips_invalid_rows() -> None:
    """Test that malformed or out-of-range rows are skipped without failing."""
    mock_data = [
        {"id": 1, "name": "Alpha Ridge", "latitude": 44.4323, "longitude": 26.1063},
        {"id": 2, "name": "Invalid Lat", "latitude": 999.0, "longitude": 24.9668},
        {"id": 3, "name": "Missing Longitude", "latitude": 45.0},
        {"name": "Missing ID", "latitude": 46.0, "longitude": 25.0},
        {"id": 4, "name": "Gamma Valley", "latitude": 46.7712, "longitude": 23.6236},
    ]
    respx.get(PARKS_URL).respond(status_code=200, json=mock_data)

    with TestClient(create_app()) as client:
        response = client.get("/api/parks")

    assert response.status_code == 200
    parks = response.json()
    assert len(parks) == 2
    assert [p["id"] for p in parks] == [1, 4]


@respx.mock
def test_get_parks_upstream_error_maps_to_502() -> None:
    """Test that upstream Supabase HTTP failure maps to 502 Bad Gateway."""
    respx.get(PARKS_URL).respond(status_code=500)

    with TestClient(create_app()) as client:
        response = client.get("/api/parks")

    assert response.status_code == 502
    assert response.json()["detail"] == "Could not load parks"


@respx.mock
def test_get_park_turbines_with_predictions_and_sorting() -> None:
    """
    Test that turbines are retrieved for today and sorted with highest probability first.

    Turbines without predictions are placed last.
    When multiple predictions exist for a turbine on the same day, the newest entry is used.
    """
    test_day = date(2026, 11, 7)
    route = respx.get(
        "https://test-project.supabase.co/rest/v1/turbine",
        params__contains={
            "park_id": "eq.1",
            "turbine_mentenance.predicted_date": "eq.2026-11-07",
            "turbine_mentenance.order": "entry_id.desc",
            "order": "id.asc",
            "limit": "1000",
        },
    ).respond(
        status_code=200,
        json=[
            {
                "id": 101,
                "turbine_mentenance": [
                    {
                        "entry_id": 10,
                        "predicted_date": "2026-11-07",
                        "daily_fault_probability": 0.15,
                        "cumulative_fault_probability": 0.25,
                        "status": "warning",
                        "suspected_subsystem": "Gearbox Bearing",
                    }
                ],
            },
            {
                "id": 102,
                "turbine_mentenance": [
                    {
                        "entry_id": 12,  # newest entry wins
                        "predicted_date": "2026-11-07",
                        "daily_fault_probability": 0.85,
                        "cumulative_fault_probability": 0.90,
                        "status": "critical",
                        "suspected_subsystem": "Generator Bearing",
                    },
                    {
                        "entry_id": 11,
                        "predicted_date": "2026-11-07",
                        "daily_fault_probability": 0.40,
                        "cumulative_fault_probability": 0.50,
                        "status": "warning",
                        "suspected_subsystem": "Generator Bearing",
                    },
                ],
            },
            {
                "id": 103,
                "turbine_mentenance": [],  # no prediction for today
            },
        ],
    )

    app = create_app()
    app.dependency_overrides[get_today] = lambda: test_day

    with TestClient(app) as client:
        response = client.get("/api/parks/1/turbines")

    assert response.status_code == 200
    assert route.called
    data = response.json()
    assert data["park_id"] == 1
    assert data["date"] == "2026-11-07"
    turbines = data["turbines"]
    assert len(turbines) == 3

    # Sorting: 102 (0.85) -> 101 (0.15) -> 103 (no prediction)
    assert turbines[0]["id"] == 102
    assert turbines[0]["prediction"]["daily_fault_probability"] == 0.85
    assert turbines[0]["prediction"]["entry_id"] == 12

    assert turbines[1]["id"] == 101
    assert turbines[1]["prediction"]["daily_fault_probability"] == 0.15

    assert turbines[2]["id"] == 103
    assert turbines[2]["prediction"] is None


@respx.mock
def test_get_park_turbines_empty_park() -> None:
    """Test that a park with zero turbines returns an empty list."""
    respx.get(
        "https://test-project.supabase.co/rest/v1/turbine",
        params__contains={"park_id": "eq.99"},
    ).respond(status_code=200, json=[])

    app = create_app()
    app.dependency_overrides[get_today] = lambda: date(2026, 11, 7)

    with TestClient(app) as client:
        response = client.get("/api/parks/99/turbines")

    assert response.status_code == 200
    data = response.json()
    assert data["park_id"] == 99
    assert data["turbines"] == []


@respx.mock
def test_get_park_turbines_upstream_error_maps_to_502() -> None:
    """Test that upstream Supabase HTTP failure maps to 502 Bad Gateway."""
    respx.get(
        "https://test-project.supabase.co/rest/v1/turbine",
        params__contains={"park_id": "eq.1"},
    ).respond(status_code=502)

    app = create_app()
    app.dependency_overrides[get_today] = lambda: date(2026, 11, 7)

    with TestClient(app) as client:
        response = client.get("/api/parks/1/turbines")

    assert response.status_code == 502
    assert response.json()["detail"] == "Could not load turbines"


def test_get_today_timezone_shift(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Test that get_today respects the configured timezone across midnight UTC.

    When UTC is 23:30 on 2026-11-07, Europe/Bucharest (UTC+2) is 01:30 on 2026-11-08.
    """
    fixed_instant = datetime(2026, 11, 7, 23, 30, 0, tzinfo=ZoneInfo("UTC"))

    monkeypatch.setenv("SMARTHACK_TIMEZONE", "Europe/Bucharest")
    with patch("smarthack.api.dependencies.datetime") as mock_datetime:
        mock_datetime.now.side_effect = lambda tz=None: (
            fixed_instant.astimezone(tz) if tz else fixed_instant
        )
        computed_date = get_today()

    assert computed_date == date(2026, 11, 8)
