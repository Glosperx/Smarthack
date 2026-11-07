"""
# Analysis grid and raster helpers

A regular latitude-longitude grid over Romania, and the operations that put every source
on it: reading a GeoTIFF with its georeferencing, averaging a fine raster into grid cells,
interpolating a coarse field onto the grid, and reprojecting rows to Web Mercator so an
image overlay lines up with the map tiles.

The following can be imported from this module:
- `AnalysisGrid`
- `GeoRaster`
- `bilinear_from_coarse`
- `block_mean`
- `box_mean`
- `mercator_row_index`
- `read_geotiff`
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class AnalysisGrid:
    """A north-up grid of square-degree cells; row 0 is the northern edge."""

    lon_min: float
    lat_max: float
    step: float
    nx: int
    ny: int

    @classmethod
    def from_bounds(
        cls, lon_min: float, lon_max: float, lat_min: float, lat_max: float, step: float
    ) -> "AnalysisGrid":
        """
        Build the grid covering a bounding box.

        :param lon_min: Western edge.
        :param lon_max: Eastern edge.
        :param lat_min: Southern edge.
        :param lat_max: Northern edge.
        :param step: Cell size in degrees.

        :returns grid: The grid.
        """
        nx = int(round((lon_max - lon_min) / step))
        ny = int(round((lat_max - lat_min) / step))
        return cls(lon_min=lon_min, lat_max=lat_max, step=step, nx=nx, ny=ny)

    @property
    def lon_max(self) -> float:
        """Eastern edge of the grid."""
        return self.lon_min + self.nx * self.step

    @property
    def lat_min(self) -> float:
        """Southern edge of the grid."""
        return self.lat_max - self.ny * self.step

    def centers(self) -> tuple[np.ndarray, np.ndarray]:
        """
        Cell-centre coordinates.

        :returns lons_lats: 1-D longitudes (per column) and latitudes (per row).
        """
        lons = self.lon_min + (np.arange(self.nx) + 0.5) * self.step
        lats = self.lat_max - (np.arange(self.ny) + 0.5) * self.step
        return lons, lats

    def index_of(self, lat: float, lon: float) -> tuple[int, int] | None:
        """
        Find the cell containing a point.

        :param lat: Latitude.
        :param lon: Longitude.

        :returns row_col: Row and column, or None outside the grid.
        """
        col = int(np.floor((lon - self.lon_min) / self.step))
        row = int(np.floor((self.lat_max - lat) / self.step))
        if 0 <= row < self.ny and 0 <= col < self.nx:
            return row, col
        return None


@dataclass
class GeoRaster:
    """A north-up raster with the coordinates of its top-left corner and pixel size."""

    data: np.ndarray
    lon_min: float
    lat_max: float
    dlon: float
    dlat: float


def read_geotiff(path: str | Path) -> GeoRaster:
    """
    Read the first band of a north-up GeoTIFF in geographic coordinates.

    Uses the ModelPixelScale and ModelTiepoint tags; a GDAL nodata value becomes NaN.

    :param path: GeoTIFF file.

    :returns raster: Data as float32 with its georeferencing.
    :raises ValueError: If the file carries no georeferencing tags.
    """
    import tifffile

    with tifffile.TiffFile(str(path)) as tif:
        page = tif.pages[0]
        if not isinstance(page, tifffile.TiffPage):
            raise ValueError(f"{path} has no readable first page")
        scale = page.tags.get("ModelPixelScaleTag")
        tie = page.tags.get("ModelTiepointTag")
        if scale is None or tie is None:
            raise ValueError(f"{path} has no GeoTIFF georeferencing")
        sx, sy = float(scale.value[0]), float(scale.value[1])
        # ModelTiepoint is (I, J, K, X, Y, Z): raster point (I, J) sits at (X, Y).
        i, j, x, y = (float(tie.value[k]) for k in (0, 1, 3, 4))
        data = page.asarray().astype(np.float32)
        nodata = page.tags.get("GDAL_NODATA")
        if nodata is not None:
            try:
                data[data == float(str(nodata.value).strip("\x00 "))] = np.nan
            except ValueError:
                pass
    return GeoRaster(data=data, lon_min=x - i * sx, lat_max=y + j * sy, dlon=sx, dlat=sy)


def block_mean(raster: GeoRaster, grid: AnalysisGrid) -> tuple[np.ndarray, np.ndarray]:
    """
    Average every finite raster pixel into the grid cell its centre falls in.

    :param raster: Source raster, finer than the grid.
    :param grid: Target grid.

    :returns sums_counts: Per-cell sum and pixel count, shaped `[ny, nx]`, so several
        rasters (tiles) can be accumulated before dividing.
    """
    rows, cols = raster.data.shape
    lons = raster.lon_min + (np.arange(cols) + 0.5) * raster.dlon
    lats = raster.lat_max - (np.arange(rows) + 0.5) * raster.dlat
    gc = np.floor((lons - grid.lon_min) / grid.step).astype(np.int64)
    gr = np.floor((grid.lat_max - lats) / grid.step).astype(np.int64)
    col_ok = (gc >= 0) & (gc < grid.nx)
    row_ok = (gr >= 0) & (gr < grid.ny)

    block = raster.data[np.ix_(row_ok, col_ok)]
    flat = (gr[row_ok][:, None] * grid.nx + gc[col_ok][None, :]).ravel()
    vals = block.ravel()
    ok = np.isfinite(vals)
    size = grid.nx * grid.ny
    sums = np.bincount(flat[ok], weights=vals[ok], minlength=size).reshape(grid.ny, grid.nx)
    counts = np.bincount(flat[ok], minlength=size).reshape(grid.ny, grid.nx)
    return sums, counts.astype(np.float64)


def bilinear_from_coarse(
    field: np.ndarray, lats: np.ndarray, lons: np.ndarray, grid: AnalysisGrid
) -> np.ndarray:
    """
    Interpolate a coarse `[lat, lon]` field (ascending axes) bilinearly onto the grid.

    Points outside the coarse grid take the value of its nearest edge.

    :param field: Coarse values.
    :param lats: Ascending latitudes of the coarse rows.
    :param lons: Ascending longitudes of the coarse columns.
    :param grid: Target grid.

    :returns values: `[ny, nx]` interpolated values.
    """
    glons, glats = grid.centers()

    def weights(axis: np.ndarray, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Lower index, upper index and upper weight of each point along one axis."""
        pos = np.clip(np.interp(pts, axis, np.arange(len(axis))), 0, len(axis) - 1)
        lo = np.floor(pos).astype(int)
        hi = np.minimum(lo + 1, len(axis) - 1)
        return lo, hi, pos - lo

    r0, r1, wr = weights(lats, glats)
    c0, c1, wc = weights(lons, glons)
    f00 = field[np.ix_(r0, c0)]
    f01 = field[np.ix_(r0, c1)]
    f10 = field[np.ix_(r1, c0)]
    f11 = field[np.ix_(r1, c1)]
    wr2, wc2 = wr[:, None], wc[None, :]
    top = f00 * (1 - wc2) + f01 * wc2
    bottom = f10 * (1 - wc2) + f11 * wc2
    return np.asarray(top * (1 - wr2) + bottom * wr2)


