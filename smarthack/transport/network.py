"""
# Oversize transport network

Turns classified roads into a verdict per road and a compact network to draw.

A road's own reasons (see `rules`) say whether it is clear, to check or blocked. Whether
it is *usable* also depends on the way to it: a clear road that no port reaches without a
blocked road is no use. So the roads that are not blocked are joined into a graph at their
shared OSM nodes, and the ports seed it:

- **blocked**: the road itself has a blocking reason;
- **isolated**: not blocked, but no port reaches it without crossing a blocked road;
- **viable**: reached from a port, and nothing known against the road itself;
- **conditional**: reached from a port, with something to check on the road itself.

The verdict is per road, not per route: a viable road may be reached only through
conditional ones. Those show on the map as amber pieces on the way, which is the point.

The following can be imported from this module:
- `Road`
- `assign_verdicts`
- `merge_chains`
"""

from dataclasses import dataclass, field
import math

import numpy as np

from smarthack.transport import constants as C


@dataclass
class Road:
    """One OSM way kept for the network, with its full-resolution geometry."""

    road_class: int
    reasons: int
    ref: str
    nodes: list[int]
    lats: list[float]
    lons: list[float]
    verdict: int = field(default=C.VERDICT_CONDITIONAL)


class _UnionFind:
    """Disjoint sets over node indices, with path halving."""

    def __init__(self, n: int) -> None:
        """
        Start with every node in its own set.

        :param n: Number of nodes.
        """
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        """
        Return the representative of a node's set.

        :param i: Node index.

        :returns root: Index of the set's representative.
        """
        parent = self.parent
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        """
        Join the sets of two nodes.

        :param a: Node index.
        :param b: Node index.
        """
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def _port_seeds(
    lats: np.ndarray,
    lons: np.ndarray,
    member: np.ndarray,
    uf: _UnionFind,
    ports: tuple[tuple[str, float, float], ...],
    radius_m: float,
) -> set[int]:
    """
    Return the roots of every component with a node near a port.

    :param lats: Node latitudes.
    :param lons: Node longitudes.
    :param member: Which nodes belong to this graph.
    :param uf: The graph's union-find.
    :param ports: `(name, lat, lon)` of each port.
    :param radius_m: Snap radius around a port.

    :returns roots: Representatives of the components reachable from a port.
    """
    roots: set[int] = set()
    for _, plat, plon in ports:
        dy = np.radians(lats - plat) * 6_371_000.0
        dx = np.radians(lons - plon) * 6_371_000.0 * math.cos(math.radians(plat))
        near = np.flatnonzero(member & (np.hypot(dx, dy) <= radius_m))
        roots.update(uf.find(int(i)) for i in near)
    return roots


def assign_verdicts(
    roads: list[Road],
    ports: tuple[tuple[str, float, float], ...] = C.PORTS,
    radius_m: float = C.PORT_SNAP_RADIUS_M,
) -> None:
    """
    Set the `verdict` of every road, in place.

    :param roads: Classified roads.
    :param ports: `(name, lat, lon)` of each entry port.
    :param radius_m: A port connects to every node within this distance.
    """
    index: dict[int, int] = {}
    node_lat: list[float] = []
    node_lon: list[float] = []
    for road in roads:
        for nid, lat, lon in zip(road.nodes, road.lats, road.lons):
            if nid not in index:
                index[nid] = len(node_lat)
                node_lat.append(lat)
                node_lon.append(lon)
    n = len(node_lat)
    passable = _UnionFind(n)
    in_passable = np.zeros(n, dtype=bool)
    for road in roads:
        if road.reasons & C.REASONS_BLOCKING:
            continue
        ids = [index[nid] for nid in road.nodes]
        for a, b in zip(ids, ids[1:]):
            passable.union(a, b)
        in_passable[ids] = True

    lats, lons = np.asarray(node_lat), np.asarray(node_lon)
    reached = _port_seeds(lats, lons, in_passable, passable, ports, radius_m)

    for road in roads:
        if road.reasons & C.REASONS_BLOCKING:
            road.verdict = C.VERDICT_BLOCKED
        elif passable.find(index[road.nodes[0]]) not in reached:
            road.verdict = C.VERDICT_ISOLATED
        elif road.reasons == 0:
            road.verdict = C.VERDICT_VIABLE
        else:
            road.verdict = C.VERDICT_CONDITIONAL


def merge_chains(roads: list[Road]) -> list[Road]:
    """
    Join roads that continue each other with the same class, reasons, ref and verdict.

    OSM splits a road at every junction and tag change; drawing tens of thousands of short
    pieces is slow and the pieces say nothing more. Two roads are joined at a node only
    when they are the only two roads of their kind ending there.

    :param roads: Roads with verdicts.

    :returns roads: Fewer, longer roads; the input is not modified.
    """
    groups: dict[tuple[int, int, str, int], list[int]] = {}
    for i, r in enumerate(roads):
        groups.setdefault((r.road_class, r.reasons, r.ref, r.verdict), []).append(i)

    merged: list[Road] = []
    for members in groups.values():
        ends: dict[int, list[int]] = {}
        for i in members:
            for nid in (roads[i].nodes[0], roads[i].nodes[-1]):
                ends.setdefault(nid, []).append(i)
        used: set[int] = set()

        def partner(node: int, current: int) -> int | None:
            """The single other unused road of the group ending at `node`, if any."""
            at = ends.get(node, [])
            if len(at) != 2:
                return None
            other = at[0] if at[1] == current else at[1]
            return None if other in used or other == current else other

        for i in members:
            if i in used:
                continue
            used.add(i)
            base = roads[i]
            nodes, lats, lons = list(base.nodes), list(base.lats), list(base.lons)
            for forward in (True, False):
                current = i
                while True:
                    tip = nodes[-1] if forward else nodes[0]
                    nxt = partner(tip, current)
                    if nxt is None:
                        break
                    used.add(nxt)
                    r = roads[nxt]
                    rn, rla, rlo = r.nodes, r.lats, r.lons
                    if (rn[0] == tip) != forward:  # orient the piece to continue the chain
                        rn, rla, rlo = rn[::-1], rla[::-1], rlo[::-1]
                    if forward:
                        nodes += rn[1:]
                        lats += rla[1:]
                        lons += rlo[1:]
                    else:
                        nodes = rn[:-1] + nodes
                        lats = rla[:-1] + lats
                        lons = rlo[:-1] + lons
                    current = nxt
            merged.append(
                Road(base.road_class, base.reasons, base.ref, nodes, lats, lons, base.verdict)
            )
    return merged


__all__ = ["Road", "assign_verdicts", "merge_chains"]
