"""
Unit tests for the wind resource atlas API routes, on a small fake atlas.
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient
import numpy as np
import pytest

from smarthack.api.app import create_app
from smarthack.resource.grid import AnalysisGrid
from smarthack.schemas.resource import (
    ResourceBounds,
    ResourceLegend,
    ResourceSite,
    ResourceSummary,
)
from smarthack.services import resource_service
from tests.conftest import skip_module_without_extra

skip_module_without_extra("resource")

#: A 4 x 2 grid of 0.5 degree cells over 24-26 E, 45-46 N.
GRID = AnalysisGrid.from_bounds(24.0, 26.0, 45.0, 46.0, 0.5)


def write_fake_atlas(directory: Path) -> None:
    """Write the four atlas files for `GRID`: one hill cell, one mountain, one outside."""
    summary = ResourceSummary(
        target_years=[2027, 2028],
        data_until=2025,
        reference_years=[2008, 2017],
        bounds=ResourceBounds(south=45.0, west=24.0, north=46.0, east=26.0),
        elevation_band_m=[200.0, 800.0],
        max_slope_deg=10.0,
        legend=ResourceLegend(vmin=4.0, vmax=8.0, colors=["#cde2fb", "#0d366b"]),
        selected_estimator="climatology_10y",
        backtest=[],
        validation_years=[2004, 2015],
        test_years=[2016, 2025],
        band_low_pct=-0.04,
        band_high_pct=0.03,
        band_coverage_test=0.78,
        rank_correlation_test=0.99,
        hill_area_km2=100.0,
        buildable_area_km2=50.0,
        hill_wind_p50_mean=6.0,
        sources=[],
        generated_at="2026-11-07T00:00:00+00:00",
    )
    (directory / "summary.json").write_text(summary.model_dump_json(), encoding="utf-8")
    site = ResourceSite(
        rank=1,
        name="Somewhere, County",
        latitude=45.75,
        longitude=24.25,
        wind_p50=7.0,
        wind_p10=6.7,
        wind_p90=7.2,
        reference_wind=6.9,
        change_pct=0.014,
        elevation_m=500.0,
        slope_deg=4.0,
        buildable_fraction=0.9,
        percentile=95.0,
        explanation="Windy ridge.",
    )
    (directory / "sites.json").write_text(json.dumps([site.model_dump()]), encoding="utf-8")
    (directory / "heatmap.png").write_bytes(b"\x89PNG fake")
    nan = np.nan
    np.savez(
        directory / "atlas_grid.npz",
        p50=np.array([[7.0, 9.0, nan, nan], [nan, nan, nan, nan]], dtype=np.float16),
        reference=np.array([[6.9, 8.8, nan, nan], [nan] * 4], dtype=np.float16),
        elevation=np.array([[500.0, 1500.0, nan, nan], [nan] * 4], dtype=np.float16),
        slope=np.array([[4.0, 20.0, nan, nan], [nan] * 4], dtype=np.float16),
        hill_quantiles=np.linspace(4.0, 8.0, 101).astype(np.float32),
    )


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """An app serving the fake atlas from a temporary directory."""
    write_fake_atlas(tmp_path)
    monkeypatch.setenv("RESOURCE_ATLAS_DIR", str(tmp_path))
    monkeypatch.setattr(resource_service, "_grid", lambda: GRID)
    resource_service._cache.clear()
    return TestClient(create_app())


def test_summary_and_sites(client: TestClient) -> None:
    """The summary and sites are served as written."""
    summary = client.get("/api/resource/summary")
    assert summary.status_code == 200
    assert summary.json()["target_years"] == [2027, 2028]
    sites = client.get("/api/resource/sites").json()
    assert sites[0]["name"] == "Somewhere, County"


def test_heatmap_is_a_png_response(client: TestClient) -> None:
    """The overlay is returned with the image media type."""
    resp = client.get("/api/resource/heatmap.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"


def test_point_on_buildable_hill(client: TestClient) -> None:
    """A hill cell gets the forecast, its band and a percentile."""
    point = client.get("/api/resource/point", params={"lat": 45.8, "lon": 24.2}).json()
    assert point["inside_country"] and point["in_band"] and point["buildable"]
    assert point["wind_p50"] == pytest.approx(7.0)
    assert point["wind_p10"] == pytest.approx(7.0 * 0.96, abs=0.01)
    assert point["percentile"] == pytest.approx(75.0)
    assert "7.0 m/s" in point["explanation"]


def test_point_on_a_mountain_is_outside_the_band(client: TestClient) -> None:
    """A 1500 m cell is described but not part of the hill band."""
    point = client.get("/api/resource/point", params={"lat": 45.8, "lon": 24.7}).json()
    assert point["inside_country"] and not point["in_band"] and not point["buildable"]
    assert "outside" in point["explanation"]


def test_point_outside_the_country(client: TestClient) -> None:
    """A cell without data, and a point off the grid, are both outside."""
    for params in ({"lat": 45.2, "lon": 25.7}, {"lat": 10.0, "lon": 10.0}):
        point = client.get("/api/resource/point", params=params).json()
        assert point["inside_country"] is False


def test_point_validates_coordinates(client: TestClient) -> None:
    """Latitude beyond 90 is rejected before the service runs."""
    assert client.get("/api/resource/point", params={"lat": 95, "lon": 24}).status_code == 422


def test_every_endpoint_is_503_before_the_atlas_is_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing files say how to build them instead of failing with a 500."""
    monkeypatch.setenv("RESOURCE_ATLAS_DIR", str(tmp_path / "empty"))
    resource_service._cache.clear()
    with TestClient(create_app()) as client:
        for path in ("summary", "sites", "heatmap.png", "point?lat=45&lon=25"):
            resp = client.get(f"/api/resource/{path}")
            assert resp.status_code == 503
            assert "make resource" in resp.json()["detail"]