def box_mean(values: np.ndarray, window: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """
    Moving-window mean that ignores NaN, with the share of valid cells in each window.

    :param values: `[ny, nx]` field with NaN where undefined.
    :param window: Window width (columns) and height (rows), odd numbers.

    :returns mean_fraction: Window mean and fraction of finite cells, both `[ny, nx]`.
    """
    wx, wy = window
    valid = np.isfinite(values)
    filled = np.where(valid, values, 0.0)

    def window_sum(a: np.ndarray) -> np.ndarray:
        """Sum over the window using a padded summed-area table."""
        padded = np.pad(a, ((wy // 2 + 1, wy // 2), (wx // 2 + 1, wx // 2)))
        sat = padded.cumsum(0).cumsum(1)
        return np.asarray(sat[wy:, wx:] - sat[:-wy, wx:] - sat[wy:, :-wx] + sat[:-wy, :-wx])

    total = window_sum(filled)
    count = window_sum(valid.astype(float))
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(count > 0, total / count, np.nan)
    return np.asarray(mean), np.asarray(count / (wx * wy))


def _mercator_y(lat_deg: np.ndarray | float) -> np.ndarray:
    """Web Mercator northing (unitless) of a latitude."""
    phi = np.radians(lat_deg)
    return np.asarray(np.log(np.tan(np.pi / 4 + phi / 2)))


def mercator_row_index(grid: AnalysisGrid, out_rows: int | None = None) -> np.ndarray:
    """
    Source grid row for each row of an image spaced evenly in Web Mercator.

    A Leaflet image overlay stretches the image linearly between its bounds in Mercator,
    so a plain latitude grid lands a few kilometres off mid-image. Sampling rows this way
    puts every pixel where it belongs.

    :param grid: The latitude-spaced grid.
    :param out_rows: Rows of the output image, the grid's own row count by default.

    :returns rows: Index into the grid rows for each output row, top to bottom.
    """
    n = out_rows or grid.ny
    y_top, y_bottom = _mercator_y(grid.lat_max), _mercator_y(grid.lat_min)
    ys = y_top - (np.arange(n) + 0.5) / n * (y_top - y_bottom)
    lats = np.degrees(2 * np.arctan(np.exp(ys)) - np.pi / 2)
    rows = np.floor((grid.lat_max - lats) / grid.step).astype(int)
    return np.asarray(np.clip(rows, 0, grid.ny - 1))


__all__ = [
    "AnalysisGrid",
    "GeoRaster",
    "bilinear_from_coarse",
    "block_mean",
    "box_mean",
    "mercator_row_index",
    "read_geotiff",
]
