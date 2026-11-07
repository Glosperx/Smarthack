"""
# Wind forecast job schemas

Rows of `public.park_wind_forecast` and the summary of one refresh of that table.

The following can be imported from this module:
- `ForecastRunSummary`
- `WindForecastRow`
"""

from dataclasses import dataclass
import datetime
import math

from pydantic import BaseModel, Field, field_validator


class WindForecastRow(BaseModel):
    """
    One forecast hour for one park, ready to be written to `park_wind_forecast`.
    """

    park_id: int = Field(description="Wind park identifier.")
    forecast_time: datetime.datetime = Field(description="Start of the forecast hour, UTC.")
    wind_speed_10m: float | None = Field(default=None, description="Wind speed at 10 m, m/s.")
    wind_speed_100m: float | None = Field(default=None, description="Wind speed at 100 m, m/s.")
    wind_direction_10m: float | None = Field(default=None, description="Direction at 10 m, deg.")
    wind_direction_100m: float | None = Field(default=None, description="Direction at 100 m, deg.")
    wind_gusts_10m: float | None = Field(default=None, description="Gusts at 10 m, m/s.")
    temperature_2m: float | None = Field(default=None, description="Air temperature, Celsius.")
    relative_humidity_2m: float | None = Field(default=None, description="Relative humidity, %.")
    dew_point_2m: float | None = Field(default=None, description="Dew point, Celsius.")
    surface_pressure: float | None = Field(default=None, description="Surface pressure, hPa.")
    fetched_at: datetime.datetime = Field(description="When the refresh that fetched it ran.")

    @field_validator(
        "wind_speed_10m",
        "wind_speed_100m",
        "wind_direction_10m",
        "wind_direction_100m",
        "wind_gusts_10m",
        "temperature_2m",
        "relative_humidity_2m",
        "dew_point_2m",
        "surface_pressure",
    )
    @classmethod
    def _finite_or_none(cls, v: float | None) -> float | None:
        """Reject non-finite floats (NaN/Inf) which cannot be serialized to valid JSON."""
        return v if v is None or math.isfinite(v) else None


@dataclass
class ForecastRunSummary:
    """
    Outcome of one refresh: how many parks were asked for and how many rows were written.
    """

    parks: int = 0
    rows: int = 0
    written: int = 0
    duration_s: float = 0.0


__all__ = ["ForecastRunSummary", "WindForecastRow"]
