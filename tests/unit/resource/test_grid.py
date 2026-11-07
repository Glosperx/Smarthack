"""
Unit tests for the analysis grid and raster helpers.
"""

from pathlib import Path

import numpy as np
import pytest

from smarthack.resource.grid import (
    AnalysisGrid,
    GeoRaster,
    bilinear_from_coarse,
    block_mean,
    box_mean,
    mercator_row_index,
    read_geotiff,
)
from tests.conftest import skip_module_without_extra

skip_module_without_extra("resource")


def small_grid() -> AnalysisGrid:
    """A 4 x 2 grid of 0.5 degree cells over 20-22 E, 44-45 N."""
    return AnalysisGrid.from_bounds(20.0, 22.0, 44.0, 45.0, 0.5)


def test_grid_bounds_and_lookup() -> None:
    """Edges, centres and point lookup agree with each other."""
    grid = small_grid()
    assert (grid.nx, grid.ny) == (4, 2)
    assert grid.lon_max == pytest.approx(22.0)
    assert grid.lat_min == pytest.approx(44.0)
    lons, lats = grid.centers()
    assert lons[0] == pytest.approx(20.25)
    assert lats[0] == pytest.approx(44.75)
    assert grid.index_of(44.9, 20.1) == (0, 0)
    assert grid.index_of(44.1, 21.9) == (1, 3)
    assert grid.index_of(50.0, 21.0) is None


def test_block_mean_averages_fine_pixels_into_cells() -> None:
    """A 0.25 degree raster: four pixels per cell, NaN pixels are left out."""
    data = np.arange(32, dtype=np.float32).reshape(4, 8)
    data[0, 0] = np.nan
    raster = GeoRaster(data=data, lon_min=20.0, lat_max=45.0, dlon=0.25, dlat=0.25)
    sums, counts = block_mean(raster, small_grid())
    assert counts[0, 0] == 3
    assert sums[0, 0] / counts[0, 0] == pytest.approx((1 + 8 + 9) / 3)
    assert counts[1, 3] == 4


def test_block_mean_ignores_pixels_outside_the_grid() -> None:
    """Pixels west of the grid contribute nothing."""
    raster = GeoRaster(
        data=np.ones((2, 2), dtype=np.float32), lon_min=10.0, lat_max=45.0, dlon=0.5, dlat=0.5
    )
    _, counts = block_mean(raster, small_grid())
    assert counts.sum() == 0


def test_bilinear_reproduces_a_linear_field() -> None:
    """Bilinear interpolation is exact for a plane."""
    lats = np.array([43.5, 45.5])
    lons = np.array([19.5, 22.5])
    field = np.array([[lon + 2 * lat for lon in lons] for lat in lats])
    grid = small_grid()
    out = bilinear_from_coarse(field, lats, lons, grid)
    glons, glats = grid.centers()
    expected = glons[None, :] + 2 * glats[:, None]
    np.testing.assert_allclose(out, expected)


def test_box_mean_skips_nan_and_reports_the_valid_share() -> None:
    """A 3 x 3 window over a field with one NaN."""
    values = np.ones((5, 5))
    values[2, 2] = np.nan
    mean, fraction = box_mean(values, (3, 3))
    assert mean[2, 2] == pytest.approx(1.0)
    assert fraction[2, 2] == pytest.approx(8 / 9)
    assert fraction[0, 0] == pytest.approx(4 / 9)


def test_mercator_rows_are_monotonic_and_cover_the_grid() -> None:
    """Output rows run north to south and span every source row."""
    grid = AnalysisGrid.from_bounds(20.0, 30.0, 43.5, 48.5, 0.005)
    rows = mercator_row_index(grid)
    assert rows[0] == 0 and rows[-1] == grid.ny - 1
    assert np.all(np.diff(rows) >= 0)
    # Mercator stretches the north: the middle output row lies north of the middle latitude.
    assert rows[len(rows) // 2] < grid.ny // 2


def test_read_geotiff_round_trip(tmp_path: Path) -> None:
    """Georeferencing tags written by tifffile are read back as the raster corner."""
    import tifffile

    path = tmp_path / "tiny.tif"
    data = np.array([[1.0, 2.0], [3.0, -9999.0]], dtype=np.float32)
    tifffile.imwrite(
        path,
        data,
        extratags=[
            (33550, "d", 3, (0.5, 0.25, 0.0), False),
            (33922, "d", 6, (0.0, 0.0, 0.0, 24.0, 46.0, 0.0), False),
            (42113, "s", 0, "-9999", False),
        ],
    )
    raster = read_geotiff(path)
    assert (raster.lon_min, raster.lat_max) == (24.0, 46.0)
    assert (raster.dlon, raster.dlat) == (0.5, 0.25)
    assert np.isnan(raster.data[1, 1])
    assert raster.data[0, 1] == 2.0


def test_read_geotiff_without_georeferencing_is_refused(tmp_path: Path) -> None:
    """A plain TIFF cannot be placed on the map."""
    import tifffile

    path = tmp_path / "plain.tif"
    tifffile.imwrite(path, np.zeros((2, 2), dtype=np.float32))
    with pytest.raises(ValueError):
        read_geotiff(path)
