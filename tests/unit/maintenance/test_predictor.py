"""
Unit tests for turbine health scoring and failure prediction.
"""

from pathlib import Path

from smarthack.maintenance.constants import (
    HEALTH_STATUS_CRITICAL,
    HEALTH_STATUS_NORMAL,
    HEALTH_STATUS_WARNING,
    SCENARIO_BEARING_OVERHEATING,
    SCENARIO_GEARBOX_WEAR,
    SCENARIO_HYDRAULIC_LEAK,
    SCENARIO_NORMAL,
    SCENARIO_TRANSFORMER_OVERHEATING,
)
from smarthack.maintenance.predictor import TurbineHealthPredictor, resolve_maintenance_models_dir
from smarthack.maintenance.simulator import ScadaSimulator


def test_resolve_maintenance_models_dir() -> None:
    """Verify custom and default model directories resolve properly."""
    custom = resolve_maintenance_models_dir("/tmp/custom")
    assert custom == Path("/tmp/custom")
    default = resolve_maintenance_models_dir(None)
    assert default.name == "maintenance"


def test_predictor_evaluates_normal_telemetry() -> None:
    """Predictor detects healthy operation with high health score and low risk."""
    sim = ScadaSimulator(seed=42)
    normal_df = sim.generate_stream(asset_id=0, duration_hours=48, scenario=SCENARIO_NORMAL)

    predictor = TurbineHealthPredictor()
    result = predictor.evaluate_telemetry(normal_df, asset_id=0)

    assert result["asset_id"] == 0
    assert result["status"] == HEALTH_STATUS_NORMAL
    assert result["health_score"] >= 75.0
    assert result["fault_probability"] < 0.35
    assert result["estimated_days_to_failure"] is None
    assert "nominal" in result["recommended_action"].lower()


def test_predictor_evaluates_bearing_failure() -> None:
    """Predictor detects bearing overheating, flags critical status, and estimates lead time."""
    sim = ScadaSimulator(seed=42)
    fault_df = sim.generate_stream(
        asset_id=1,
        duration_hours=48,
        scenario=SCENARIO_BEARING_OVERHEATING,
    )

    predictor = TurbineHealthPredictor()
    result = predictor.evaluate_telemetry(fault_df, asset_id=1)

    assert result["status"] in (HEALTH_STATUS_WARNING, HEALTH_STATUS_CRITICAL)
    assert result["health_score"] < 50.0
    assert result["fault_probability"] >= 0.60
    assert result["estimated_days_to_failure"] is not None
    assert 1.0 <= result["estimated_days_to_failure"] <= 7.0
    assert result["suspected_subsystem"] == "Generator Bearing"
    assert "bearing" in result["recommended_action"].lower()


def test_predictor_evaluates_gearbox_failure() -> None:
    """Predictor detects gearbox thermal wear and flags Gearbox subsystem."""
    sim = ScadaSimulator(seed=42)
    df = sim.generate_stream(asset_id=2, duration_hours=48, scenario=SCENARIO_GEARBOX_WEAR)

    predictor = TurbineHealthPredictor()
    res = predictor.evaluate_telemetry(df, asset_id=2)

    assert res["status"] in (HEALTH_STATUS_WARNING, HEALTH_STATUS_CRITICAL)
    assert res["suspected_subsystem"] == "Gearbox"
    assert res["subsystem_risks"]["Gearbox"] > 0.50


def test_predictor_evaluates_transformer_failure() -> None:
    """Predictor detects transformer phase overheating and flags Transformer subsystem."""
    sim = ScadaSimulator(seed=42)
    df = sim.generate_stream(
        asset_id=4, duration_hours=48, scenario=SCENARIO_TRANSFORMER_OVERHEATING
    )

    predictor = TurbineHealthPredictor()
    res = predictor.evaluate_telemetry(df, asset_id=4)

    assert res["status"] in (HEALTH_STATUS_WARNING, HEALTH_STATUS_CRITICAL)
    assert res["suspected_subsystem"] == "Transformer"
    assert res["subsystem_risks"]["Transformer"] > 0.50


def test_predictor_evaluates_hydraulic_failure() -> None:
    """Predictor detects hydraulic group oil overheating."""
    sim = ScadaSimulator(seed=42)
    df = sim.generate_stream(asset_id=5, duration_hours=48, scenario=SCENARIO_HYDRAULIC_LEAK)

    predictor = TurbineHealthPredictor()
    res = predictor.evaluate_telemetry(df, asset_id=5)

    assert res["status"] in (HEALTH_STATUS_WARNING, HEALTH_STATUS_CRITICAL)
    assert res["suspected_subsystem"] == "Hydraulic Group"
    assert res["subsystem_risks"]["Hydraulic Group"] > 0.50
