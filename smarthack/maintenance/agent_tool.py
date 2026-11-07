"""
# Maintenance agent tool and interface API

High-level function calling specifications and interfaces for autonomous LLM agents.

The following can be imported from this module:
- `assess_turbine_health`
- `format_health_report`
- `get_maintenance_tool_spec`
- `simulate_turbine_scenario`
"""

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from smarthack.maintenance.constants import (
    HEALTH_STATUS_NORMAL,
    HEALTH_STATUS_WARNING,
    HEALTH_STATUS_WATCH,
    SCENARIO_BEARING_OVERHEATING,
    SCENARIO_NORMAL,
)
from smarthack.maintenance.predictor import TurbineHealthPredictor, resolve_maintenance_models_dir
from smarthack.maintenance.simulator import ScadaSimulator

logger = logging.getLogger(__name__)


def get_maintenance_tool_spec() -> dict[str, Any]:
    """
    Return the function-calling JSON schema specification for LLM agents.

    :returns spec: Standard OpenAI/Gemini-compatible function tool definition.
    """
    return {
        "type": "function",
        "function": {
            "name": "assess_turbine_health",
            "description": (
                "Assess the physical health of a wind turbine from recent SCADA telemetry streams. "
                "Predicts impending component breakdown, fault probability, days-to-failure lead time, "
                "and identifies the failing subsystem (Generator Bearing, Gearbox, Hydraulic Group)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_id": {
                        "type": "integer",
                        "description": "Unique wind turbine identifier (e.g. 0, 1, 10).",
                        "default": 0,
                    },
                    "window_hours": {
                        "type": "integer",
                        "description": "Hours of operational telemetry to evaluate (default 48).",
                        "default": 48,
                    },
                    "scenario": {
                        "type": "string",
                        "description": (
                            "Optional simulation scenario to evaluate: 'normal', 'bearing_overheating', "
                            "'gearbox_wear', or 'hydraulic_leak'."
                        ),
                        "enum": ["normal", "bearing_overheating", "gearbox_wear", "hydraulic_leak"],
                        "default": "normal",
                    },
                },
                "required": ["asset_id"],
            },
        },
    }


def assess_turbine_health(
    asset_id: int = 0,
    telemetry_records: list[dict[str, Any]] | None = None,
    window_hours: int = 48,
    scenario: str = SCENARIO_NORMAL,
    models_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Evaluate wind turbine telemetry and return health metrics, lead time, and diagnosis.

    :param asset_id: Wind turbine asset identifier.
    :param telemetry_records: Optional list of raw SCADA records. If None, uses simulator.
    :param window_hours: Hours of telemetry window to evaluate.
    :param scenario: Fault profile if synthesizing telemetry.
    :param models_dir: Optional custom directory path to model artifacts.

    :returns result: Structured assessment payload for agent consumption.
    """
    resolved_dir = resolve_maintenance_models_dir(models_dir)
    predictor = TurbineHealthPredictor()
    predictor.load_model(
        model_path=resolved_dir / "fault_classifier.joblib",
        features_path=resolved_dir / "fault_features.json",
    )

    if telemetry_records is not None and len(telemetry_records) > 0:
        telemetry_df = pd.DataFrame(telemetry_records)
    else:
        simulator = ScadaSimulator(seed=42 + asset_id)
        telemetry_df = simulator.generate_stream(
            asset_id=asset_id,
            duration_hours=window_hours,
            scenario=scenario,
        )

    eval_result = predictor.evaluate_telemetry(telemetry_df, asset_id=asset_id)
    status = eval_result["status"]
    health = eval_result["health_score"]
    prob = eval_result["fault_probability"]
    days = eval_result["estimated_days_to_failure"]
    subsystem = eval_result["suspected_subsystem"]

    if status == HEALTH_STATUS_NORMAL:
        summary_text = (
            f"Turbine #{asset_id} is operating within nominal thresholds (Health Score: {health}/100). "
            f"Fault risk is negligible ({prob:.1%}). No maintenance required."
        )
    elif status == HEALTH_STATUS_WATCH:
        summary_text = (
            f"Turbine #{asset_id} status is WATCH (Health Score: {health}/100, Risk: {prob:.1%}). "
            f"Minor thermal/variance drift detected. Projected lead time to potential fault: {days} days. "
            f"Recommend scheduled diagnostic inspection."
        )
    elif status == HEALTH_STATUS_WARNING:
        summary_text = (
            f"WARNING: Turbine #{asset_id} shows significant degradation in {subsystem or 'drivetrain'} "
            f"(Health Score: {health}/100, Failure Probability: {prob:.1%}). Estimated lead time before breakdown: "
            f"{days} days. Recommend scheduling maintenance team within 48 hours."
        )
    else:  # CRITICAL
        summary_text = (
            f"CRITICAL ALERT: Turbine #{asset_id} is in critical condition (Health Score: {health}/100, "
            f"Failure Probability: {prob:.1%}). Impending breakdown in {subsystem or 'drivetrain'} within {days} days. "
            f"Immediate dispatch and derating advised."
        )

    return {
        "status": "success",
        "asset_id": asset_id,
        "health_status": status,
        "health_score": health,
        "fault_probability": prob,
        "estimated_days_to_failure": days,
        "suspected_subsystem": subsystem,
        "anomalous_sensors": eval_result["anomalous_sensors"],
        "records_evaluated": eval_result["records_evaluated"],
        "summary_text": summary_text,
    }


def simulate_turbine_scenario(
    asset_id: int = 0,
    scenario: str = SCENARIO_BEARING_OVERHEATING,
    duration_hours: int = 48,
    models_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Simulate a deteriorating turbine scenario and evaluate the resulting health impact.

    :param asset_id: Wind turbine asset ID.
    :param scenario: Fault profile to inject.
    :param duration_hours: Duration of telemetry stream in hours.
    :param models_dir: Optional custom model directory path.

    :returns result: Health evaluation and simulation results.
    """
    return assess_turbine_health(
        asset_id=asset_id,
        window_hours=duration_hours,
        scenario=scenario,
        models_dir=models_dir,
    )


def format_health_report(payload: dict[str, Any]) -> str:
    """
    Format a structured health assessment dictionary as a human-readable text report.

    :param payload: Dictionary returned by `assess_turbine_health`.

    :returns report: Multi-line formatted ASCII report.
    """
    asset_id = payload.get("asset_id", 0)
    status = payload.get("health_status", "UNKNOWN")
    score = payload.get("health_score", 0.0)
    prob = payload.get("fault_probability", 0.0)
    days = payload.get("estimated_days_to_failure")
    subsystem = payload.get("suspected_subsystem") or "None"
    anomalous = ", ".join(payload.get("anomalous_sensors", [])) or "None"

    days_str = f"{days} days" if days is not None else "N/A"

    lines = [
        f"=== Turbine #{asset_id} Health Assessment ===",
        f"Operational Status    : {status}",
        f"Overall Health Score  : {score} / 100",
        f"Fault Risk Probability: {prob:.1%}",
        f"Estimated Time to Fail: {days_str}",
        f"Suspected Subsystem   : {subsystem}",
        f"Anomalous Sensors     : {anomalous}",
        "----------------------------------------------",
        payload.get("summary_text", ""),
    ]
    return "\n".join(lines)


__all__ = [
    "assess_turbine_health",
    "format_health_report",
    "get_maintenance_tool_spec",
    "simulate_turbine_scenario",
]
