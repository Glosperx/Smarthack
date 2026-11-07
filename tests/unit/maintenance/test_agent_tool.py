"""
Unit tests for the maintenance agent tool and interface adapter.
"""

from smarthack.maintenance.agent_tool import (
    assess_turbine_health,
    format_health_report,
    get_maintenance_tool_spec,
    simulate_turbine_scenario,
)
from smarthack.maintenance.constants import (
    HEALTH_STATUS_CRITICAL,
    HEALTH_STATUS_NORMAL,
    HEALTH_STATUS_WARNING,
    SCENARIO_BEARING_OVERHEATING,
    SCENARIO_NORMAL,
)


def test_get_maintenance_tool_spec_schema() -> None:
    """Agent tool spec follows OpenAI/Gemini function calling schema standards."""
    spec = get_maintenance_tool_spec()
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "assess_turbine_health"
    props = spec["function"]["parameters"]["properties"]
    assert "asset_id" in props
    assert "window_hours" in props
    assert "horizon_days" in props
    assert "scenario" in props
    assert "asset_id" in spec["function"]["parameters"]["required"]


def test_assess_turbine_health_normal() -> None:
    """Agent tool returns structured health payload for normal turbine operations."""
    payload = assess_turbine_health(asset_id=0, window_hours=48, scenario=SCENARIO_NORMAL)

    assert payload["status"] == "success"
    assert payload["asset_id"] == 0
    assert payload["health_status"] == HEALTH_STATUS_NORMAL
    assert payload["health_score"] >= 75.0
    assert "subsystem_risks" in payload
    assert "daily_forecast" in payload
    assert len(payload["daily_forecast"]) == 7
    assert "recommended_action" in payload
    assert "summary_text" in payload
    assert "Turbine #0" in payload["summary_text"]


def test_assess_turbine_health_fault_scenario() -> None:
    """Agent tool detects failure scenario and generates appropriate alert text."""
    payload = assess_turbine_health(
        asset_id=3,
        window_hours=48,
        scenario=SCENARIO_BEARING_OVERHEATING,
    )

    assert payload["status"] == "success"
    assert payload["asset_id"] == 3
    assert payload["health_status"] in (HEALTH_STATUS_WARNING, HEALTH_STATUS_CRITICAL)
    assert payload["estimated_days_to_failure"] is not None
    assert payload["suspected_subsystem"] == "Generator Bearing"
    assert "subsystem_risks" in payload
    assert "daily_forecast" in payload
    assert len(payload["daily_forecast"]) == 7
    assert payload["subsystem_risks"]["Generator Bearing"] > 0.50
    assert "summary_text" in payload
    assert "ALERT" in payload["summary_text"] or "WARNING" in payload["summary_text"]


def test_simulate_turbine_scenario_convenience() -> None:
    """Direct scenario simulation returns actionable health assessment payload."""
    payload = simulate_turbine_scenario(asset_id=7, scenario=SCENARIO_BEARING_OVERHEATING)
    assert payload["status"] == "success"
    assert payload["asset_id"] == 7
    assert payload["records_evaluated"] > 0
    assert len(payload["daily_forecast"]) == 7


def test_format_health_report() -> None:
    """Health report ASCII formatter includes all diagnostic summary fields."""
    payload = assess_turbine_health(asset_id=2, scenario=SCENARIO_NORMAL)
    report = format_health_report(payload)

    assert "=== Turbine #2 Health Assessment ===" in report
    assert "Operational Status" in report
    assert "Overall Health Score" in report
    assert "Fault Risk Probability" in report
    assert "Subsystem Risk Breakdown" in report
    assert "7-Day Failure Risk Forecast" in report
    assert "Recommended Action" in report
