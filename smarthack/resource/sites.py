"""
# Candidate wind park sites

Ranks the hill terrain by forecast wind over a park-sized window and proposes the best
sites, kept apart so the list covers several regions instead of one ridge many times.

The following can be imported from this module:
- `CandidateSite`
- `select_sites`
"""

from dataclasses import dataclass

import numpy as np

from smarthack.resource.grid import AnalysisGrid, box_mean

#: Mean Earth radius in kilometres.
_EARTH_RADIUS_KM = 6371.0


@dataclass
class CandidateSite:
    """A proposed site: the centre of the best park-sized window in its area."""

    rank: int
    row: int
    col: int
    latitude: float
    longitude: float
    window_wind: float
    valid_fraction: float


def _haversine_km(lat1: float, lon1: float, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Great-circle distance from one point to many, in kilometres."""
    p1, p2 = np.radians(lat1), np.radians(lats)
    dphi = p2 - p1
    dlmb = np.radians(lons - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return np.asarray(2 * _EARTH_RADIUS_KM * np.arcsin(np.sqrt(a)))


def select_sites(
    wind: np.ndarray,
    grid: AnalysisGrid,
    window: tuple[int, int],
    min_valid_fraction: float,
    min_separation_km: float,
    count: int,
) -> list[CandidateSite]:
    """
    Pick the best park-sized windows of eligible terrain, greedily, kept apart.

    `wind` is NaN wherever a turbine cannot go (outside the hill band, too steep, outside
    the country). Each cell is scored by the mean wind of its window, counted only when
    enough of the window is eligible. The best cell is taken, everything within the
    separation radius is removed, and so on.

    :param wind: `[ny, nx]` forecast wind, NaN where ineligible.
    :param grid: The grid `wind` lives on.
    :param window: Window width and height in cells.
    :param min_valid_fraction: Share of the window that must be eligible.
    :param min_separation_km: Minimum distance between two sites.
    :param count: How many sites to return at most.

    :returns sites: Sites in rank order, best first.
    """
    score, fraction = box_mean(wind, window)
    ok = np.isfinite(score) & (fraction >= min_valid_fraction) & np.isfinite(wind)
    rows, cols = np.nonzero(ok)
    if rows.size == 0:
        return []
    values = score[rows, cols]
    order = np.argsort(-values)
    rows, cols, values = rows[order], cols[order], values[order]
    lons_c, lats_c = grid.centers()
    lats, lons = lats_c[rows], lons_c[cols]
    alive = np.ones(rows.size, dtype=bool)

    sites: list[CandidateSite] = []
    idx = 0
    while len(sites) < count:
        remaining = np.flatnonzero(alive[idx:])
        if remaining.size == 0:
            break
        idx += int(remaining[0])
        r, c = int(rows[idx]), int(cols[idx])
        sites.append(
            CandidateSite(
                rank=len(sites) + 1,
                row=r,
                col=c,
                latitude=float(lats[idx]),
                longitude=float(lons[idx]),
                window_wind=float(values[idx]),
                valid_fraction=float(fraction[r, c]),
            )
        )
        near = _haversine_km(float(lats[idx]), float(lons[idx]), lats, lons) < min_separation_km
        alive &= ~near
    return sites


__all__ = ["CandidateSite", "select_sites"]
