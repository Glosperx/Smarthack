"""
# Wind resource atlas constants

Fixed parameters of the hill-zone wind resource atlas: the analysis grid over Romania,
the elevation band, the buildability limit, the public data sources and the colour ramp.

The following can be imported from this module:
- `BUILDABLE_MAX_SLOPE_DEG`
- `COPERNICUS_DEM_URL`
- `ELEVATION_MAX_M`
- `ELEVATION_MIN_M`
- `GRID_LAT_MAX`
- `GRID_LAT_MIN`
- `GRID_LON_MAX`
- `GRID_LON_MIN`
- `GRID_STEP_DEG`
- `GWA_REFERENCE_FIRST_YEAR`
- `GWA_REFERENCE_LAST_YEAR`
- `GWA_WIND_SPEED_URL`
- `HEATMAP_RAMP`
- `LEAD_YEARS`
- `NASA_POWER_FIRST_YEAR`
- `NASA_POWER_PARAMETER`
- `NASA_POWER_REGIONAL_URL`
- `SITE_COUNT`
- `SITE_MIN_SEPARATION_KM`
- `SITE_MIN_VALID_FRACTION`
- `SITE_WINDOW_CELLS`
"""

#: Analysis grid: a box around Romania in WGS84 degrees, with ~0.005 deg cells
#: (about 550 m east-west by 390 m north-south at 46 N).
GRID_LON_MIN: float = 20.0
GRID_LON_MAX: float = 30.0
GRID_LAT_MIN: float = 43.5
GRID_LAT_MAX: float = 48.5
GRID_STEP_DEG: float = 0.005

#: The hill band the atlas ranks. Below it is plain, above it is mountain terrain
#: with access, icing and protected-area problems.
ELEVATION_MIN_M: float = 200.0
ELEVATION_MAX_M: float = 800.0

#: Mean terrain slope above which access roads and crane pads are impractical
#: (about 18 % grade).
BUILDABLE_MAX_SLOPE_DEG: float = 10.0

#: Global Wind Atlas v3 mean wind speed at 100 m for Romania (250 m grid, CC-BY 4.0).
GWA_WIND_SPEED_URL: str = "https://globalwindatlas.info/api/gis/country/ROU/wind-speed/100"

#: The years the Global Wind Atlas v3 long-term mean was computed from (ERA5 2008-2017).
GWA_REFERENCE_FIRST_YEAR: int = 2008
GWA_REFERENCE_LAST_YEAR: int = 2017

#: Copernicus DEM GLO-90 tiles on the public AWS open-data bucket; `{lat}` and `{lon}`
#: are the south-west corner, such as `N45` and `E024`.
COPERNICUS_DEM_URL: str = (
    "https://copernicus-dem-90m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_30_{lat}_00_{lon}_00_DEM/Copernicus_DSM_COG_30_{lat}_00_{lon}_00_DEM.tif"
)

#: NASA POWER monthly regional endpoint (MERRA-2 reanalysis, 0.5 x 0.625 deg).
NASA_POWER_REGIONAL_URL: str = "https://power.larc.nasa.gov/api/temporal/monthly/regional"

#: Wind speed at 50 m, the closest NASA POWER height to a hub.
NASA_POWER_PARAMETER: str = "WS50M"

#: First year of the long-term record requested from NASA POWER.
NASA_POWER_FIRST_YEAR: int = 1981

#: The forecast target, in years after the last complete year of data: with data up to
#: 2025, `(2, 3)` is the mean of 2027 and 2028, the next two full years.
LEAD_YEARS: tuple[int, int] = (2, 3)

#: Candidate site search: a moving window of about 3.5 x 3.5 km (an onshore park's
#: footprint), the share of it that must be buildable hill terrain, the minimum distance
#: between two proposed sites and how many to propose.
SITE_WINDOW_CELLS: tuple[int, int] = (9, 7)
SITE_MIN_VALID_FRACTION: float = 0.6
SITE_MIN_SEPARATION_KM: float = 20.0
SITE_COUNT: int = 15

#: Sequential single-hue ramp (light = less wind, dark = more wind).
HEATMAP_RAMP: tuple[str, ...] = (
    "#cde2fb",
    "#9ec5f4",
    "#6da7ec",
    "#3987e5",
    "#256abf",
    "#184f95",
    "#0d366b",
)

__all__ = [
    "BUILDABLE_MAX_SLOPE_DEG",
    "COPERNICUS_DEM_URL",
    "ELEVATION_MAX_M",
    "ELEVATION_MIN_M",
    "GRID_LAT_MAX",
    "GRID_LAT_MIN",
    "GRID_LON_MAX",
    "GRID_LON_MIN",
    "GRID_STEP_DEG",
    "GWA_REFERENCE_FIRST_YEAR",
    "GWA_REFERENCE_LAST_YEAR",
    "GWA_WIND_SPEED_URL",
    "HEATMAP_RAMP",
    "LEAD_YEARS",
    "NASA_POWER_FIRST_YEAR",
    "NASA_POWER_PARAMETER",
    "NASA_POWER_REGIONAL_URL",
    "SITE_COUNT",
    "SITE_MIN_SEPARATION_KM",
    "SITE_MIN_VALID_FRACTION",
    "SITE_WINDOW_CELLS",
]
