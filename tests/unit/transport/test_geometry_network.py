"""Unit tests for road geometry, curve splitting, verdicts and chain merging."""

import math

from tests.conftest import skip_module_without_extra

skip_module_without_extra("transport")

import numpy as np  # noqa: E402

from smarthack.transport import constants as C  # noqa: E402
from smarthack.transport.geometry import (  # noqa: E402
    length_m,
    min_curve_radius_m,
    simplify_indices,
    tight_segments,
)
from smarthack.transport.network import Road, assign_verdicts, merge_chains  # noqa: E402
from smarthack.transport.osm import roads_from_way  # noqa: E402

#: Metres per degree of latitude.
M = 111_195.0


def _arc(radius_m: float, degrees: float, step_deg: float = 2.0) -> tuple[np.ndarray, np.ndarray]:
    """Points on a circular arc of the given radius near 45 N, 25 E."""
    angles = np.radians(np.arange(0.0, degrees + 1e-9, step_deg))
    lat0, lon0 = 45.0, 25.0
    k = math.cos(math.radians(lat0))
    lats = lat0 + radius_m * np.sin(angles) / M
    lons = lon0 + radius_m * (1 - np.cos(angles)) / (M * k)
    return lats, lons


def test_length_of_a_straight_kilometre() -> None:
    """One kilometre north is about 1000 m."""
    lats = np.array([45.0, 45.0 + 1000.0 / M])
    lons = np.array([25.0, 25.0])
    assert length_m(lats, lons) == np.float64(length_m(lats, lons))
    assert abs(length_m(lats, lons) - 1000.0) < 1.0


def test_curve_radius_is_measured() -> None:
    """A 30 m arc reads close to 30 m; a 300 m arc stays well above the limit."""
    assert abs(min_curve_radius_m(*_arc(30.0, 120.0), C.CURVE_HALF_WINDOW_M) - 30.0) < 2.0
    assert min_curve_radius_m(*_arc(300.0, 30.0, 0.5), C.CURVE_HALF_WINDOW_M) > 250.0


def test_straight_line_has_no_curve() -> None:
    """A straight line has an infinite radius and no tight segment."""
    lats = np.linspace(45.0, 45.01, 20)
    lons = np.full(20, 25.0)
    assert math.isinf(min_curve_radius_m(lats, lons, C.CURVE_HALF_WINDOW_M))
    assert not tight_segments(lats, lons, C.CURVE_MIN_RADIUS_M, C.CURVE_HALF_WINDOW_M).any()


def test_simplify_keeps_ends_and_drops_collinear_points() -> None:
    """Collinear interior points go; the two ends always stay."""
    lats = np.linspace(45.0, 45.01, 50)
    lons = np.linspace(25.0, 25.01, 50)
    assert simplify_indices(lats, lons, 1e-6) == [0, 49]


def test_tight_curve_is_cut_out_of_a_long_road() -> None:
    """Only the stretch around a hairpin carries the curve reason, not the whole road."""
    k = math.cos(math.radians(45.0))
    # 500 m straight north, a 20 m hairpin, then 500 m straight back south.
    north = np.linspace(0, 500, 26)
    lats_a, lons_a = 45.0 + north / M, np.full(26, 25.0)
    hl, hn = _arc(20.0, 180.0, 10.0)
    hairpin_lats = lats_a[-1] + (hl - 45.0)
    hairpin_lons = 25.0 + (hn - 25.0)
    south = lats_a[::-1]
    lats = np.concatenate([lats_a, hairpin_lats[1:], south[1:]])
    lons = np.concatenate([lons_a, hairpin_lons[1:], np.full(25, 25.0 + 40.0 / (M * k))])
    nodes = list(range(len(lats)))
    pieces = roads_from_way({"highway": "primary"}, nodes, list(lats), list(lons))
    flagged = [p for p in pieces if p.reasons & 128]
    clear = [p for p in pieces if not p.reasons & 128]
    assert flagged and clear
    flagged_m = sum(length_m(np.asarray(p.lats), np.asarray(p.lons)) for p in flagged)
    assert flagged_m < 200.0
    # Pieces share their end nodes, so the road stays connected.
    for a, b in zip(pieces, pieces[1:]):
        assert a.nodes[-1] == b.nodes[0]


def _road(reasons: int, nodes: list[int], lat0: float = 44.17, lon0: float = 28.64) -> Road:
    """A short road whose node i sits 0.01 deg east of node i-1, starting at (lat0, lon0)."""
    lats = [lat0] * len(nodes)
    lons = [lon0 + 0.01 * (n - nodes[0]) for n in nodes]
    return Road(road_class=2, reasons=reasons, ref="DN", nodes=nodes, lats=lats, lons=lons)


def test_verdicts_from_a_port() -> None:
    """Clear roads near a port are viable; a road behind a blocked one is isolated."""
    port = (("Test port", 44.17, 28.64),)
    clear = _road(0, [1, 2])
    check = _road(512, [2, 3])
    blocked = _road(1, [3, 4])
    behind = _road(0, [4, 5])
    roads = [clear, check, blocked, behind]
    assign_verdicts(roads, ports=port, radius_m=500.0)
    assert [r.verdict for r in roads] == [
        C.VERDICT_VIABLE,
        C.VERDICT_CONDITIONAL,
        C.VERDICT_BLOCKED,
        C.VERDICT_ISOLATED,
    ]


def test_merge_joins_continuations_of_the_same_kind() -> None:
    """Two pieces of the same kind meeting end to end become one; a different kind stays."""
    a = _road(0, [1, 2, 3])
    b = _road(0, [5, 4, 3])  # reversed direction, must be flipped
    c = _road(512, [5, 6])
    for r in (a, b, c):
        r.verdict = C.VERDICT_VIABLE if r.reasons == 0 else C.VERDICT_CONDITIONAL
    merged = merge_chains([a, b, c])
    assert len(merged) == 2
    joined = next(r for r in merged if r.reasons == 0)
    assert joined.nodes in ([1, 2, 3, 4, 5], [5, 4, 3, 2, 1])
