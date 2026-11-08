"""
# Oversize transport data sources

Download, with an on-disk cache, of the OpenStreetMap extract of Romania (Geofabrik,
about 330 MB, refreshed daily upstream).

The following can be imported from this module:
- `fetch_romania_extract`
"""

import logging
from pathlib import Path

from smarthack.clients.resource_sources import download_file
from smarthack.transport.constants import GEOFABRIK_ROMANIA_URL

logger = logging.getLogger(__name__)

_EXTRACT_NAME = "romania-latest.osm.pbf"


def fetch_romania_extract(cache_dir: Path, refresh: bool = False) -> Path:
    """
    Return the cached OSM extract of Romania, downloading it when missing.

    :param cache_dir: Directory of the cache.
    :param refresh: Whether to drop the cached copy and download the current one.

    :returns path: The `.osm.pbf` file.
    :raises httpx.HTTPError: When the download fails.
    :raises FileNotFoundError: When Geofabrik has no such file.
    """
    dest = cache_dir / _EXTRACT_NAME
    if refresh and dest.exists():
        dest.unlink()
    if not dest.exists():
        logger.info("Downloading %s (about 330 MB) ...", GEOFABRIK_ROMANIA_URL)
    path = download_file(GEOFABRIK_ROMANIA_URL, dest)
    if path is None:
        raise FileNotFoundError(f"Geofabrik has no extract at {GEOFABRIK_ROMANIA_URL}")
    return path


__all__ = ["fetch_romania_extract"]
