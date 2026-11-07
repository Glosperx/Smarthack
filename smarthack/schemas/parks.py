"""
# Wind park schema

Data contract for wind park geographic locations and metadata.

The following can be imported from this module:
- `Park`
"""

from pydantic import BaseModel, Field


class Park(BaseModel):
    """
    Wind park geographical coordinates and identification.
    """

    id: int = Field(description="Unique numeric park identifier.")
    latitude: float = Field(ge=-90, le=90, description="WGS84 latitude coordinate.")
    longitude: float = Field(ge=-180, le=180, description="WGS84 longitude coordinate.")


__all__ = ["Park"]
