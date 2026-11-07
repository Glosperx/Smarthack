"""
# Maintenance job schemas

Data transfer models and summary containers for scheduled turbine maintenance evaluations.

The following can be imported from this module:
- `PredictionRow`
- `RunSummary`
"""

from dataclasses import dataclass, field
import datetime
import math

from pydantic import BaseModel, Field, field_validator


class PredictionRow(BaseModel):
    """
    Validated turbine diagnostic record ready for upsert into database.
    """

    turbine_id: int = Field(description="Unique numeric turbine identifier.")
    predicted_date: datetime.date = Field(description="Calendar date of the prediction.")
    daily_fault_probability: float = Field(
        ge=0.0, le=1.0, description="Probability of breakdown within 24 hours."
    )
    cumulative_fault_probability: float = Field(
        ge=0.0, le=1.0, description="Projected cumulative risk probability."
    )
    status: str = Field(description="Health status label (e.g. NORMAL, WATCH, WARNING, CRITICAL).")
    suspected_subsystem: str = Field(
        description="Primary diagnosed failing subsystem, or 'none' if normal."
    )
    health_score: float | None = Field(default=None, description="Physical health score 0-100.")
    estimated_days_to_failure: float | None = Field(
        default=None, description="Estimated days before component breakdown."
    )
    anomalous_sensors: list[str] | None = Field(
        default=None, description="Sensors violating physical limits."
    )
    summary_text: str | None = Field(default=None, description="Diagnostic human-readable summary.")

    @field_validator("health_score", "estimated_days_to_failure")
    @classmethod
    def _finite_or_none(cls, v: float | None) -> float | None:
        """Reject non-finite floats (NaN/Inf) which cannot be serialized to valid JSON."""
        return v if v is None or math.isfinite(v) else None


@dataclass
class RunSummary:
    """
    Diagnostic execution summary reporting performance and outcome statistics of a run cycle.
    """

    day: datetime.date
    total: int = 0
    written: int = 0
    failed: int = 0
    no_data: int = 0
    duration_s: float = 0.0
    by_status: dict[str, int] = field(default_factory=dict)


__all__ = ["PredictionRow", "RunSummary"]
