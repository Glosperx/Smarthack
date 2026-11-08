"""
# OpenStreetMap road reader

Reads the roads of an OSM `.pbf` extract that matter for oversize transport (classes in
`constants.ROAD_CLASSES` and their ramps), classifies each from its tags (`rules`) and
its tightest curve (`geometry`), and returns them with their full geometry.

`osmium` comes with the `transport` extra and is imported inside `read_roads`, so this
module imports without it.

The following can be imported from this module:
- `extract_timestamp`
- `read_roads`
- `roads_from_way`
"""

from collections.abc import Callable
from datetime import datetime
import logging
from pathlib import Path
from typing import Any

import numpy as np

from smarthack.transport import constants as C
from smarthack.transport.geometry import tight_segments
from smarthack.transport.network import Road
from smarthack.transport.rules import classify_tags

logger = logging.getLogger(__name__)

#: The tags the rules read; copying only these keeps the per-way cost low.
_TAG_KEYS = (
    "highway",
    "ref",
    "maxheight",
    "maxheight:physical",
    "maxwidth",
    "maxwidth:physical",
    "maxweight",
    "maxweightrating",
    "maxlength",
    "hgv",
    "motor_vehicle",
    "access",
    "bridge",
    "tunnel",
    "junction",
    "width",
    "est_width",
    "lanes",
    "oneway",
    "surface",
)

_CLASS_INDEX = {name: i for i, name in enumerate(C.ROAD_CLASSES)}


def roads_from_way(
    tags: dict[str, str], nodes: list[int], lats: list[float], lons: list[float]
) -> list[Road]:
    """
    Classify one way into roads: the way itself, cut around its tight curves.

    A tight curve is a local obstacle, so only the ~30 m around it carries the curve
    reason; the rest of the way keeps the reasons of its tags alone. The pieces share
    their end nodes, so the network stays connected.

    :param tags: The way's tags (only `_TAG_KEYS`).
    :param nodes: OSM node ids, in order.
    :param lats: Node latitudes.
    :param lons: Node longitudes.

    :returns roads: The classified pieces; empty when the way is not a kept road class.
    """
    road_class = _CLASS_INDEX.get(tags.get("highway", "").removesuffix("_link"))
    if road_class is None or len(nodes) < 2:
        return []
    reasons = classify_tags(tags)
    ref = tags.get("ref", "")
    if reasons & 256:  # a roundabout is flagged as such; its curve says nothing more
        return [Road(road_class, reasons, ref, nodes, lats, lons)]
    marks = tight_segments(
        np.asarray(lats), np.asarray(lons), C.CURVE_MIN_RADIUS_M, C.CURVE_HALF_WINDOW_M
    )
    pieces: list[Road] = []
    start = 0
    for seg in range(1, len(marks) + 1):
        if seg == len(marks) or marks[seg] != marks[start]:
            flag = 128 if marks[start] else 0
            end = seg + 1  # vertices start..seg, both included
            pieces.append(
                Road(
                    road_class,
                    reasons | flag,
                    ref,
                    nodes[start:end],
                    lats[start:end],
                    lons[start:end],
                )
            )
            start = seg
    return pieces


def read_roads(pbf: Path, progress: Callable[[int], None] | None = None) -> list[Road]:
    """
    Read and classify every kept road of an OSM extract.

    :param pbf: Path of the `.osm.pbf` file.
    :param progress: Optional callback receiving the number of roads read so far.

    :returns roads: Classified roads with full-resolution geometry.
    :raises ModuleNotFoundError: When the `transport` extra (osmium) is not installed.
    """
    # Heavy, optional, C++-backed: imported here so the package imports without it.
    import osmium

    roads: list[Road] = []

    class _Handler(osmium.SimpleHandler):
        """Collects highway ways of the kept classes, with node locations."""

        def way(self, w: Any) -> None:
            """
            Copy one way out of osmium (its objects die with the callback) and classify it.

            :param w: The osmium way.
            """
            highway = w.tags.get("highway")
            if highway is None or highway.removesuffix("_link") not in _CLASS_INDEX:
                return
            nodes: list[int] = []
            lats: list[float] = []
            lons: list[float] = []
            for n in w.nodes:
                if not n.location.valid():
                    continue
                nodes.append(n.ref)
                lats.append(n.location.lat)
                lons.append(n.location.lon)
            tags = {k: w.tags[k] for k in _TAG_KEYS if k in w.tags}
            before = len(roads) // 50_000
            roads.extend(roads_from_way(tags, nodes, lats, lons))
            if progress is not None and len(roads) // 50_000 > before:
                progress(len(roads))

    handler = _Handler()
    # No tag filter: it would also drop the untagged nodes the locations come from.
    handler.apply_file(str(pbf), locations=True)
    logger.info("Read %d roads from %s", len(roads), pbf.name)
    return roads


def extract_timestamp(pbf: Path) -> datetime | None:
    """
    Return the replication timestamp written in an OSM extract's header.

    :param pbf: Path of the `.osm.pbf` file.

    :returns when: The extract's data date, or None when the header has none.
    """
    import osmium

    reader = osmium.io.Reader(str(pbf), osmium.osm.osm_entity_bits.NOTHING)
    try:
        raw = reader.header().get("osmosis_replication_timestamp")
    finally:
        reader.close()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


__all__ = ["extract_timestamp", "read_roads", "roads_from_way"]
