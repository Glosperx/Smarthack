"""
Unit tests for site selection, heatmap rendering and terrain slope.
"""

from io import BytesIO

import numpy as np
import pytest

from smarthack.resource.grid import AnalysisGrid, GeoRaster
from smarthack.resource.render import colorize, hex_to_rgb, render_overlay_png
from smarthack.resource.sites import select_sites
from smarthack.resource.terrain import slope_degrees
from tests.conftest import skip_module_without_extra

skip_module_without_extra("resource")


def site_grid() -> AnalysisGrid:
    """A 1 x 2 degree grid of 0.05 degree cells (about 5 km)."""
    return AnalysisGrid.from_bounds(20.0, 22.0, 45.0, 46.0, 0.05)


def two_hills(grid: AnalysisGrid) -> np.ndarray:
    """A windy area in the west, a slightly calmer one 100 km east, plain elsewhere."""
    wind = np.full((grid.ny, grid.nx), 5.0)
    wind[8:12, 3:7] = 8.0
    wind[8:12, 30:34] = 7.5
    return wind


def test_sites_are_ranked_and_kept_apart() -> None:
    """The best window wins; a second site comes from the other area, not next door."""
    grid = site_grid()
    sites = select_sites(two_hills(grid), grid, (3, 3), 0.6, 20.0, 5)
    assert sites[0].rank == 1
    assert sites[0].window_wind == pytest.approx(8.0)
    assert 20.15 < sites[0].longitude < 20.35
    assert sites[1].window_wind == pytest.approx(7.5)
    for a in sites:
        for b in sites:
            if a is not b:
                assert abs(a.longitude - b.longitude) + abs(a.latitude - b.latitude) > 0.15


def test_sites_need_enough_eligible_terrain() -> None:
    """A lone eligible cell is not a park-sized site."""
    grid = site_grid()
    wind = np.full((grid.ny, grid.nx), np.nan)
    wind[10, 10] = 9.0
    assert select_sites(wind, grid, (3, 3), 0.6, 20.0, 5) == []


def test_colorize_clips_to_the_ramp_ends_and_hides_nan() -> None:
    """Below vmin is the first colour, above vmax the last, NaN is transparent."""
    ramp = ("#000000", "#ffffff")
    rgba = colorize(np.array([[0.0, 5.0, 99.0, np.nan]]), ramp, 0.0, 10.0, 200)
    assert tuple(rgba[0, 0, :3]) == (0, 0, 0)
    assert tuple(rgba[0, 1, :3]) == (128, 128, 128)
    assert tuple(rgba[0, 2, :3]) == (255, 255, 255)
    assert rgba[0, 0, 3] == 200 and rgba[0, 3, 3] == 0


def test_hex_to_rgb() -> None:
    """Hex parsing."""
    assert hex_to_rgb("#256abf") == (0x25, 0x6A, 0xBF)


def test_render_overlay_png_has_the_grid_size() -> None:
    """The overlay is one pixel per grid cell."""
    from PIL import Image

    grid = site_grid()
    png = render_overlay_png(two_hills(grid), grid, ("#cde2fb", "#0d366b"), 5.0, 8.0)
    with Image.open(BytesIO(png)) as img:
        assert img.size == (grid.nx, grid.ny)
        assert img.mode == "RGBA"


def test_slope_of_a_tilted_plane() -> None:
    """A plane rising 100 m per north-south pixel of ~92 m is about 47 degrees."""
    rows = np.arange(10, dtype=np.float32)[:, None]
    dem = GeoRaster(
        data=np.repeat(-100.0 * rows, 10, axis=1),
        lon_min=24.0,
        lat_max=46.0,
        dlon=1 / 1200,
        dlat=1 / 1200,
    )
    slope = slope_degrees(dem).data
    expected = np.degrees(np.arctan(100.0 / (110_574.0 / 1200)))
    assert slope[5, 5] == pytest.approx(expected, rel=1e-3)


def test_slope_of_flat_ground_is_zero() -> None:
    """No relief, no slope."""
    dem = GeoRaster(
        data=np.full((5, 5), 300.0, dtype=np.float32),
        lon_min=24.0,
        lat_max=46.0,
        dlon=1 / 1200,
        dlat=1 / 1200,
    )
    assert np.all(slope_degrees(dem).data == 0)
