"""
# Road geometry

Distances, the tightest horizontal curve of a road, and line simplification. Coordinates
are projected to local metres (equirectangular around the road's own latitude), which is
exact to well under 1 % over the length of one road.

The following can be imported from this module:
- `length_m`
- `min_curve_radius_m`
- `simplify_indices`
- `tight_segments`
- `vertex_curve_radii_m`
"""

import math

import numpy as np

_EARTH_RADIUS_M = 6_371_000.0


def _local_xy(lats: np.ndarray, lons: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Project WGS84 degrees to metres on a plane tangent at the mean latitude.

    :param lats: Latitudes in degrees.
    :param lons: Longitudes in degrees.

    :returns xy: Eastings and northings in metres.
    """
    lat0 = math.radians(float(np.mean(lats)))
    x = np.radians(lons) * _EARTH_RADIUS_M * math.cos(lat0)
    y = np.radians(lats) * _EARTH_RADIUS_M
    return x, y


def length_m(lats: np.ndarray, lons: np.ndarray) -> float:
    """
    Return the length of a polyline.

    :param lats: Latitudes in degrees, one per vertex.
    :param lons: Longitudes in degrees, one per vertex.

    :returns metres: Sum of the segment lengths; 0 for fewer than two vertices.
    """
    if len(lats) < 2:
        return 0.0
    x, y = _local_xy(lats, lons)
    return float(np.hypot(np.diff(x), np.diff(y)).sum())


def vertex_curve_radii_m(
    lats: np.ndarray, lons: np.ndarray, half_window_m: float
) -> tuple[np.ndarray, np.ndarray]:
    """
    Return the curve radius at every vertex of a polyline, and the vertices' arc positions.

    At each vertex the radius is that of the circle through the points `half_window_m`
    before and after it along the line, and the vertex itself. Measuring over a fixed arc
    rather than between neighbouring vertices keeps OSM digitising noise (vertices a metre
    apart with a small kink) from reading as a hairpin. Vertices closer than
    `half_window_m` to an end get `inf`.

    :param lats: Latitudes in degrees.
    :param lons: Longitudes in degrees.
    :param half_window_m: Arc length on each side of a vertex.

    :returns radii_and_positions: Radius per vertex in metres, and distance of each vertex
        from the start of the line in metres.
    """
    n = len(lats)
    if n < 2:
        return np.full(n, np.inf), np.zeros(n)
    x, y = _local_xy(lats, lons)
    s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    radii = np.full(n, np.inf)
    inner = (s >= half_window_m) & (s <= s[-1] - half_window_m)
    if n < 3 or not inner.any():
        return radii, s
    sb, sf = s[inner] - half_window_m, s[inner] + half_window_m
    ax, ay = np.interp(sb, s, x), np.interp(sb, s, y)
    bx, by = x[inner], y[inner]
    cx, cy = np.interp(sf, s, x), np.interp(sf, s, y)
    a = np.hypot(bx - cx, by - cy)
    b = np.hypot(ax - cx, ay - cy)
    c = np.hypot(ax - bx, ay - by)
    twice_area = np.abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay))
    with np.errstate(divide="ignore", invalid="ignore"):
        radii[inner] = np.where(twice_area > 1e-9, a * b * c / (2.0 * twice_area), np.inf)
    return radii, s


def tight_segments(
    lats: np.ndarray,
    lons: np.ndarray,
    min_radius_m: float,
    half_window_m: float,
) -> np.ndarray:
    """
    Mark the segments of a polyline that lie on a curve tighter than `min_radius_m`.

    A segment is marked when either of its vertices is within `half_window_m` (along the
    line) of a vertex whose radius is below the limit, so the mark covers the curve itself
    and not the whole road.

    :param lats: Latitudes in degrees.
    :param lons: Longitudes in degrees.
    :param min_radius_m: Radius below which a curve is tight.
    :param half_window_m: Arc length of the radius window, and of the mark around a curve.

    :returns marks: One boolean per segment (`len(lats) - 1` of them).
    """
    radii, s = vertex_curve_radii_m(lats, lons, half_window_m)
    n = len(lats)
    if n < 2:
        return np.zeros(0, dtype=bool)
    tight_at = s[radii < min_radius_m]
    if tight_at.size == 0:
        return np.zeros(n - 1, dtype=bool)
    # Distance of every vertex to its nearest tight vertex, along the line.
    idx = np.clip(np.searchsorted(tight_at, s), 1, tight_at.size) - 1
    nearest = np.minimum(
        np.abs(s - tight_at[idx]), np.abs(s - tight_at[np.minimum(idx + 1, tight_at.size - 1)])
    )
    near = nearest <= half_window_m
    marks: np.ndarray = near[:-1] | near[1:]
    return marks


def min_curve_radius_m(lats: np.ndarray, lons: np.ndarray, half_window_m: float) -> float:
    """
    Return the radius of the tightest curve along a polyline.

    :param lats: Latitudes in degrees.
    :param lons: Longitudes in degrees.
    :param half_window_m: Arc length on each side of a vertex (see `vertex_curve_radii_m`).

    :returns metres: The smallest radius found, or `math.inf` when the line is too short
        or straight.
    """
    radii, _ = vertex_curve_radii_m(lats, lons, half_window_m)
    return float(np.min(radii)) if radii.size else math.inf


def simplify_indices(lats: np.ndarray, lons: np.ndarray, tolerance_deg: float) -> list[int]:
    """
    Douglas-Peucker simplification, in degrees (longitude scaled by cos latitude).

    :param lats: Latitudes in degrees.
    :param lons: Longitudes in degrees.
    :param tolerance_deg: Largest allowed deviation of a dropped vertex.

    :returns indices: Sorted indices of the vertices to keep; always the two ends.
    """
    n = len(lats)
    if n <= 2:
        return list(range(n))
    scale = math.cos(math.radians(float(np.mean(lats))))
    px, py = np.asarray(lons) * scale, np.asarray(lats)
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j - i < 2:
            continue
        dx, dy = px[j] - px[i], py[j] - py[i]
        seg = math.hypot(dx, dy)
        mx, my = px[i + 1 : j] - px[i], py[i + 1 : j] - py[i]
        if seg == 0.0:
            dist = np.hypot(mx, my)
        else:
            dist = np.abs(mx * dy - my * dx) / seg
        k = int(np.argmax(dist))
        if dist[k] > tolerance_deg:
            mid = i + 1 + k
            keep[mid] = True
            stack.append((i, mid))
            stack.append((mid, j))
    return [int(i) for i in np.flatnonzero(keep)]


__all__ = [
    "length_m",
    "min_curve_radius_m",
    "simplify_indices",
    "tight_segments",
    "vertex_curve_radii_m",
]
