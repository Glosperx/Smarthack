"""
# Dispatch orchestration service

High-level domain service orchestrating daily fleet health sweeps, coordinating
autonomous LangGraph agent execution across wind parks, and compiling fleet reports.

The following can be imported from this module:
- `DispatchService`
- `get_default_dispatch_service`
"""

from datetime import datetime, timezone
import logging

from smarthack.clients.crew_client import get_default_crew_client
from smarthack.schemas.dispatch import (
    AlertChannel,
    CrewStatus,
    DispatchDecision,
    FleetSweepReport,
    ParkSweepResult,
)
from smarthack.services.agent.graph import run_park_dispatch_agent
from smarthack.services.fleet_service import get_default_fleet_service

logger = logging.getLogger(__name__)


class DispatchService:
    """
    Service coordinating fleet-wide predictive maintenance sweeps and autonomous alerting.

    Sweeps wind turbines daily per wind park, detects component anomalies, invokes the
    LangGraph dispatch agent, and returns detailed audit reports.
    """

    def __init__(self) -> None:
        """
        Initialize the dispatch orchestration service.
        """
        self._fleet_svc = get_default_fleet_service()
        self._crew_client = get_default_crew_client()

    def run_daily_fleet_sweep(
        self,
        scenarios: dict[int, str] | None = None,
        target_park_id: str | None = None,
    ) -> FleetSweepReport:
        """
        Execute the daily predictive maintenance sweep across all or specific wind parks.

        :param scenarios: Optional simulation scenario mapping (turbine_id -> scenario_name).
        :param target_park_id: Optional wind park identifier to restrict the sweep.

        :returns report: FleetSweepReport capturing the overall status and per-park decisions.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        parks = [target_park_id] if target_park_id else self._fleet_svc.get_all_parks()

        total_scanned = 0
        total_faults = 0
        critical_alerts = 0
        warning_alerts = 0
        park_results: dict[str, ParkSweepResult] = {}

        for park_id in parks:
            # 1. Daily Health Scan for this park
            triage_items = self._fleet_svc.scan_park(park_id, scenarios=scenarios)
            triage_dicts = [t.model_dump() for t in triage_items]
            failing_items = [t for t in triage_items if t.needs_repair]

            # 2. Count active crews
            crews = self._crew_client.get_crews_by_park(park_id, status=CrewStatus.AVAILABLE)

            # 3. Execute the autonomous LangGraph agent for this park
            agent_result = run_park_dispatch_agent(park_id=park_id, triage_items=triage_dicts)

            raw_decisions = agent_result.get("alert_decisions", [])
            decisions = [DispatchDecision.model_validate(d) for d in raw_decisions]

            # Update metrics
            total_scanned += len(triage_items)
            total_faults += len(failing_items)

            for d in decisions:
                if d.alert_channel == AlertChannel.VOICE_CALL:
                    critical_alerts += 1
                elif d.alert_channel == AlertChannel.EMAIL:
                    warning_alerts += 1

            park_res = ParkSweepResult(
                park_id=park_id,
                turbines_scanned=len(triage_items),
                turbines_needing_repair=len(failing_items),
                crews_available=len(crews),
                conflict_detected=bool(agent_result.get("has_conflict", False)),
                power_model_invoked=bool(agent_result.get("power_model_invoked", False)),
                decisions=decisions,
            )
            park_results[park_id] = park_res

        logger.info(
            "Completed fleet sweep across %d parks. Turbines: %d, Faults: %d, Voice Calls: %d, Emails: %d",
            len(parks),
            total_scanned,
            total_faults,
            critical_alerts,
            warning_alerts,
        )

        return FleetSweepReport(
            timestamp=timestamp,
            total_turbines_scanned=total_scanned,
            total_faults_detected=total_faults,
            critical_alerts_count=critical_alerts,
            warning_alerts_count=warning_alerts,
            park_results=park_results,
        )

    def simulate_dispatch_scenario(
        self,
        park_id: str,
        failing_turbines_with_scenarios: dict[int, str],
        active_crew_count: int | None = None,
    ) -> ParkSweepResult:
        """
        Simulate an arbitrary operational scenario for live demonstrations and tests.

        :param park_id: Wind park identifier.
        :param failing_turbines_with_scenarios: Mapping of turbine_id to scenario name.
        :param active_crew_count: Optional override for the number of available crews.

        :returns result: ParkSweepResult containing the agent's decisions and execution trace.
        """
        self._crew_client.reset_crews()
        if active_crew_count is not None:
            park_crews = self._crew_client.get_crews_by_park(park_id)
            for idx, crew in enumerate(park_crews):
                new_status = (
                    CrewStatus.AVAILABLE if idx < active_crew_count else CrewStatus.OFF_SHIFT
                )
                self._crew_client.update_crew_status(crew.crew_id, new_status)

        fleet_report = self.run_daily_fleet_sweep(
            scenarios=failing_turbines_with_scenarios,
            target_park_id=park_id,
        )
        return fleet_report.park_results[park_id]


_GLOBAL_DISPATCH_SERVICE: DispatchService | None = None


def get_default_dispatch_service() -> DispatchService:
    """
    Return or initialize the singleton default DispatchService instance.

    :returns service: Active DispatchService instance.
    """
    global _GLOBAL_DISPATCH_SERVICE
    if _GLOBAL_DISPATCH_SERVICE is None:
        _GLOBAL_DISPATCH_SERVICE = DispatchService()
    return _GLOBAL_DISPATCH_SERVICE


__all__ = ["DispatchService", "get_default_dispatch_service"]
