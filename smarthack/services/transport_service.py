"""
# Oversize transport network service

Builds the oversize transport network of Romania and serves it.

Building (`build_network`, run by `make transport`):

1. The OpenStreetMap extract of Romania (Geofabrik), cached after the first download.
2. Every motorway, trunk, primary, secondary and tertiary road is classified from its
   tags and its tightest curve for a 2.4-3 MW turbine convoy (`smarthack.transport.rules`).
3. Reachability from the entry ports (Constanța, Galați, Brăila) turns that into a
   verdict per road: viable, conditional, blocked or isolated
   (`smarthack.transport.network`).
4. Continuous pieces are merged and simplified, then written as a gzipped compact JSON
   (`network.json.gz`) next to a `summary.json`.

Network file layout, chosen for size (it holds every major road of the country):
`{"classes": [...], "refs": [...], "roads": [[class, verdict, reasons, ref_index,
[lat, lon, lat, lon, ...]], ...]}`, coordinates rounded to 5 decimals (~1 m).

The following can be imported from this module:
- `NetworkNotBuiltError`
- `build_network`
- `encode_network`
- `load_summary`
- `network_path`
- `summarise`
"""

from datetime import datetime, timezone
import gzip
import json
import logging
from pathlib import Path
from typing import Any

from smarthack import config
from smarthack.clients import transport_sources
from smarthack.schemas.transport import (
    TransportPort,
    TransportReasonStat,
    TransportSource,
    TransportSummary,
    TransportVehicle,
    TransportVerdictStat,
)
from smarthack.transport import constants as C
from smarthack.transport.network import Road, assign_verdicts, merge_chains

logger = logging.getLogger(__name__)

_SUMMARY_FILE = "summary.json"
_NETWORK_FILE = "network.json.gz"

_SOURCES = [
    TransportSource(
        name="OpenStreetMap road network of Romania (Geofabrik extract)",
        url="https://download.geofabrik.de/europe/romania.html",
        license="© OpenStreetMap contributors, ODbL 1.0",
    ),
]

_CAVEATS = [
    "A pre-screening, not a permit: every oversize convoy still needs a special transport "
    "authorisation (AST) from CNAIR, which sets the actual route.",
    "OpenStreetMap rarely tags bridge capacity in Romania. A road with nothing against it "
    "may still have a weak bridge; bridges on secondary and county roads are flagged.",
    "Curves are measured along each road; turns at junctions between two roads are not.",
    "Temporary closures, roadworks and seasonal heavy-traffic bans are not included.",
    "Roads smaller than county roads (the last kilometres to a site) are out of scope.",
]


class NetworkNotBuiltError(FileNotFoundError):
    """The transport network files do not exist yet."""


def _road_km(road: Road) -> float:
    """
    Length of a road in kilometres.

    :param road: A road with full-resolution geometry.

    :returns km: Its length.
    """
    import numpy as np

    from smarthack.transport.geometry import length_m

    return length_m(np.asarray(road.lats), np.asarray(road.lons)) / 1000.0


def summarise(roads: list[Road], extract_date: datetime | None, drawn: int) -> TransportSummary:
    """
    Count the kilometres per verdict and per reason.

    :param roads: Roads with verdicts, before merging.
    :param extract_date: Date of the OSM extract.
    :param drawn: Number of road pieces in the network file.

    :returns summary: The network summary.
    """
    verdict_km = {code: 0.0 for code in C.VERDICT_LABELS}
    reason_km = {bit: 0.0 for bit in C.REASON_LABELS}
    total = 0.0
    for road in roads:
        km = _road_km(road)
        total += km
        verdict_km[road.verdict] += km
        for bit in reason_km:
            if road.reasons & bit:
                reason_km[bit] += km
    return TransportSummary(
        generated_at=datetime.now(timezone.utc),
        osm_extract_date=extract_date,
        vehicle=TransportVehicle(
            description="Worst case of a 2.4-3 MW onshore turbine: 45-55 m blade, "
            "~4.3 m bottom tower section, 70-90 t nacelle",
            length_m=C.VEHICLE_LENGTH_M,
            height_m=C.VEHICLE_HEIGHT_M,
            width_m=C.VEHICLE_WIDTH_M,
            gross_t=C.VEHICLE_GROSS_T,
        ),
        ports=[TransportPort(name=n, latitude=lat, longitude=lon) for n, lat, lon in C.PORTS],
        classes=list(C.ROAD_CLASSES),
        verdicts=[
            TransportVerdictStat(code=code, label=label, km=round(verdict_km[code], 1))
            for code, label in C.VERDICT_LABELS.items()
        ],
        reasons=[
            TransportReasonStat(
                bit=bit,
                label=label,
                blocking=bool(bit & C.REASONS_BLOCKING),
                km=round(reason_km[bit], 1),
            )
            for bit, label in C.REASON_LABELS.items()
        ],
        road_count=drawn,
        total_km=round(total, 1),
        caveats=_CAVEATS,
        sources=_SOURCES,
    )


