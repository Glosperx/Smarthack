"""
# Maintenance service

Orchestrates fleet-wide turbine health evaluation cycles and persistence.

The following can be imported from this module:
- `run_prediction_cycle`
- `scenario_for`
"""

from collections.abc import Awaitable, Callable
from datetime import date
import logging
import time
from typing import Any

import httpx

from smarthack import config
from smarthack.clients import supabase
from smarthack.constants import NO_SUBSYSTEM
from smarthack.maintenance.agent_tool import assess_turbine_health, load_predictor
from smarthack.maintenance.constants import SCENARIO_NORMAL
from smarthack.maintenance.predictor import TurbineHealthPredictor
from smarthack.schemas.maintenance import PredictionRow, RunSummary

logger = logging.getLogger(__name__)


def scenario_for(turbine_id: int) -> str:
    """
    Retrieve configured demo simulation scenario for a specific turbine ID.

    :param turbine_id: Asset identifier of the turbine.

    :returns scenario: Simulation scenario profile name (defaults to 'normal').
    """
    scenarios = config.maintenance_demo_scenarios()
    return scenarios.get(turbine_id, SCENARIO_NORMAL)


def _to_row(turbine_id: int, day: date, result: dict[str, Any]) -> PredictionRow:
    """
    Transform raw assessment result dictionary into validated database prediction row.

    :param turbine_id: Unique numeric turbine identifier.
    :param day: Forecast date to assign to the prediction.
    :param result: Raw payload returned by `assess_turbine_health`.

    :returns row: Validated `PredictionRow` model instance.
    """
    p = float(result.get("fault_probability", 0.0))
    daily_forecast = result.get("daily_forecast") or []
    if daily_forecast and isinstance(daily_forecast, list):
        first_day = daily_forecast[0]
        cum_p = float(first_day.get("cumulative_fault_probability", p))
    else:
        cum_p = p

    subsystem = result.get("suspected_subsystem")
    normalized_subsystem = (
        subsystem.strip() if subsystem and str(subsystem).strip() else NO_SUBSYSTEM
    )

    return PredictionRow(
        turbine_id=turbine_id,
        predicted_date=day,
        daily_fault_probability=p,
        cumulative_fault_probability=cum_p,
        status=str(result.get("health_status", "NORMAL")),
        suspected_subsystem=normalized_subsystem,
        health_score=result.get("health_score"),
        estimated_days_to_failure=result.get("estimated_days_to_failure"),
        anomalous_sensors=result.get("anomalous_sensors"),
        summary_text=result.get("summary_text"),
    )


async def run_prediction_cycle(
    http: httpx.AsyncClient,
    *,
    day: date,
    get_telemetry: Callable[[int], Awaitable[list[dict[str, Any]] | None]] | None = None,
    turbine_ids: list[int] | None = None,
    dry_run: bool = False,
    predictor: TurbineHealthPredictor | None = None,
) -> RunSummary:
    """
    Execute a full diagnostic assessment cycle across registered turbines and upsert results.

    :param http: Shared asynchronous HTTP client.
    :param day: Target calendar date for prediction assignment.
    :param get_telemetry: Optional async callable returning telemetry records (or None for simulation).
    :param turbine_ids: Optional explicit turbine IDs to evaluate (defaults to fetching all from database).
    :param dry_run: If True, computes predictions and summary but writes nothing to database.
    :param predictor: Optional pre-loaded ML predictor instance.

    :returns summary: Diagnostic summary of processed, written, and skipped turbines.
    """
    started = time.monotonic()
    summary = RunSummary(day=day)

    ids = turbine_ids if turbine_ids is not None else await supabase.fetch_all_turbine_ids(http)
    summary.total = len(ids)

    feature_inputs = await supabase.fetch_maintenance_inputs(http, ids)

    active_predictor = predictor or load_predictor()
    rows: list[PredictionRow] = []

    for tid in ids:
        try:
            features = feature_inputs.get(tid)
            if features is not None:
                result = assess_turbine_health(
                    asset_id=tid,
                    features_record=features,
                    predictor=active_predictor,
                )
            else:
                telemetry: list[dict[str, Any]] | None = None
                if get_telemetry is not None:
                    telemetry = await get_telemetry(tid)
                    if telemetry is not None and len(telemetry) == 0:
                        summary.no_data += 1
                        continue

                result = assess_turbine_health(
                    asset_id=tid,
                    telemetry_records=telemetry,
                    scenario=scenario_for(tid),
                    predictor=active_predictor,
                )
            rows.append(_to_row(tid, day, result))
        except Exception:
            logger.exception("Assessment failed for turbine %s", tid)
            summary.failed += 1

    if rows and not dry_run:
        await supabase.upsert_predictions(http, [r.model_dump(mode="json") for r in rows])

    summary.written = 0 if dry_run else len(rows)
    for r in rows:
        summary.by_status[r.status] = summary.by_status.get(r.status, 0) + 1
    summary.duration_s = round(time.monotonic() - started, 3)

    return summary


__all__ = ["run_prediction_cycle", "scenario_for"]
