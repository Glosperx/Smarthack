"""
# Fleet registry and telemetry evaluation service

Service for managing wind park asset inventories, coordinating daily physical telemetry
assessments, and triaging impending turbine failures.

The following can be imported from this module:
- `FleetService`
- `get_default_fleet_service`
"""

import copy
import logging
from typing import Any

from smarthack.maintenance.agent_tool import assess_turbine_health, simulate_turbine_scenario
from smarthack.maintenance.constants import (
    DEFAULT_FORECAST_HORIZON_DAYS,
    HEALTH_STATUS_CRITICAL,
    HEALTH_STATUS_WARNING,
)
from smarthack.schemas.dispatch import TurbineHealthTriage, TurbineInfo

logger = logging.getLogger(__name__)

# Default registered turbines across wind parks
DEFAULT_TURBINES: list[dict[str, Any]] = [
    {
        "turbine_id": 0,
        "park_id": "wind_farm_a",
        "name": "Turbine Alpha-01",
        "latitude": 35.2,
        "longitude": -101.8,
        "capacity_kw": 2050.0,
    },
    {
        "turbine_id": 1,
        "park_id": "wind_farm_a",
        "name": "Turbine Alpha-02",
        "latitude": 35.21,
        "longitude": -101.82,
        "capacity_kw": 2050.0,
    },
    {
        "turbine_id": 2,
        "park_id": "wind_farm_a",
        "name": "Turbine Alpha-03",
        "latitude": 35.19,
        "longitude": -101.79,
        "capacity_kw": 2050.0,
    },
    {
        "turbine_id": 10,
        "park_id": "wind_farm_b",
        "name": "Turbine Beta-01",
        "latitude": 42.5,
        "longitude": -88.5,
        "capacity_kw": 2050.0,
    },
    {
        "turbine_id": 11,
        "park_id": "wind_farm_b",
        "name": "Turbine Beta-02",
        "latitude": 42.52,
        "longitude": -88.48,
        "capacity_kw": 2050.0,
    },
]


