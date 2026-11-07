"""
# Schemas

Data contracts and transfer objects for the API, built with Pydantic.
These define the schema of requests and responses exposed via OpenAPI.

The following can be imported from this module:
- `AlertChannel`
- `CrewStatus`
- `DispatchDecision`
- `ExampleResult`
- `FleetSweepReport`
- `MaintenanceCrew`
- `ParkSweepResult`
- `SimulateDispatchRequest`
- `TurbineHealthTriage`
- `TurbineInfo`
"""

from smarthack.schemas.dispatch import (
    AlertChannel,
    CrewStatus,
    DispatchDecision,
    FleetSweepReport,
    MaintenanceCrew,
    ParkSweepResult,
    SimulateDispatchRequest,
    TurbineHealthTriage,
    TurbineInfo,
)
from smarthack.schemas.example import ExampleResult

__all__ = [
    "AlertChannel",
    "CrewStatus",
    "DispatchDecision",
    "ExampleResult",
    "FleetSweepReport",
    "MaintenanceCrew",
    "ParkSweepResult",
    "SimulateDispatchRequest",
    "TurbineHealthTriage",
    "TurbineInfo",
]
