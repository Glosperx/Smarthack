"""
Unit tests for the wind resource data source downloads.
"""

import json
from pathlib import Path

import httpx
import respx

from smarthack.clients import resource_sources
from smarthack.resource.constants import NASA_POWER_REGIONAL_URL

TILE_URL = (
    "https://copernicus-dem-90m.s3.amazonaws.com/Copernicus_DSM_COG_30_N45_00_E024_00_DEM/"
    "Copernicus_DSM_COG_30_N45_00_E024_00_DEM.tif"
)


def test_dem_tile_name_pads_and_signs() -> None:
    """South-west corner degrees become the Copernicus tile name parts."""
    assert resource_sources.dem_tile_name(45, 24) == ("N45", "E024")
    assert resource_sources.dem_tile_name(-3, -7) == ("S03", "W007")


@respx.mock
def test_download_file_writes_once_and_then_reads_the_cache(tmp_path: Path) -> None:
    """A second call does not hit the network."""
    route = respx.get(TILE_URL).respond(200, content=b"tiff-bytes")
    first = resource_sources.fetch_dem_tile(tmp_path, 45, 24)
    second = resource_sources.fetch_dem_tile(tmp_path, 45, 24)
    assert first == second and first is not None
    assert first.read_bytes() == b"tiff-bytes"
    assert route.call_count == 1
    assert not list(tmp_path.rglob("*.part"))


@respx.mock
def test_missing_tile_is_none_not_an_error(tmp_path: Path) -> None:
    """An all-sea tile does not exist on the bucket (403)."""
    respx.get(TILE_URL).respond(403)
    assert resource_sources.fetch_dem_tile(tmp_path, 45, 24) is None
    assert not list(tmp_path.rglob("*.tif"))


@respx.mock
def test_download_failure_raises_and_leaves_no_partial_file(tmp_path: Path) -> None:
    """A server error is raised, not cached."""
    respx.get(TILE_URL).respond(500)
    try:
        resource_sources.fetch_dem_tile(tmp_path, 45, 24)
    except httpx.HTTPStatusError:
        pass
    else:
        raise AssertionError("expected an HTTP error")
    assert not list(tmp_path.rglob("*.tif*"))


@respx.mock
def test_fetch_nasa_power_caches_the_response(tmp_path: Path) -> None:
    """The regional query runs once; the JSON is cached under a name with the years."""
    body: dict[str, list[object]] = {"features": []}
    route = respx.get(NASA_POWER_REGIONAL_URL).respond(200, json=body)
    bbox = (20.0, 43.5, 30.0, 48.5)
    assert resource_sources.fetch_nasa_power(tmp_path, 1981, 2025, bbox) == body
    assert resource_sources.fetch_nasa_power(tmp_path, 1981, 2025, bbox) == body
    assert route.call_count == 1
    params = route.calls[0].request.url.params
    assert params["parameters"] == "WS50M" and params["end"] == "2025"
    assert json.loads((tmp_path / "nasa_power_WS50M_1981_2025.json").read_text()) == body


@respx.mock
def test_reverse_geocode_names_place_and_county() -> None:
    """Village and county are joined; the client identifies itself."""
    route = respx.get("https://nominatim.openstreetmap.org/reverse").respond(
        200, json={"address": {"village": "Topolog", "county": "Tulcea"}}
    )
    assert resource_sources.reverse_geocode(44.9, 28.3) == "Topolog, Tulcea"
    assert "smarthack" in route.calls[0].request.headers["User-Agent"]


@respx.mock
def test_reverse_geocode_failure_is_none() -> None:
    """A failed lookup leaves the site unnamed instead of failing the build."""
    respx.get("https://nominatim.openstreetmap.org/reverse").respond(429)
    assert resource_sources.reverse_geocode(44.9, 28.3) is None
