"""
# Wind resource data sources

Downloads, with an on-disk cache, of the public datasets behind the hill-zone wind
atlas: NASA POWER monthly wind (MERRA-2), the Global Wind Atlas mean wind speed GeoTIFF,
Copernicus DEM GLO-90 elevation tiles, and OpenStreetMap Nominatim place names.

Every file is fetched once; a later build reads it from the cache directory.

The following can be imported from this module:
- `dem_tile_name`
- `download_file`
- `fetch_dem_tile`
- `fetch_gwa_wind_speed`
- `fetch_nasa_power`
- `reverse_geocode`
- `reverse_geocode_place`
"""

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from smarthack.resource.constants import (
    COPERNICUS_DEM_URL,
    GWA_WIND_SPEED_URL,
    NASA_POWER_PARAMETER,
    NASA_POWER_REGIONAL_URL,
)

logger = logging.getLogger(__name__)

#: Large rasters and the NASA regional query can take minutes on a slow link.
_DOWNLOAD_TIMEOUT_S = 300.0

#: OpenStreetMap Nominatim reverse geocoding (usage policy: identify the client, 1 req/s).
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"

#: Generic client name sent to public services that ask clients to identify themselves.
_USER_AGENT = "smarthack-wind-resource-atlas/0.1"


def download_file(url: str, dest: Path, client: httpx.Client | None = None) -> Path | None:
    """
    Download a URL to a file unless the file is already there.

    Writes to a temporary name first and renames on success, so an interrupted download
    never leaves a truncated file that looks complete.

    :param url: Source URL.
    :param dest: Target file.
    :param client: Optional HTTP client to reuse.

    :returns path: The file, or None when the server has no such object (403/404).
    :raises httpx.HTTPError: On any other HTTP or network failure.
    """
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    own = client is None
    http = client or httpx.Client(timeout=_DOWNLOAD_TIMEOUT_S, follow_redirects=True)
    try:
        with http.stream("GET", url) as resp:
            if resp.status_code in (403, 404):
                return None
            resp.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_bytes(1 << 20):
                    fh.write(chunk)
        tmp.replace(dest)
        return dest
    finally:
        if tmp.exists():
            tmp.unlink()
        if own:
            http.close()


def fetch_nasa_power(
    cache_dir: Path,
    first_year: int,
    last_year: int,
    bbox: tuple[float, float, float, float],
) -> dict[str, Any]:
    """
    Fetch NASA POWER monthly wind at 50 m for a bounding box, in one request.

    :param cache_dir: Directory of the download cache.
    :param first_year: First year requested.
    :param last_year: Last year requested.
    :param bbox: West, south, east, north in degrees.

    :returns payload: The GeoJSON response.
    :raises httpx.HTTPError: When the request fails.
    """
    west, south, east, north = bbox
    dest = cache_dir / f"nasa_power_{NASA_POWER_PARAMETER}_{first_year}_{last_year}.json"
    if not dest.is_file():
        params: dict[str, str | float] = {
            "parameters": NASA_POWER_PARAMETER,
            "community": "RE",
            "latitude-min": south,
            "latitude-max": north,
            "longitude-min": west,
            "longitude-max": east,
            "start": str(first_year),
            "end": str(last_year),
            "format": "JSON",
        }
        logger.info("NASA POWER: requesting %s %d-%d", NASA_POWER_PARAMETER, first_year, last_year)
        resp = httpx.get(NASA_POWER_REGIONAL_URL, params=params, timeout=_DOWNLOAD_TIMEOUT_S)
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(resp.text, encoding="utf-8")
    payload: dict[str, Any] = json.loads(dest.read_text(encoding="utf-8"))
    return payload


def fetch_gwa_wind_speed(cache_dir: Path) -> Path:
    """
    Fetch the Global Wind Atlas mean wind speed at 100 m for Romania.

    :param cache_dir: Directory of the download cache.

    :returns path: The GeoTIFF file.
    :raises FileNotFoundError: If the atlas server refuses the request.
    """
    path = download_file(GWA_WIND_SPEED_URL, cache_dir / "gwa_rou_wind_speed_100m.tif")
    if path is None:
        raise FileNotFoundError(f"Global Wind Atlas refused {GWA_WIND_SPEED_URL}")
    return path


def dem_tile_name(lat_floor: int, lon_floor: int) -> tuple[str, str]:
    """
    Name the Copernicus DEM tile whose south-west corner is at the given degrees.

    :param lat_floor: Southern edge latitude.
    :param lon_floor: Western edge longitude.

    :returns lat_lon: Such as `("N45", "E024")`.
    """
    lat = f"{'N' if lat_floor >= 0 else 'S'}{abs(lat_floor):02d}"
    lon = f"{'E' if lon_floor >= 0 else 'W'}{abs(lon_floor):03d}"
    return lat, lon


def fetch_dem_tile(
    cache_dir: Path, lat_floor: int, lon_floor: int, client: httpx.Client | None = None
) -> Path | None:
    """
    Fetch one Copernicus DEM GLO-90 tile.

    :param cache_dir: Directory of the download cache.
    :param lat_floor: Southern edge latitude of the tile.
    :param lon_floor: Western edge longitude of the tile.
    :param client: Optional HTTP client to reuse across tiles.

    :returns path: The GeoTIFF, or None for an all-sea tile that does not exist.
    """
    lat, lon = dem_tile_name(lat_floor, lon_floor)
    url = COPERNICUS_DEM_URL.format(lat=lat, lon=lon)
    return download_file(url, cache_dir / "dem" / f"dem_{lat}_{lon}.tif", client=client)


def reverse_geocode(lat: float, lon: float, client: httpx.Client | None = None) -> str | None:
    """
    Name the locality and county around a point with OpenStreetMap Nominatim.

    :param lat: Latitude.
    :param lon: Longitude.
    :param client: Optional HTTP client to reuse.

    :returns name: Such as `"Topolog, Tulcea"`, or None when the lookup fails.
    """
    return reverse_geocode_place(lat, lon, client)[0]


def reverse_geocode_place(
    lat: float, lon: float, client: httpx.Client | None = None
) -> tuple[str | None, str | None]:
    """
    Name the locality and county around a point and report its country.

    :param lat: Latitude.
    :param lon: Longitude.
    :param client: Optional HTTP client to reuse.

    :returns place: The name such as `"Topolog, Tulcea"` and the lower-case ISO country code
        such as `"ro"`; None for what the lookup could not tell.
    """
    params: dict[str, str | float] = {
        "lat": lat,
        "lon": lon,
        "format": "jsonv2",
        "zoom": 12,
        "accept-language": "ro",
    }
    headers = {"User-Agent": _USER_AGENT}
    try:
        if client is not None:
            resp = client.get(_NOMINATIM_URL, params=params, headers=headers)
        else:
            resp = httpx.get(_NOMINATIM_URL, params=params, headers=headers, timeout=30.0)
        resp.raise_for_status()
        address = resp.json().get("address", {})
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Nominatim lookup failed for %.3f,%.3f: %s", lat, lon, exc)
        return None, None
    place = next(
        (address[k] for k in ("village", "town", "city", "municipality", "hamlet") if k in address),
        None,
    )
    county = address.get("county")
    parts = [p for p in (place, county) if p]
    return (", ".join(parts) if parts else None), address.get("country_code")


__all__ = [
    "reverse_geocode_place",
    "dem_tile_name",
    "download_file",
    "fetch_dem_tile",
    "fetch_gwa_wind_speed",
    "fetch_nasa_power",
    "reverse_geocode",
]
