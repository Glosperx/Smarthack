"""
# Unit tests for fleet registry and telemetry service

Validates fleet asset inventory, park-level grouping, and health evaluations.
"""

import pytest

from smarthack.services.fleet_service import FleetService, get_default_fleet_service


def test_fleet_service_inventory() -> None:
    """Verify fleet registry inventory and park grouping."""
    svc = FleetService()
    turbines = svc.get_all_turbines()
    assert len(turbines) >= 5

    parks = svc.get_all_parks()
    assert "wind_farm_a" in parks
    assert "wind_farm_b" in parks

    park_a_turbines = svc.get_turbines_for_park("wind_farm_a")
    assert len(park_a_turbines) == 3
    assert all(t.park_id == "wind_farm_a" for t in park_a_turbines)

    assert svc.get_turbine_info(0) is not None
    assert svc.get_turbine_info(999) is None


def test_assess_turbine_normal_and_scenario() -> None:
    """Verify turbine assessment with normal telemetry and injected scenario."""
    svc = FleetService()

    # Normal assessment
    triage_normal = svc.assess_turbine(turbine_id=0)
    assert triage_normal.turbine_id == 0
    assert triage_normal.park_id == "wind_farm_a"
    assert triage_normal.health_status in ("NORMAL", "WATCH", "WARNING", "CRITICAL")

    # Injected failure scenario
    triage_fault = svc.assess_turbine(turbine_id=0, simulated_scenario="bearing_overheating")
    assert triage_fault.health_status in ("WARNING", "CRITICAL")
    assert triage_fault.fault_probability > 0.5
    assert triage_fault.needs_repair is True

    # Non-existent turbine raises KeyError
    with pytest.raises(KeyError):
        svc.assess_turbine(turbine_id=999)


def test_scan_park_and_all_parks() -> None:
    """Verify batch scanning of a single park and all parks."""
    svc = FleetService()

    park_a_triage = svc.scan_park("wind_farm_a", scenarios={0: "bearing_overheating"})
    assert len(park_a_triage) == 3
    t0 = next(t for t in park_a_triage if t.turbine_id == 0)
    assert t0.needs_repair is True

    all_parks = svc.scan_all_parks()
    assert "wind_farm_a" in all_parks
    assert "wind_farm_b" in all_parks


def test_fleet_service_singleton() -> None:
    """Verify singleton accessor."""
    s1 = get_default_fleet_service()
    s2 = get_default_fleet_service()
    assert s1 is s2
