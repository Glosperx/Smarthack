"""
# Unit tests for dispatch orchestration service

Validates fleet-wide sweeps, scenario simulation, and metrics aggregation.
"""

from smarthack.clients.crew_client import get_default_crew_client
from smarthack.services.dispatch_service import DispatchService, get_default_dispatch_service


def test_dispatch_service_sweep() -> None:
    """Verify fleet-wide daily sweep execution."""
    crew_client = get_default_crew_client()
    crew_client.reset_crews()

    svc = DispatchService()
    report = svc.run_daily_fleet_sweep()

    assert report.total_turbines_scanned >= 5
    assert "wind_farm_a" in report.park_results
    assert "wind_farm_b" in report.park_results


def test_dispatch_service_simulate_scenario() -> None:
    """Verify simulation runner with injected scenarios and crew overrides."""
    svc = DispatchService()

    # Incur conflict: 2 failing turbines vs 1 active crew
    result = svc.simulate_dispatch_scenario(
        park_id="wind_farm_a",
        failing_turbines_with_scenarios={
            0: "bearing_overheating",
            1: "hydraulic_leak",
        },
        active_crew_count=1,
    )

    assert result.park_id == "wind_farm_a"
    assert result.turbines_needing_repair == 2
    assert result.crews_available == 1
    assert result.conflict_detected is True
    assert result.power_model_invoked is True
    assert len(result.decisions) == 2


def test_dispatch_service_singleton() -> None:
    """Verify singleton accessor."""
    s1 = get_default_dispatch_service()
    s2 = get_default_dispatch_service()
    assert s1 is s2
