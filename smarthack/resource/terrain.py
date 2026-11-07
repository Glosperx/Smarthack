"""
# Terrain derivatives

Slope from a digital elevation model in geographic coordinates, used to keep proposed
sites on terrain where access roads and crane pads can be built.

The following can be imported from this module:
- `slope_degrees`
"""

import numpy as np

from smarthack.resource.grid import GeoRaster

#: Metres per degree of latitude (WGS84 mean).
_M_PER_DEG_LAT = 110_574.0

#: Metres per degree of longitude at the equator.
_M_PER_DEG_LON_EQ = 111_320.0


def slope_degrees(dem: GeoRaster) -> GeoRaster:
    """
    Compute the terrain slope of every DEM pixel.

    Pixel spacing in metres is taken at each row's latitude, so the east-west spacing
    shrinks northwards as it does on the ground.

    :param dem: Elevation raster in metres, north-up, geographic coordinates.

    :returns slope: Raster of the same shape and georeferencing, in degrees.
    """
    rows = dem.data.shape[0]
    lats = dem.lat_max - (np.arange(rows) + 0.5) * dem.dlat
    dy = dem.dlat * _M_PER_DEG_LAT
    dx = dem.dlon * _M_PER_DEG_LON_EQ * np.cos(np.radians(lats))[:, None]
    dz_dy, dz_dx = np.gradient(dem.data.astype(np.float64))
    slope = np.degrees(np.arctan(np.hypot(dz_dx / dx, dz_dy / dy)))
    return GeoRaster(
        data=slope.astype(np.float32),
        lon_min=dem.lon_min,
        lat_max=dem.lat_max,
        dlon=dem.dlon,
        dlat=dem.dlat,
    )


__all__ = ["slope_degrees"]
