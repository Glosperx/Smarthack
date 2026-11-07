"""
# Dispatch and alerting routes

Route handlers for autonomous daily fleet sweeps, crew status tracking, and scenario simulations.

The following can be imported from this module:
- `router`
"""

from typing import Any

from fastapi import APIRouter, Query

from smarthack.clients.crew_client import get_default_crew_client
from smarthack.clients.email_client import get_default_email_client
from smarthack.clients.voice_client import get_default_voice_client
from smarthack.schemas.dispatch import (
    FleetSweepReport,
    MaintenanceCrew,
    ParkSweepResult,
    SimulateDispatchRequest,
)
from smarthack.services.dispatch_service import get_default_dispatch_service

router = APIRouter(prefix="/dispatch", tags=["dispatch"])


@router.post("/daily-sweep", response_model=FleetSweepReport)
def run_daily_sweep(park_id: str | None = Query(default=None)) -> FleetSweepReport:
    """
    Trigger the daily predictive maintenance sweep and autonomous crew dispatching.

    :param park_id: Optional wind park identifier to restrict the sweep.

    :returns report: Comprehensive fleet sweep report with decisions and notification counts.
    """
    dispatch_svc = get_default_dispatch_service()
    return dispatch_svc.run_daily_fleet_sweep(target_park_id=park_id)


@router.get("/crews", response_model=list[MaintenanceCrew])
def list_crews(park_id: str | None = Query(default=None)) -> list[MaintenanceCrew]:
    """
    Retrieve maintenance crews with optional wind park filtering.

    :param park_id: Optional wind park identifier.

    :returns crews: List of matching MaintenanceCrew records.
    """
    crew_client = get_default_crew_client()
    if park_id:
        return crew_client.get_crews_by_park(park_id)
    return crew_client.get_all_crews()


@router.post("/simulate", response_model=ParkSweepResult)
def simulate_scenario(payload: SimulateDispatchRequest) -> ParkSweepResult:
    """
    Run an interactive simulation with injected turbine fault scenarios and crew capacities.

    :param payload: Simulation parameters including park_id, injected scenarios, and crew counts.

    :returns result: ParkSweepResult detailing decisions and whether power model was invoked.
    """
    dispatch_svc = get_default_dispatch_service()
    return dispatch_svc.simulate_dispatch_scenario(
        park_id=payload.park_id,
        failing_turbines_with_scenarios=payload.scenarios,
        active_crew_count=payload.active_crew_count,
    )


@router.get("/notifications/voice", response_model=list[dict[str, Any]])
def get_voice_notifications() -> list[dict[str, Any]]:
    """
    Retrieve the audit log of all emergency text-to-speech voice calls dispatched.

    :returns calls: List of completed voice call records.
    """
    voice_client = get_default_voice_client()
    return voice_client.get_call_history()


@router.get("/notifications/email", response_model=list[dict[str, Any]])
def get_email_notifications() -> list[dict[str, Any]]:
    """
    Retrieve the audit log of all maintenance work order tickets dispatched via email.

    :returns tickets: List of delivered email ticket records.
    """
    email_client = get_default_email_client()
    return email_client.get_email_history()


__all__ = ["router"]