class FleetService:
    """
    Fleet registry and health monitoring service.

    Tracks turbine metadata, coordinates telemetry evaluations, and groups health triage
    by wind park.
    """

    def __init__(self, initial_turbines: list[TurbineInfo] | None = None) -> None:
        """
        Initialize the fleet service with a turbine registry.

        :param initial_turbines: Optional custom list of TurbineInfo objects.
        """
        self._turbines: dict[int, TurbineInfo] = {}
        if initial_turbines is not None:
            for t in initial_turbines:
                self._turbines[t.turbine_id] = copy.deepcopy(t)
        else:
            self.reset_fleet()

    def reset_fleet(self) -> None:
        """
        Reset the fleet registry to default seed turbines.
        """
        self._turbines.clear()
        for t_dict in DEFAULT_TURBINES:
            turbine = TurbineInfo.model_validate(t_dict)
            self._turbines[turbine.turbine_id] = turbine

    def get_all_turbines(self) -> list[TurbineInfo]:
        """
        Retrieve all registered wind turbines.

        :returns turbines: List of TurbineInfo instances.
        """
        return list(self._turbines.values())

    def get_turbines_for_park(self, park_id: str) -> list[TurbineInfo]:
        """
        Retrieve all turbines situated within a specific wind park.

        :param park_id: Wind park identifier.

        :returns turbines: List of TurbineInfo instances in that park.
        """
        return [t for t in self._turbines.values() if t.park_id == park_id]

    def get_all_parks(self) -> list[str]:
        """
        Retrieve all unique wind park identifiers.

        :returns parks: Sorted list of unique park identifiers.
        """
        return sorted({t.park_id for t in self._turbines.values()})

    def get_turbine_info(self, turbine_id: int) -> TurbineInfo | None:
        """
        Retrieve metadata for a specific wind turbine.

        :param turbine_id: Asset identifier.

        :returns turbine: TurbineInfo instance or None if not registered.
        """
        return self._turbines.get(turbine_id)

    def assess_turbine(
        self,
        turbine_id: int,
        simulated_scenario: str | None = None,
        horizon_days: int = DEFAULT_FORECAST_HORIZON_DAYS,
    ) -> TurbineHealthTriage:
        """
        Evaluate physical health for a wind turbine over the forecast horizon.

        :param turbine_id: Turbine asset identifier.
        :param simulated_scenario: Optional scenario name (e.g. 'bearing_overheating', 'gearbox_wear').
        :param horizon_days: Forecast window in days (default 7).

        :returns triage: Evaluated TurbineHealthTriage data model.
        :raises KeyError: If the turbine is not registered in the fleet.
        """
        turbine = self.get_turbine_info(turbine_id)
        if turbine is None:
            raise KeyError(f"Turbine ID {turbine_id} is not registered in the fleet.")

        if simulated_scenario:
            health_report = simulate_turbine_scenario(
                scenario=simulated_scenario,
                asset_id=turbine_id,
                horizon_days=horizon_days,
            )
        else:
            health_report = assess_turbine_health(
                asset_id=turbine_id,
                horizon_days=horizon_days,
            )

        status = str(health_report.get("health_status", "NORMAL"))
        fault_prob = float(health_report.get("fault_probability", 0.0))
        days_to_fail = float(health_report.get("days_to_failure", 7.0))
        needs_repair = status in (HEALTH_STATUS_CRITICAL, HEALTH_STATUS_WARNING)

        return TurbineHealthTriage(
            turbine_id=turbine_id,
            park_id=turbine.park_id,
            health_status=status,
            fault_probability=fault_prob,
            days_to_failure=days_to_fail,
            suspected_failure=str(health_report.get("suspected_failure", "None")),
            subsystem_risks=health_report.get("subsystem_risks", {}),
            daily_forecast=health_report.get("daily_forecast", []),
            recommended_action=str(health_report.get("recommended_action", "No action needed.")),
            needs_repair=needs_repair,
            projected_mwh_7d=None,
            power_evaluated=False,
        )

    def scan_park(
        self,
        park_id: str,
        scenarios: dict[int, str] | None = None,
    ) -> list[TurbineHealthTriage]:
        """
        Scan all turbines in a designated wind park.

        :param park_id: Wind park identifier.
        :param scenarios: Optional mapping of turbine_id -> simulated scenario name.

        :returns triage_list: Health assessments for all turbines in the park.
        """
        turbines = self.get_turbines_for_park(park_id)
        results: list[TurbineHealthTriage] = []
        for t in turbines:
            scenario = (scenarios or {}).get(t.turbine_id)
            triage = self.assess_turbine(t.turbine_id, simulated_scenario=scenario)
            results.append(triage)
        return results

    def scan_all_parks(
        self,
        scenarios: dict[int, str] | None = None,
    ) -> dict[str, list[TurbineHealthTriage]]:
        """
        Run the daily physical telemetry sweep across all registered wind parks.

        :param scenarios: Optional mapping of turbine_id -> simulated scenario name.

        :returns park_map: Dictionary mapping park_id to its list of TurbineHealthTriage items.
        """
        report: dict[str, list[TurbineHealthTriage]] = {}
        for park_id in self.get_all_parks():
            report[park_id] = self.scan_park(park_id, scenarios=scenarios)
        return report


_GLOBAL_FLEET_SERVICE: FleetService | None = None


def get_default_fleet_service() -> FleetService:
    """
    Return or initialize the singleton default FleetService instance.

    :returns service: Active FleetService instance.
    """
    global _GLOBAL_FLEET_SERVICE
    if _GLOBAL_FLEET_SERVICE is None:
        _GLOBAL_FLEET_SERVICE = FleetService()
    return _GLOBAL_FLEET_SERVICE


__all__ = ["FleetService", "get_default_fleet_service"]
