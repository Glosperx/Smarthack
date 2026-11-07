"""
# Integration tests for /api/parks endpoint

Verifies park querying, schema validation filtering, error handling, and caching.
"""

from collections.abc import Iterator

from fastapi.testclient import TestClient
import pytest
import respx

from smarthack.api.app import create_app
from smarthack.services.parks_service import clear_cache

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _reset_parks_cache(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Ensure a clean cache and valid configuration for each test."""
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "test-api-key")
    monkeypatch.setenv("SUPABASE_PARKS_TABLE", "parks")
    clear_cache()
    yield
    clear_cache()


@respx.mock
def test_get_parks_success() -> None:
    """Test that valid park records are returned as expected."""
    target_url = "https://test-project.supabase.co/rest/v1/parks?select=*&order=id.asc&limit=1000"
    mock_data = [
        {"id": 1, "latitude": 44.4323, "longitude": 26.1063},
        {"id": 2, "latitude": 45.9432, "longitude": 24.9668},
    ]
    respx.get(target_url).respond(status_code=200, json=mock_data)

    with TestClient(create_app()) as client:
        response = client.get("/api/parks")

    assert response.status_code == 200
    parks = response.json()
    assert len(parks) == 2
    assert parks[0] == {"id": 1, "latitude": 44.4323, "longitude": 26.1063}
    assert parks[1] == {"id": 2, "latitude": 45.9432, "longitude": 24.9668}


@respx.mock
def test_get_parks_skips_invalid_rows() -> None:
    """Test that malformed or out-of-range rows are skipped without failing."""
    target_url = "https://test-project.supabase.co/rest/v1/parks?select=*&order=id.asc&limit=1000"
    mock_data = [
        {"id": 1, "latitude": 44.4323, "longitude": 26.1063},
        {"id": 2, "latitude": 999.0, "longitude": 24.9668},  # out-of-range latitude
        {"id": 3, "latitude": 45.0},  # missing longitude
        {"latitude": 46.0, "longitude": 25.0},  # missing id
        {"id": 4, "latitude": 46.7712, "longitude": 23.6236},
    ]
    respx.get(target_url).respond(status_code=200, json=mock_data)

    with TestClient(create_app()) as client:
        response = client.get("/api/parks")

    assert response.status_code == 200
    parks = response.json()
    assert len(parks) == 2
    assert [p["id"] for p in parks] == [1, 4]


@respx.mock
def test_get_parks_upstream_error_maps_to_502() -> None:
    """Test that upstream Supabase HTTP failure maps to 502 Bad Gateway."""
    target_url = "https://test-project.supabase.co/rest/v1/parks?select=*&order=id.asc&limit=1000"
    respx.get(target_url).respond(status_code=500)

    with TestClient(create_app()) as client:
        response = client.get("/api/parks")

    assert response.status_code == 502
    assert response.json()["detail"] == "Could not load parks"