def encode_network(roads: list[Road], tolerance_deg: float = C.SIMPLIFY_TOLERANCE_DEG) -> dict:
    """
    Simplify and pack merged roads into the compact network layout.

    :param roads: Merged roads with verdicts.
    :param tolerance_deg: Douglas-Peucker tolerance.

    :returns network: The JSON-ready network (see the module docstring).
    """
    import numpy as np

    from smarthack.transport.geometry import simplify_indices

    refs: dict[str, int] = {}
    packed: list[list[Any]] = []
    for road in roads:
        lats, lons = np.asarray(road.lats), np.asarray(road.lons)
        keep = simplify_indices(lats, lons, tolerance_deg)
        coords: list[float] = []
        for i in keep:
            coords.append(round(float(lats[i]), 5))
            coords.append(round(float(lons[i]), 5))
        ref_index = refs.setdefault(road.ref, len(refs)) if road.ref else -1
        packed.append([road.road_class, road.verdict, road.reasons, ref_index, coords])
    return {"classes": list(C.ROAD_CLASSES), "refs": list(refs), "roads": packed}


def build_network(
    cache_dir: Path | None = None,
    out_dir: Path | None = None,
    pbf: Path | None = None,
    refresh: bool = False,
) -> TransportSummary:
    """
    Build the network from OpenStreetMap and write its files.

    :param cache_dir: Download cache, `TRANSPORT_CACHE_DIR` by default.
    :param out_dir: Output directory, `TRANSPORT_NETWORK_DIR` by default.
    :param pbf: An OSM extract to use instead of downloading Romania's.
    :param refresh: Whether to download a fresh extract even when one is cached.

    :returns summary: The summary that was written.
    :raises ModuleNotFoundError: When the `transport` extra (osmium) is not installed.
    """
    from smarthack.transport.osm import extract_timestamp, read_roads

    cache = cache_dir or config.transport_cache_dir()
    out = out_dir or config.transport_network_dir()
    source = pbf or transport_sources.fetch_romania_extract(cache, refresh=refresh)

    logger.info("Reading and classifying roads from %s ...", source)
    roads = read_roads(source, progress=lambda n: logger.info("  %d roads read", n))
    assign_verdicts(roads)
    merged = merge_chains(roads)
    logger.info("Merged %d roads into %d drawn pieces", len(roads), len(merged))

    network = encode_network(merged)
    summary = summarise(roads, extract_timestamp(source), drawn=len(merged))

    out.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(network, separators=(",", ":")).encode("utf-8")
    (out / _NETWORK_FILE).write_bytes(gzip.compress(payload, compresslevel=9, mtime=0))
    (out / _SUMMARY_FILE).write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Wrote %s (%.1f MB uncompressed)", out / _NETWORK_FILE, len(payload) / 1e6)
    return summary


def _network_file(name: str, out_dir: Path | None) -> Path:
    """
    Path of a network file, raising when it has not been built.

    :param name: File name.
    :param out_dir: Network directory, `TRANSPORT_NETWORK_DIR` by default.

    :returns path: The file.
    :raises NetworkNotBuiltError: If the file does not exist.
    """
    path = (out_dir or config.transport_network_dir()) / name
    if not path.is_file():
        raise NetworkNotBuiltError(f"{path} not found: run `make transport` to build it")
    return path


#: Loaded summaries keyed by path and modification time, so a rebuild is picked up.
_cache: dict[tuple[str, float], TransportSummary] = {}


def load_summary(out_dir: Path | None = None) -> TransportSummary:
    """
    Read the network summary.

    :param out_dir: Network directory, `TRANSPORT_NETWORK_DIR` by default.

    :returns summary: Vehicle, ports, kilometres per verdict and reason, sources.
    :raises NetworkNotBuiltError: If the network has not been built.
    """
    path = _network_file(_SUMMARY_FILE, out_dir)
    key = (str(path), path.stat().st_mtime)
    if key not in _cache:
        _cache[key] = TransportSummary.model_validate_json(path.read_text(encoding="utf-8"))
    return _cache[key]


def network_path(out_dir: Path | None = None) -> Path:
    """
    Locate the gzipped network file.

    :param out_dir: Network directory, `TRANSPORT_NETWORK_DIR` by default.

    :returns path: `network.json.gz`.
    :raises NetworkNotBuiltError: If the network has not been built.
    """
    return _network_file(_NETWORK_FILE, out_dir)


__all__ = [
    "NetworkNotBuiltError",
    "build_network",
    "encode_network",
    "load_summary",
    "network_path",
    "summarise",
]
