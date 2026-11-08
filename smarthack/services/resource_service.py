"""
# Hill wind resource atlas service

Builds the hill-zone wind atlas from public data and answers questions about it.

Building (`build_atlas`, run by `make resource`):

1. NASA POWER monthly wind 1981-last year, one request for the whole country.
2. A rolling-origin backtest picks the forecast method for the next two full years
   and calibrates its P10-P90 band (`smarthack.resource.climate`).
3. The Global Wind Atlas 250 m long-term mean (2008-2017) gives the terrain detail;
   the coarse forecast-to-reference factor moves it to the forecast years.
4. Copernicus DEM elevation and slope keep the 200-800 m hill band and buildable terrain.
5. The best park-sized windows become candidate sites; the band becomes a heatmap PNG.

Serving reads the files the build wrote: the summary, the sites, the heatmap and a
compressed grid for point queries.

The following can be imported from this module:
- `AtlasNotBuiltError`
- `build_atlas`
- `build_plain_layer`
- `heatmap_path`
- `list_plain_sites`
- `list_sites`
- `load_summary`
- `plain_heatmap_path`
- `query_point`
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
import time
from typing import Any

import httpx

from smarthack import config
from smarthack.clients import resource_sources
from smarthack.resource import constants as C
from smarthack.schemas.resource import (
    ResourceBacktestRow,
    ResourceBounds,
    ResourceLegend,
    ResourcePoint,
    ResourceSite,
    ResourceSource,
    ResourceSummary,
)

logger = logging.getLogger(__name__)

_SUMMARY_FILE = "summary.json"
_SITES_FILE = "sites.json"
_HEATMAP_FILE = "heatmap.png"
_GRID_FILE = "atlas_grid.npz"
_PLAIN_HEATMAP_FILE = "heatmap_plain.png"
_PLAIN_SITES_FILE = "sites_plain.json"

#: Seconds between two Nominatim requests (its usage policy allows one per second).
_GEOCODE_PAUSE_S = 1.1

_SOURCES = [
    ResourceSource(
        name="NASA POWER (MERRA-2) monthly wind speed at 50 m, 1981-present",
        role="Long-term record for the backtest and the forecast of the next years",
        url="https://power.larc.nasa.gov/",
        license="NASA open data, no restrictions",
    ),
    ResourceSource(
        name="Global Wind Atlas v3, mean wind speed at 100 m (250 m grid)",
        role="Terrain-resolved long-term wind of the 2008-2017 reference period",
        url="https://globalwindatlas.info/",
        license="CC BY 4.0 (DTU / World Bank Group)",
    ),
    ResourceSource(
        name="Copernicus DEM GLO-90",
        role="Elevation band (200-800 m) and terrain slope",
        url="https://registry.opendata.aws/copernicus-dem/",
        license="Copernicus DEM licence, free use with attribution (ESA / Airbus)",
    ),
    ResourceSource(
        name="OpenStreetMap Nominatim",
        role="Names of the localities near the proposed sites",
        url="https://nominatim.openstreetmap.org/",
        license="ODbL, (c) OpenStreetMap contributors",
    ),
]


class AtlasNotBuiltError(FileNotFoundError):
    """The atlas files are missing: run `make resource` first."""


def _grid() -> Any:
    """The analysis grid over Romania."""
    from smarthack.resource.grid import AnalysisGrid

    return AnalysisGrid.from_bounds(
        C.GRID_LON_MIN, C.GRID_LON_MAX, C.GRID_LAT_MIN, C.GRID_LAT_MAX, C.GRID_STEP_DEG
    )


def _cell_area_km2(lats: Any) -> Any:
    """Area of one grid cell per row latitude, in km2."""
    import numpy as np

    side_ns = C.GRID_STEP_DEG * 110.574
    side_ew = C.GRID_STEP_DEG * 111.320 * np.cos(np.radians(lats))
    return side_ns * side_ew


def _site_explanation(
    name: str | None,
    p50: float,
    p10: float,
    p90: float,
    years: tuple[int, int],
    percentile: float,
    elevation: float,
    slope: float,
    change: float,
    terrain: str = "hill",
) -> str:
    """One sentence on why a site or point stands out."""
    where = name or "This area"
    return (
        f"{where}: forecast mean wind {p50:.1f} m/s at 100 m for {years[0]}-{years[1]} "
        f"(80% band {p10:.1f}-{p90:.1f}), windier than {percentile:.0f}% of Romania's "
        f"{terrain} terrain; {elevation:.0f} m elevation, {slope:.0f} deg mean slope, "
        f"{change * 100:+.1f}% vs the {C.GWA_REFERENCE_FIRST_YEAR}-"
        f"{C.GWA_REFERENCE_LAST_YEAR} average."
    )


def _percentile(value: float, quantiles: Any) -> float:
    """Share (0-100) of hill terrain with less wind, from stored hill quantiles."""
    import numpy as np

    return float(np.interp(value, quantiles, np.linspace(0.0, 100.0, len(quantiles))))


def _dem_layers(mask: Any, grid: Any, cache_dir: Path) -> tuple[Any, Any]:
    """Mean elevation and slope per grid cell from the Copernicus tiles under `mask`."""
    import numpy as np

    from smarthack.resource.grid import block_mean, read_geotiff
    from smarthack.resource.terrain import slope_degrees

    lons, lats = grid.centers()
    rows, cols = np.nonzero(mask)
    tiles = sorted(
        set(zip(np.floor(lats[rows]).astype(int).tolist(), np.floor(lons[cols]).astype(int)))
    )
    shape = (grid.ny, grid.nx)
    elev_sum, elev_n = np.zeros(shape), np.zeros(shape)
    slope_sum, slope_n = np.zeros(shape), np.zeros(shape)
    with httpx.Client(timeout=300.0, follow_redirects=True) as http:
        for i, (lat, lon) in enumerate(tiles, start=1):
            path = resource_sources.fetch_dem_tile(cache_dir, int(lat), int(lon), client=http)
            if path is None:
                continue
            dem = read_geotiff(path)
            s, n = block_mean(dem, grid)
            elev_sum += s
            elev_n += n
            s, n = block_mean(slope_degrees(dem), grid)
            slope_sum += s
            slope_n += n
            logger.info("DEM tile %d/%d (%s, %s) done", i, len(tiles), lat, lon)
    with np.errstate(invalid="ignore", divide="ignore"):
        elevation = np.where(elev_n > 0, elev_sum / elev_n, np.nan)
        slope = np.where(slope_n > 0, slope_sum / slope_n, np.nan)
    return elevation, slope


def _plain_layer(
    p50: Any, elevation: Any, slope: Any, country: Any, grid: Any, legend: ResourceLegend
) -> tuple[bytes, dict[str, float]]:
    """
    Render the plain heatmap and measure the plain terrain.

    Plain is every land cell below the hill band (the sea is left out). It is drawn on the hill layer's wind scale,
    so a shade means the same wind speed in both layers.

    :param p50: Forecast mean wind per cell.
    :param elevation: Mean elevation per cell.
    :param slope: Mean slope per cell.
    :param country: Cells inside Romania.
    :param grid: The analysis grid.
    :param legend: The hill legend, whose wind range the plain layer reuses.

    :returns result: The PNG and the plain statistics (`area`, `buildable_area`, `wind_mean`).
    """
    import numpy as np

    from smarthack.resource.render import render_overlay_png

    plain = country & (elevation >= C.PLAIN_ELEVATION_MIN_M) & (elevation < C.ELEVATION_MIN_M)
    buildable = plain & (slope <= C.BUILDABLE_MAX_SLOPE_DEG)
    png = render_overlay_png(
        np.where(plain, p50, np.nan), grid, C.PLAIN_RAMP, legend.vmin, legend.vmax
    )
    _, lats = grid.centers()
    area = _cell_area_km2(lats)[:, None]
    stats = {
        "area": round(float((area * plain).sum()), 0),
        "buildable_area": round(float((area * buildable).sum()), 0),
        "wind_mean": round(float(np.mean(p50[plain])), 2) if plain.any() else 0.0,
    }
    return png, stats


def _plain_sites(
    p50: Any,
    elevation: Any,
    slope: Any,
    reference: Any,
    grid: Any,
    band: tuple[float, float],
    years: tuple[int, int],
    name_sites: bool,
) -> list[ResourceSite]:
    """
    Propose the windiest park-sized windows of the plain, like the hill sites.

    :param p50: Forecast mean wind per cell.
    :param elevation: Mean elevation per cell.
    :param slope: Mean slope per cell.
    :param reference: Reference-period mean wind per cell.
    :param grid: The analysis grid.
    :param band: P10 and P90 as relative deviations from P50.
    :param years: First and last forecast year.
    :param name_sites: Look up locality names.

    :returns sites: The best `PLAIN_SITE_COUNT` sites, windiest first.
    """
    import numpy as np

    from smarthack.resource.grid import box_mean
    from smarthack.resource.sites import select_sites

    plain = np.isfinite(p50) & (elevation >= C.PLAIN_ELEVATION_MIN_M)
    plain &= elevation < C.ELEVATION_MIN_M
    if not plain.any():
        return []
    buildable = plain & (slope <= C.BUILDABLE_MAX_SLOPE_DEG)
    quantiles = np.quantile(p50[plain], np.linspace(0, 1, 101))
    candidates = select_sites(
        np.where(buildable, p50, np.nan),
        grid,
        C.SITE_WINDOW_CELLS,
        C.SITE_MIN_VALID_FRACTION,
        C.SITE_MIN_SEPARATION_KM,
        # The wind grid reaches past the border, so with names on, twice as many candidates
        # are looked up and the ones Nominatim places in another country are dropped.
        C.PLAIN_SITE_COUNT * (2 if name_sites else 1),
    )
    elev_w, _ = box_mean(np.where(buildable, elevation, np.nan), C.SITE_WINDOW_CELLS)
    slope_w, _ = box_mean(np.where(buildable, slope, np.nan), C.SITE_WINDOW_CELLS)
    ref_w, _ = box_mean(np.where(buildable, reference, np.nan), C.SITE_WINDOW_CELLS)
    sites: list[ResourceSite] = []
    with httpx.Client(timeout=30.0) as http:
        for cand in candidates:
            if len(sites) == C.PLAIN_SITE_COUNT:
                break
            r, c = cand.row, cand.col
            name = None
            if name_sites:
                name, country_code = resource_sources.reverse_geocode_place(
                    cand.latitude, cand.longitude, http
                )
                time.sleep(_GEOCODE_PAUSE_S)
                if country_code not in (None, "ro"):
                    continue
            w50 = cand.window_wind
            pct = _percentile(w50, quantiles)
            change = w50 / float(ref_w[r, c]) - 1.0
            p10, p90 = w50 * (1 + band[0]), w50 * (1 + band[1])
            sites.append(
                ResourceSite(
                    rank=len(sites) + 1,
                    name=name,
                    latitude=round(cand.latitude, 5),
                    longitude=round(cand.longitude, 5),
                    wind_p50=round(w50, 2),
                    wind_p10=round(p10, 2),
                    wind_p90=round(p90, 2),
                    reference_wind=round(float(ref_w[r, c]), 2),
                    change_pct=round(change, 4),
                    elevation_m=round(float(elev_w[r, c]), 0),
                    slope_deg=round(float(slope_w[r, c]), 1),
                    buildable_fraction=round(cand.valid_fraction, 2),
                    percentile=round(pct, 1),
                    explanation=_site_explanation(
                        name,
                        w50,
                        p10,
                        p90,
                        years,
                        pct,
                        float(elev_w[r, c]),
                        float(slope_w[r, c]),
                        change,
                        terrain="plain",
                    ),
                )
            )
    return sites


def _write_plain_sites(out: Path, sites: list[ResourceSite]) -> None:
    """Write the plain sites next to the hill ones."""
    text = json.dumps([s.model_dump() for s in sites], indent=2, ensure_ascii=False)
    (out / _PLAIN_SITES_FILE).write_text(text, encoding="utf-8")


def build_plain_layer(atlas_dir: Path | None = None, name_sites: bool = True) -> ResourceSummary:
    """
    Add the plain heatmap and sites to an atlas built without them, from its stored grid.

    Needs no download: it reads the grid file `build_atlas` wrote and updates the summary.

    :param atlas_dir: Atlas directory, `RESOURCE_ATLAS_DIR` by default.
    :param name_sites: Look up locality names for the plain sites.

    :returns summary: The updated summary.
    :raises AtlasNotBuiltError: If the atlas has not been built.
    """
    import numpy as np

    out = atlas_dir or config.resource_atlas_dir()
    summary = load_summary(out)
    with np.load(_atlas_file(_GRID_FILE, out)) as data:
        p50 = data["p50"].astype(np.float32)
        elevation = data["elevation"].astype(np.float32)
        slope = data["slope"].astype(np.float32)
        reference = data["reference"].astype(np.float32)
    _write_plain_sites(
        out,
        _plain_sites(
            p50,
            elevation,
            slope,
            reference,
            _grid(),
            (summary.band_low_pct, summary.band_high_pct),
            (summary.target_years[0], summary.target_years[1]),
            name_sites,
        ),
    )
    png, stats = _plain_layer(p50, elevation, slope, np.isfinite(p50), _grid(), summary.legend)
    (out / _PLAIN_HEATMAP_FILE).write_bytes(png)
    updated = summary.model_copy(
        update={
            "plain_legend": ResourceLegend(
                vmin=summary.legend.vmin, vmax=summary.legend.vmax, colors=list(C.PLAIN_RAMP)
            ),
            "plain_area_km2": stats["area"],
            "plain_buildable_area_km2": stats["buildable_area"],
            "plain_wind_p50_mean": stats["wind_mean"],
        }
    )
    (out / _SUMMARY_FILE).write_text(updated.model_dump_json(indent=2), encoding="utf-8")
    _cache.clear()
    return updated


def build_atlas(
    cache_dir: Path | None = None,
    atlas_dir: Path | None = None,
    last_year: int | None = None,
    name_sites: bool = True,
) -> ResourceSummary:
    """
    Build the hill wind atlas end to end and write it to `atlas_dir`.

    :param cache_dir: Download cache, `RESOURCE_CACHE_DIR` by default.
    :param atlas_dir: Output directory, `RESOURCE_ATLAS_DIR` by default.
    :param last_year: Last complete year of wind data, the previous calendar year by default.
    :param name_sites: Look up locality names for the proposed sites.

    :returns summary: The summary written next to the heatmap.
    :raises httpx.HTTPError: When a required download fails.
    """
    import numpy as np

    from smarthack.resource.climate import forecast_factor, parse_power_regional, run_backtest
    from smarthack.resource.grid import bilinear_from_coarse, block_mean, box_mean, read_geotiff
    from smarthack.resource.render import render_overlay_png
    from smarthack.resource.sites import select_sites

    cache = cache_dir or config.resource_cache_dir()
    out = atlas_dir or config.resource_atlas_dir()
    out.mkdir(parents=True, exist_ok=True)
    final_year = last_year or datetime.now(timezone.utc).year - 1
    grid = _grid()

    # 1-2. Long-term record, backtest and forecast factor.
    payload = resource_sources.fetch_nasa_power(
        cache,
        C.NASA_POWER_FIRST_YEAR,
        final_year,
        (C.GRID_LON_MIN, C.GRID_LAT_MIN, C.GRID_LON_MAX, C.GRID_LAT_MAX),
    )
    cube = parse_power_regional(payload, C.NASA_POWER_PARAMETER)
    backtest = run_backtest(cube, C.LEAD_YEARS)
    logger.info(
        "Backtest selected %s (test MAE %.3f m/s, band coverage %.2f)",
        backtest.selected,
        backtest.mae_test[backtest.selected],
        backtest.band_coverage_test,
    )
    reference = (C.GWA_REFERENCE_FIRST_YEAR, C.GWA_REFERENCE_LAST_YEAR)
    fc = forecast_factor(cube, backtest.selected, C.LEAD_YEARS, reference)

    # 3. Fine-scale reference wind, moved to the forecast years.
    gwa_sum, gwa_n = block_mean(read_geotiff(resource_sources.fetch_gwa_wind_speed(cache)), grid)
    with np.errstate(invalid="ignore", divide="ignore"):
        gwa = np.where(gwa_n > 0, gwa_sum / gwa_n, np.nan)
    country = np.isfinite(gwa)
    factor = bilinear_from_coarse(fc.factor, cube.lats, cube.lons, grid)
    p50 = np.where(country, gwa * factor, np.nan)

    # 4. Terrain: hill band and buildable slopes.
    elevation, slope = _dem_layers(country, grid, cache)
    hill = country & (elevation >= C.ELEVATION_MIN_M) & (elevation <= C.ELEVATION_MAX_M)
    buildable = hill & (slope <= C.BUILDABLE_MAX_SLOPE_DEG)
    hill_wind = p50[hill]
    quantiles = np.quantile(hill_wind, np.linspace(0, 1, 101))

    # 5. Heatmap and sites.
    vmin = math.floor(float(np.quantile(hill_wind, 0.02)) * 2) / 2
    vmax = math.ceil(float(np.quantile(hill_wind, 0.995)) * 2) / 2
    png = render_overlay_png(np.where(hill, p50, np.nan), grid, C.HEATMAP_RAMP, vmin, vmax)
    (out / _HEATMAP_FILE).write_bytes(png)
    legend = ResourceLegend(vmin=vmin, vmax=vmax, colors=list(C.HEATMAP_RAMP))
    plain_png, plain = _plain_layer(p50, elevation, slope, country, grid, legend)
    (out / _PLAIN_HEATMAP_FILE).write_bytes(plain_png)

    eligible = np.where(buildable, p50, np.nan)
    candidates = select_sites(
        eligible,
        grid,
        C.SITE_WINDOW_CELLS,
        C.SITE_MIN_VALID_FRACTION,
        C.SITE_MIN_SEPARATION_KM,
        C.SITE_COUNT,
    )
    elev_w, _ = box_mean(np.where(buildable, elevation, np.nan), C.SITE_WINDOW_CELLS)
    slope_w, _ = box_mean(np.where(buildable, slope, np.nan), C.SITE_WINDOW_CELLS)
    ref_w, _ = box_mean(np.where(buildable, gwa, np.nan), C.SITE_WINDOW_CELLS)
    sites: list[ResourceSite] = []
    with httpx.Client(timeout=30.0) as http:
        for cand in candidates:
            r, c = cand.row, cand.col
            name = None
            if name_sites:
                name = resource_sources.reverse_geocode(cand.latitude, cand.longitude, http)
                time.sleep(_GEOCODE_PAUSE_S)
            w50 = cand.window_wind
            ref = float(ref_w[r, c])
            pct = _percentile(w50, quantiles)
            change = w50 / ref - 1.0
            p10, p90 = w50 * (1 + backtest.band_low), w50 * (1 + backtest.band_high)
            sites.append(
                ResourceSite(
                    rank=cand.rank,
                    name=name,
                    latitude=round(cand.latitude, 5),
                    longitude=round(cand.longitude, 5),
                    wind_p50=round(w50, 2),
                    wind_p10=round(p10, 2),
                    wind_p90=round(p90, 2),
                    reference_wind=round(ref, 2),
                    change_pct=round(change, 4),
                    elevation_m=round(float(elev_w[r, c]), 0),
                    slope_deg=round(float(slope_w[r, c]), 1),
                    buildable_fraction=round(cand.valid_fraction, 2),
                    percentile=round(pct, 1),
                    explanation=_site_explanation(
                        name,
                        w50,
                        p10,
                        p90,
                        fc.target_years,
                        pct,
                        float(elev_w[r, c]),
                        float(slope_w[r, c]),
                        change,
                    ),
                )
            )

    # Grid for point queries: float16 keeps it small; NaN outside the country.
    np.savez_compressed(
        out / _GRID_FILE,
        p50=p50.astype(np.float16),
        reference=np.where(country, gwa, np.nan).astype(np.float16),
        elevation=np.where(country, elevation, np.nan).astype(np.float16),
        slope=np.where(country, slope, np.nan).astype(np.float16),
        hill_quantiles=quantiles.astype(np.float32),
    )

    _, lats = grid.centers()
    area = _cell_area_km2(lats)[:, None]
    summary = ResourceSummary(
        target_years=list(fc.target_years),
        data_until=int(cube.years.max()),
        reference_years=list(reference),
        bounds=ResourceBounds(
            south=grid.lat_min, west=grid.lon_min, north=grid.lat_max, east=grid.lon_max
        ),
        elevation_band_m=[C.ELEVATION_MIN_M, C.ELEVATION_MAX_M],
        max_slope_deg=C.BUILDABLE_MAX_SLOPE_DEG,
        legend=legend,
        plain_legend=ResourceLegend(vmin=vmin, vmax=vmax, colors=list(C.PLAIN_RAMP)),
        plain_area_km2=plain["area"],
        plain_buildable_area_km2=plain["buildable_area"],
        plain_wind_p50_mean=plain["wind_mean"],
        selected_estimator=backtest.selected,
        backtest=[
            ResourceBacktestRow(
                estimator=name,
                mae_validation=round(backtest.mae_validation[name], 4),
                mae_test=round(backtest.mae_test[name], 4),
                mape_test=round(backtest.mape_test[name], 4),
                selected=name == backtest.selected,
            )
            for name in sorted(backtest.mae_test, key=lambda n: backtest.mae_validation[n])
        ],
        validation_years=list(backtest.validation_targets),
        test_years=list(backtest.test_targets),
        band_low_pct=round(backtest.band_low, 4),
        band_high_pct=round(backtest.band_high, 4),
        band_coverage_test=round(backtest.band_coverage_test, 3),
        rank_correlation_test=round(backtest.rank_correlation_test, 4),
        hill_area_km2=round(float((area * hill).sum()), 0),
        buildable_area_km2=round(float((area * buildable).sum()), 0),
        hill_wind_p50_mean=round(float(np.mean(hill_wind)), 2),
        sources=_SOURCES,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    (out / _SUMMARY_FILE).write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    sites_json = json.dumps([s.model_dump() for s in sites], indent=2, ensure_ascii=False)
    (out / _SITES_FILE).write_text(sites_json, encoding="utf-8")
    _write_plain_sites(
        out,
        _plain_sites(
            p50,
            elevation,
            slope,
            np.where(country, gwa, np.nan),
            grid,
            (backtest.band_low, backtest.band_high),
            fc.target_years,
            name_sites,
        ),
    )
    _cache.clear()
    logger.info("Atlas written to %s: %d sites", out, len(sites))
    return summary


@dataclass
class _LoadedGrid:
    """Point-query arrays read from the grid file."""

    p50: Any
    reference: Any
    elevation: Any
    slope: Any
    hill_quantiles: Any


#: Loaded files keyed by path and modification time, so a rebuild is picked up.
_cache: dict[tuple[str, float], Any] = {}


def _atlas_file(name: str, atlas_dir: Path | None) -> Path:
    """Path of an atlas file, raising when it has not been built."""
    path = (atlas_dir or config.resource_atlas_dir()) / name
    if not path.is_file():
        raise AtlasNotBuiltError(f"{path} not found: run `make resource` to build the atlas")
    return path


def _cached(path: Path, loader: Any) -> Any:
    """Load a file once per modification time."""
    key = (str(path), path.stat().st_mtime)
    if key not in _cache:
        _cache[key] = loader(path)
    return _cache[key]


def load_summary(atlas_dir: Path | None = None) -> ResourceSummary:
    """
    Read the atlas summary.

    :param atlas_dir: Atlas directory, `RESOURCE_ATLAS_DIR` by default.

    :returns summary: Method, backtest, legend and sources.
    :raises AtlasNotBuiltError: If the atlas has not been built.
    """
    path = _atlas_file(_SUMMARY_FILE, atlas_dir)
    summary: ResourceSummary = _cached(
        path, lambda p: ResourceSummary.model_validate_json(p.read_text(encoding="utf-8"))
    )
    return summary


def list_sites(atlas_dir: Path | None = None) -> list[ResourceSite]:
    """
    Read the proposed sites, best first.

    :param atlas_dir: Atlas directory, `RESOURCE_ATLAS_DIR` by default.

    :returns sites: Candidate sites in rank order.
    :raises AtlasNotBuiltError: If the atlas has not been built.
    """
    path = _atlas_file(_SITES_FILE, atlas_dir)
    sites: list[ResourceSite] = _cached(
        path,
        lambda p: [ResourceSite.model_validate(s) for s in json.loads(p.read_text("utf-8"))],
    )
    return sites


def list_plain_sites(atlas_dir: Path | None = None) -> list[ResourceSite]:
    """
    Read the proposed plain sites, windiest first.

    :param atlas_dir: Atlas directory, `RESOURCE_ATLAS_DIR` by default.

    :returns sites: Candidate plain sites in rank order.
    :raises AtlasNotBuiltError: If the plain layer has not been built.
    """
    path = _atlas_file(_PLAIN_SITES_FILE, atlas_dir)
    sites: list[ResourceSite] = _cached(
        path,
        lambda p: [ResourceSite.model_validate(s) for s in json.loads(p.read_text("utf-8"))],
    )
    return sites


def heatmap_path(atlas_dir: Path | None = None) -> Path:
    """
    Locate the heatmap image.

    :param atlas_dir: Atlas directory, `RESOURCE_ATLAS_DIR` by default.

    :returns path: The PNG overlay.
    :raises AtlasNotBuiltError: If the atlas has not been built.
    """
    return _atlas_file(_HEATMAP_FILE, atlas_dir)


def plain_heatmap_path(atlas_dir: Path | None = None) -> Path:
    """
    Locate the plain heatmap image.

    :param atlas_dir: Atlas directory, `RESOURCE_ATLAS_DIR` by default.

    :returns path: The PNG overlay.
    :raises AtlasNotBuiltError: If the plain layer has not been built.
    """
    return _atlas_file(_PLAIN_HEATMAP_FILE, atlas_dir)


def _load_grid(path: Path) -> _LoadedGrid:
    """Read the point-query arrays."""
    import numpy as np

    with np.load(path) as data:
        return _LoadedGrid(
            p50=data["p50"],
            reference=data["reference"],
            elevation=data["elevation"],
            slope=data["slope"],
            hill_quantiles=data["hill_quantiles"],
        )


def query_point(lat: float, lon: float, atlas_dir: Path | None = None) -> ResourcePoint:
    """
    Describe the forecast wind and terrain of the grid cell containing a point.

    :param lat: Latitude.
    :param lon: Longitude.
    :param atlas_dir: Atlas directory, `RESOURCE_ATLAS_DIR` by default.

    :returns point: Values for the cell and a plain-language reading.
    :raises AtlasNotBuiltError: If the atlas has not been built.
    """
    import numpy as np

    summary = load_summary(atlas_dir)
    data: _LoadedGrid = _cached(_atlas_file(_GRID_FILE, atlas_dir), _load_grid)
    cell = _grid().index_of(lat, lon)
    p50 = float(data.p50[cell]) if cell is not None else math.nan
    if cell is None or not np.isfinite(p50):
        return ResourcePoint(
            latitude=lat,
            longitude=lon,
            inside_country=False,
            in_band=False,
            buildable=False,
            explanation="Outside Romania: the atlas has no data here.",
        )

    elevation = float(data.elevation[cell])
    slope = float(data.slope[cell])
    reference = float(data.reference[cell])
    in_band = C.ELEVATION_MIN_M <= elevation <= C.ELEVATION_MAX_M
    in_plain = C.PLAIN_ELEVATION_MIN_M <= elevation < C.ELEVATION_MIN_M
    buildable = (in_band or in_plain) and slope <= C.BUILDABLE_MAX_SLOPE_DEG
    p10 = p50 * (1 + summary.band_low_pct)
    p90 = p50 * (1 + summary.band_high_pct)
    change = p50 / reference - 1.0
    pct = _percentile(p50, data.hill_quantiles)
    years = (summary.target_years[0], summary.target_years[1])

    if in_plain:
        explanation = (
            f"Plain below {C.ELEVATION_MIN_M:.0f} m: forecast mean wind {p50:.1f} m/s at 100 m "
            f"for {years[0]}-{years[1]} (80% band {p10:.1f}-{p90:.1f}), {slope:.0f} deg slope, "
            f"{change * 100:+.1f}% vs the {C.GWA_REFERENCE_FIRST_YEAR}-"
            f"{C.GWA_REFERENCE_LAST_YEAR} average. "
            + (
                "Gentle enough to build on."
                if buildable
                else f"Slope is above the {C.BUILDABLE_MAX_SLOPE_DEG:.0f} deg buildable limit."
            )
        )
    elif not in_band:
        explanation = (
            f"Elevation {elevation:.0f} m is outside the {C.ELEVATION_MIN_M:.0f}-"
            f"{C.ELEVATION_MAX_M:.0f} m hill band. Forecast mean wind here: {p50:.1f} m/s."
        )
    elif not buildable:
        explanation = (
            f"Hill terrain with forecast mean wind {p50:.1f} m/s, but the mean slope of "
            f"{slope:.0f} deg is above the {C.BUILDABLE_MAX_SLOPE_DEG:.0f} deg buildable limit."
        )
    else:
        explanation = _site_explanation(None, p50, p10, p90, years, pct, elevation, slope, change)

    return ResourcePoint(
        latitude=lat,
        longitude=lon,
        inside_country=True,
        in_band=in_band,
        in_plain=in_plain,
        buildable=buildable,
        elevation_m=round(elevation, 0),
        slope_deg=round(slope, 1),
        wind_p50=round(p50, 2),
        wind_p10=round(p10, 2),
        wind_p90=round(p90, 2),
        reference_wind=round(reference, 2),
        change_pct=round(change, 4),
        percentile=round(pct, 1) if in_band else None,
        explanation=explanation,
    )


__all__ = [
    "AtlasNotBuiltError",
    "build_atlas",
    "build_plain_layer",
    "heatmap_path",
    "list_plain_sites",
    "list_sites",
    "load_summary",
    "plain_heatmap_path",
    "query_point",
]
