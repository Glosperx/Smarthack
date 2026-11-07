"""
# Unit tests for dispatch API routes

Validates endpoints for daily sweeps, crew querying, simulation, and notification logs.
"""

from fastapi.testclient import TestClient

from smarthack.api.app import create_app
from smarthack.clients.crew_client import get_default_crew_client


def test_api_list_crews() -> None:
    """Test GET /api/dispatch/crews endpoint."""
    with TestClient(create_app()) as client:
        resp = client.get("/api/dispatch/crews")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 3

        resp_filtered = client.get("/api/dispatch/crews?park_id=wind_farm_a")
        assert resp_filtered.status_code == 200
        assert len(resp_filtered.json()) == 2


def test_api_daily_sweep() -> None:
    """Test POST /api/dispatch/daily-sweep endpoint."""
    crew_client = get_default_crew_client()
    crew_client.reset_crews()

    with TestClient(create_app()) as client:
        resp = client.post("/api/dispatch/daily-sweep?park_id=wind_farm_a")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_turbines_scanned"] == 3
        assert "wind_farm_a" in data["park_results"]


def test_api_simulate_scenario() -> None:
    """Test POST /api/dispatch/simulate endpoint."""
    with TestClient(create_app()) as client:
        payload = {
            "park_id": "wind_farm_a",
            "scenarios": {0: "bearing_overheating", 1: "hydraulic_leak"},
            "active_crew_count": 1,
        }
        resp = client.post("/api/dispatch/simulate", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["park_id"] == "wind_farm_a"
        assert data["conflict_detected"] is True
        assert data["power_model_invoked"] is True
        assert len(data["decisions"]) == 2


def test_api_notifications_log() -> None:
    """Test GET /api/dispatch/notifications/voice and /email."""
    with TestClient(create_app()) as client:
        v_resp = client.get("/api/dispatch/notifications/voice")
        assert v_resp.status_code == 200
        assert isinstance(v_resp.json(), list)

        e_resp = client.get("/api/dispatch/notifications/email")
        assert e_resp.status_code == 200
        assert isinstance(e_resp.json(), list)
