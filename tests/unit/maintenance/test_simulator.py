"""
Unit tests for SCADA telemetry simulator and scenario injector.
"""

from smarthack.maintenance.constants import (
    SCENARIO_BEARING_OVERHEATING,
    SCENARIO_GEARBOX_WEAR,
    SCENARIO_NORMAL,
    SCENARIO_TRANSFORMER_OVERHEATING,
    SENSOR_AMBIENT_TEMP,
    SENSOR_BEARING_DE,
    SENSOR_GEARBOX_BEARING,
    SENSOR_TRANSFORMER_L3,
    SENSOR_WIND_SPEED,
)
from smarthack.maintenance.simulator import ScadaSimulator, simulate_telemetry_stream


def test_simulator_normal_stream_shape() -> None:
    """Verify normal telemetry simulation produces valid intervals and sensors."""
    sim = ScadaSimulator(seed=123)
    df = sim.generate_stream(asset_id=5, duration_hours=24, scenario=SCENARIO_NORMAL)

    # 24 hours * 6 intervals/hr = 144 records
    assert len(df) == 144
    assert df["asset_id"].iloc[0] == 5
    assert SENSOR_WIND_SPEED in df.columns
    assert SENSOR_AMBIENT_TEMP in df.columns
    assert SENSOR_BEARING_DE in df.columns

    # In normal conditions, bearing temp is reasonable (< 65°C)
    assert df[SENSOR_BEARING_DE].max() < 65.0


def test_simulator_bearing_overheating_scenario() -> None:
    """Verify bearing overheating scenario causes progressive thermal surge."""
    sim = ScadaSimulator(seed=123)
    df = sim.generate_stream(
        asset_id=1,
        duration_hours=48,
        scenario=SCENARIO_BEARING_OVERHEATING,
    )

    first_half_mean = df[SENSOR_BEARING_DE].iloc[:144].mean()
    second_half_mean = df[SENSOR_BEARING_DE].iloc[144:].mean()

    # Temperature must drift significantly higher in the second half
    assert second_half_mean > first_half_mean + 15.0
    assert df[SENSOR_BEARING_DE].max() > 75.0


def test_simulator_gearbox_wear_scenario() -> None:
    """Verify gearbox wear scenario elevates gearbox bearing temperature."""
    df = simulate_telemetry_stream(
        asset_id=2,
        duration_hours=48,
        scenario=SCENARIO_GEARBOX_WEAR,
        seed=42,
    )

    assert df[SENSOR_GEARBOX_BEARING].max() > 68.0


def test_simulator_transformer_overheating_scenario() -> None:
    """Verify transformer overheating scenario elevates phase temperature significantly."""
    df = simulate_telemetry_stream(
        asset_id=8,
        duration_hours=48,
        scenario=SCENARIO_TRANSFORMER_OVERHEATING,
        seed=42,
    )

    assert df[SENSOR_TRANSFORMER_L3].max() > 90.0


def test_simulate_telemetry_stream_helper() -> None:
    """Verify module-level simulate_telemetry_stream helper works as expected."""
    df = simulate_telemetry_stream(asset_id=0, duration_hours=6)
    assert len(df) == 36
