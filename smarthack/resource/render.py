"""
# Heatmap rendering

Colours a wind field with a sequential ramp and writes it as a transparent PNG laid out
in Web Mercator rows, ready for a map image overlay.

The following can be imported from this module:
- `colorize`
- `hex_to_rgb`
- `render_overlay_png`
"""

from io import BytesIO

import numpy as np

from smarthack.resource.grid import AnalysisGrid, mercator_row_index


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    """
    Parse `#rrggbb`.

    :param color: Hex colour.

    :returns rgb: Red, green and blue in 0-255.
    """
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def colorize(
    values: np.ndarray, ramp: tuple[str, ...], vmin: float, vmax: float, alpha: int
) -> np.ndarray:
    """
    Map values to RGBA by linear interpolation along a colour ramp.

    Values are clipped to `[vmin, vmax]`; NaN becomes fully transparent.

    :param values: Field to colour.
    :param ramp: Hex colours from the low to the high end, evenly spaced.
    :param vmin: Value at the first colour.
    :param vmax: Value at the last colour.
    :param alpha: Opacity of defined cells, 0-255.

    :returns rgba: `values.shape + (4,)` array of uint8.
    """
    stops = np.array([hex_to_rgb(c) for c in ramp], dtype=float)
    pos = np.linspace(0.0, 1.0, len(ramp))
    t = np.clip((np.nan_to_num(values, nan=vmin) - vmin) / (vmax - vmin), 0.0, 1.0)
    rgba = np.zeros(values.shape + (4,), dtype=np.uint8)
    for ch in range(3):
        rgba[..., ch] = np.round(np.interp(t, pos, stops[:, ch])).astype(np.uint8)
    defined = np.isfinite(values)
    rgba[..., 3] = np.where(defined, alpha, 0).astype(np.uint8)
    rgba[~defined, :3] = 0
    return rgba


def render_overlay_png(
    values: np.ndarray,
    grid: AnalysisGrid,
    ramp: tuple[str, ...],
    vmin: float,
    vmax: float,
    alpha: int = 215,
) -> bytes:
    """
    Render a grid field as a PNG whose rows are evenly spaced in Web Mercator.

    :param values: `[ny, nx]` field, NaN where nothing should be drawn.
    :param grid: The grid of `values`.
    :param ramp: Sequential hex ramp.
    :param vmin: Value at the light end.
    :param vmax: Value at the dark end.
    :param alpha: Opacity of drawn cells.

    :returns png: Encoded PNG image.
    """
    from PIL import Image

    rows = mercator_row_index(grid)
    rgba = colorize(values[rows, :], ramp, vmin, vmax, alpha)
    buffer = BytesIO()
    Image.fromarray(rgba).save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


__all__ = ["colorize", "hex_to_rgb", "render_overlay_png"]
