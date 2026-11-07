"""
# Integration tests for FastAPI endpoints

Smoke tests exercising API routes through Starlette's TestClient.
"""

from fastapi.testclient import TestClient
import pytest
import respx

from smarthack import config
from smarthack.api.app import create_app

pytestmark = pytest.mark.integration


def test_health_endpoint_returns_ok() -> None:
    """Test that GET /api/health returns HTTP 200 with ok status."""
    with TestClient(create_app()) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@respx.mock
def test_example_endpoint_success() -> None:
    """Test that GET /api/example calls upstream service and validates response."""
    upstream_url = f"{config.example_service_url()}/search?q=test"
    respx.get(upstream_url).respond(
        status_code=200, json={"query": "test", "items": ["alpha", "beta"]}
    )

    with TestClient(create_app()) as client:
        response = client.get("/api/example?q=test")

    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "test"
    assert data["items"] == ["alpha", "beta"]


@respx.mock
def test_example_endpoint_upstream_failure() -> None:
    """Test that upstream failure maps to 502 Bad Gateway."""
    upstream_url = f"{config.example_service_url()}/search?q=fail"
    respx.get(upstream_url).respond(status_code=500)

    with TestClient(create_app()) as client:
        response = client.get("/api/example?q=fail")

    assert response.status_code == 502
    assert "Upstream failed" in response.json()["detail"]


def test_nonexistent_api_endpoint_returns_404() -> None:
    """Test that unknown routes return 404."""
    with TestClient(create_app()) as client:
        response = client.get("/api/unknown_route")

    assert response.status_code == 404
