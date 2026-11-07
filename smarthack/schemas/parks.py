"""
# Wind park schemas

Data contracts for wind park geographic locations, turbine assets, and daily predictions.

The following can be imported from this module:
- `Park`
- `ParkTurbines`
- `TurbinePrediction`
- `TurbineToday`
"""

import datetime

from pydantic import BaseModel, Field


class Park(BaseModel):
    """
    Wind park geographical coordinates and identification.
    """

    id: int = Field(description="Unique numeric park identifier.")
    name: str = Field(description="Display name of the wind park.")
    latitude: float = Field(ge=-90, le=90, description="WGS84 latitude coordinate.")
    longitude: float = Field(ge=-180, le=180, description="WGS84 longitude coordinate.")


class TurbinePrediction(BaseModel):
    """
    Single diagnostic maintenance prediction record for a wind turbine.
    """

    entry_id: int = Field(description="Unique prediction database sequence identifier.")
    predicted_date: datetime.date = Field(description="Target forecast date of the prediction.")
    daily_fault_probability: float = Field(description="Probability of failure within 24 hours.")
    cumulative_fault_probability: float = Field(
        description="Multi-day aggregated probability of failure."
    )
    status: str = Field(description="Operational health status code or label.")
    suspected_subsystem: str = Field(description="Primary turbine subsystem at risk.")


class TurbineToday(BaseModel):
    """
    Turbine operational status with today's maintenance prediction if available.
    """

    id: int = Field(description="Unique numeric turbine identifier.")
    prediction: TurbinePrediction | None = Field(
        default=None, description="Diagnostic prediction for today, or None if unavailable."
    )


class ParkTurbines(BaseModel):
    """
    Collection of turbines and today's diagnostics for a specific wind park.
    """

    park_id: int = Field(description="Unique numeric identifier of the parent park.")
    date: datetime.date = Field(
        description="The evaluation date for which predictions were retrieved."
    )
    turbines: list[TurbineToday] = Field(
        default_factory=list, description="Turbines registered under this park."
    )


__all__ = ["Park", "ParkTurbines", "TurbinePrediction", "TurbineToday"]
