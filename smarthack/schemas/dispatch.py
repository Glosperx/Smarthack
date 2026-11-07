"""
# Dispatch domain schemas

Pydantic models for wind park assets, maintenance crew tracking, predictive triage,
and autonomous alerting decisions.

The following can be imported from this module:
- `AlertChannel`
- `CrewStatus`
- `DispatchDecision`
- `FleetSweepReport`
- `MaintenanceCrew`
- `ParkSweepResult`
- `SimulateDispatchRequest`
- `TurbineHealthTriage`
- `TurbineInfo`
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AlertChannel(str, Enum):
    """Notification channels selected by the autonomous alerting agent."""

    VOICE_CALL = "VOICE_CALL"
    EMAIL = "EMAIL"
    NONE = "NONE"


class CrewStatus(str, Enum):
    """Operational status of a wind park maintenance crew."""

    AVAILABLE = "AVAILABLE"
    DISPATCHED = "DISPATCHED"
    OFF_SHIFT = "OFF_SHIFT"


class TurbineInfo(BaseModel):
    """
    Metadata for a wind turbine situated in a specific wind park.

    Identifies turbine geographical coordinates and nameplate rated capacity.
    """

    turbine_id: int = Field(description="Unique asset identifier for the turbine.")
    park_id: str = Field(description="Identifier of the wind park containing this turbine.")
    name: str = Field(description="Human-readable turbine name or asset tag.")
    latitude: float = Field(description="Geographic latitude coordinate.")
    longitude: float = Field(description="Geographic longitude coordinate.")
    capacity_kw: float = Field(default=2050.0, description="Rated power output in kilowatts.")


class MaintenanceCrew(BaseModel):
    """
    Field maintenance crew dedicated to a specific wind park.

    Maintains crew contact information, availability status, and component specialties.
    """

    crew_id: str = Field(description="Unique crew identifier.")
    crew_name: str = Field(description="Designation or name of the crew lead.")
    park_id: str = Field(description="Wind park identifier this crew is dedicated to.")
    contact_phone: str = Field(description="Direct phone number for text-to-speech voice calls.")
    contact_email: str = Field(description="Email address for work order tickets.")
    status: CrewStatus = Field(default=CrewStatus.AVAILABLE, description="Current availability.")
    specialties: list[str] = Field(
        default_factory=list,
        description="Technical skills (e.g. Mechanical, Electrical, Hydraulic).",
    )


class TurbineHealthTriage(BaseModel):
    """
    Predictive maintenance health triage item produced by the daily fleet sweep.

    Combines 7-day failure risk, days-to-failure lead time, and power output forecasts.
    """

    turbine_id: int = Field(description="Unique turbine asset identifier.")
    park_id: str = Field(description="Identifier of the wind park containing this turbine.")
    health_status: str = Field(
        description="Assessed health state: NORMAL, WATCH, WARNING, CRITICAL."
    )
    fault_probability: float = Field(
        description="Probability of component fault over the next 7 days."
    )
    days_to_failure: float = Field(
        description="Estimated lead time in days until functional breakdown."
    )
    suspected_failure: str = Field(description="Suspected root cause failure mode or component.")
    subsystem_risks: dict[str, float] = Field(
        default_factory=dict, description="Component-level risk breakdown."
    )
    daily_forecast: list[dict[str, Any]] = Field(
        default_factory=list, description="Day-by-day 7-day risk and probability forecast."
    )
    recommended_action: str = Field(description="Suggested remediation protocol.")
    needs_repair: bool = Field(description="Whether the turbine requires crew intervention.")
    projected_mwh_7d: float | None = Field(
        default=None,
        description="Forecasted 7-day power generation in MWh, populated only if conflict occurs.",
    )
    power_evaluated: bool = Field(
        default=False,
        description="True if the wind power model was invoked to resolve a crew conflict.",
    )


class DispatchDecision(BaseModel):
    """
    Autonomous dispatch and alerting decision determined for a single turbine.

    Specifies the assigned crew, notification modality, priority ranking, and rationale.
    """

    turbine_id: int = Field(description="Turbine asset identifier.")
    park_id: str = Field(description="Wind park identifier.")
    health_status: str = Field(description="Health status evaluated by maintenance model.")
    priority_rank: int = Field(description="Dispatch priority rank within the park (1 = highest).")
    alert_channel: AlertChannel = Field(description="Channel selected: VOICE_CALL, EMAIL, or NONE.")
    assigned_crew_id: str | None = Field(
        default=None, description="Crew assigned to this turbine, or None if deferred."
    )
    assigned_crew_name: str | None = Field(
        default=None, description="Name of the assigned crew lead."
    )
    notification_sent: bool = Field(
        default=False, description="Whether the notification was successfully triggered."
    )
    notification_message: str = Field(
        default="", description="The exact alert text sent to the crew."
    )
    decision_reason: str = Field(
        default="", description="Explanatory rationale for the scheduling and alerting decision."
    )


class ParkSweepResult(BaseModel):
    """
    Operational summary of the daily sweep and triage for a single wind park.
    """

    park_id: str = Field(description="Wind park identifier.")
    turbines_scanned: int = Field(description="Total turbines evaluated in this park.")
    turbines_needing_repair: int = Field(description="Number of turbines with detected issues.")
    crews_available: int = Field(description="Number of active crews available in this park.")
    conflict_detected: bool = Field(
        description="True if repair candidates exceeded available crews in this park."
    )
    power_model_invoked: bool = Field(
        description="True if the wind power model was called to resolve competing candidates."
    )
    decisions: list[DispatchDecision] = Field(
        default_factory=list, description="List of dispatch and alerting decisions for this park."
    )


class SimulateDispatchRequest(BaseModel):
    """
    Request model for triggering a simulated dispatch scenario.
    """

    park_id: str = Field(default="wind_farm_a", description="Wind park identifier.")
    scenarios: dict[int, str] = Field(
        default_factory=dict,
        description="Mapping of turbine asset IDs to simulated failure scenario names.",
    )
    active_crew_count: int | None = Field(
        default=None,
        description="Optional override for active available crews in that park.",
    )


class FleetSweepReport(BaseModel):
    """
    Global report across all wind parks for the autonomous daily sweep.
    """

    timestamp: str = Field(description="ISO timestamp of the sweep execution.")
    total_turbines_scanned: int = Field(description="Total turbines assessed across all parks.")
    total_faults_detected: int = Field(description="Total turbines requiring intervention.")
    critical_alerts_count: int = Field(description="Total emergency TTS voice calls triggered.")
    warning_alerts_count: int = Field(description="Total warning email tickets dispatched.")
    park_results: dict[str, ParkSweepResult] = Field(
        default_factory=dict, description="Detailed results indexed by park identifier."
    )


__all__ = [
    "AlertChannel",
    "CrewStatus",
    "DispatchDecision",
    "FleetSweepReport",
    "MaintenanceCrew",
    "ParkSweepResult",
    "SimulateDispatchRequest",
    "TurbineHealthTriage",
    "TurbineInfo",
]
