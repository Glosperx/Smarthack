"""
# Schemas

Data contracts and transfer objects for the API, built with Pydantic.
These define the schema of requests and responses exposed via OpenAPI.

The following can be imported from this module:
- `AlertChannel`
- `CrewStatus`
- `DispatchDecision`
- `ExampleResult`
- `ForecastRunSummary`
- `FleetSweepReport`
- `MaintenanceCrew`
- `Park`
- `ParkSweepResult`
- `ParkTurbines`
- `PredictionRow`
- `RunSummary`
- `SimulateDispatchRequest`
- `TurbineHealthTriage`
- `TurbineInfo`
- `TurbinePrediction`
- `TurbineToday`
- `WindForecastRow`
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
from smarthack.schemas.maintenance import PredictionRow, RunSummary
from smarthack.schemas.parks import Park, ParkTurbines, TurbinePrediction, TurbineToday
from smarthack.schemas.wind_forecast import ForecastRunSummary, WindForecastRow

__all__ = [
    "AlertChannel",
    "CrewStatus",
    "DispatchDecision",
    "ExampleResult",
    "ForecastRunSummary",
    "FleetSweepReport",
    "MaintenanceCrew",
    "Park",
    "ParkSweepResult",
    "ParkTurbines",
    "PredictionRow",
    "RunSummary",
    "SimulateDispatchRequest",
    "TurbineHealthTriage",
    "TurbineInfo",
    "TurbinePrediction",
    "TurbineToday",
    "WindForecastRow",
]
