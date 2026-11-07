"""
Unit tests for predictive maintenance feature engineering.
"""

import numpy as np
import pandas as pd

from smarthack.maintenance.constants import (
    SENSOR_AMBIENT_TEMP,
    SENSOR_BEARING_DE,
    SENSOR_BEARING_NDE,
    SENSOR_GEARBOX_BEARING,
    SENSOR_GEARBOX_OIL,
    SENSOR_GENERATOR_RPM,
    SENSOR_GRID_POWER,
    SENSOR_PITCH_ANGLE,
    SENSOR_WIND_SPEED,
)
from smarthack.maintenance.features import (
    RAW_SCADA_COLUMNS,
    compute_thermal_lifts,
    extract_maintenance_features,
    get_maintenance_feature_names,
)


def make_synthetic_telemetry(n_points: int = 40) -> pd.DataFrame:
    """Generate minimal valid SCADA telemetry DataFrame."""
    return pd.DataFrame(
        {
            SENSOR_AMBIENT_TEMP: np.full(n_points, 20.0),
            SENSOR_WIND_SPEED: np.full(n_points, 8.0),
            SENSOR_PITCH_ANGLE: np.zeros(n_points),
            SENSOR_GENERATOR_RPM: np.full(n_points, 1200.0),
            SENSOR_GRID_POWER: np.full(n_points, 1000.0),
            SENSOR_BEARING_DE: np.linspace(45.0, 50.0, n_points),
            SENSOR_BEARING_NDE: np.full(n_points, 42.0),
            SENSOR_GEARBOX_BEARING: np.full(n_points, 48.0),
            SENSOR_GEARBOX_OIL: np.full(n_points, 44.0),
        }
    )


def test_raw_scada_columns_present() -> None:
    """Verify raw SCADA column specification has all core sensors."""
    assert SENSOR_AMBIENT_TEMP in RAW_SCADA_COLUMNS
    assert SENSOR_BEARING_DE in RAW_SCADA_COLUMNS
    assert SENSOR_GEARBOX_OIL in RAW_SCADA_COLUMNS


def test_compute_thermal_lifts() -> None:
    """Verify thermal lifts accurately compute delta over ambient."""
    df = make_synthetic_telemetry(10)
    result = compute_thermal_lifts(df)

    assert "thermal_lift_bearing_de" in result.columns
    assert "thermal_lift_gearbox_oil" in result.columns
    # 45.0 - 20.0 = 25.0
    assert np.isclose(result["thermal_lift_bearing_de"].iloc[0], 25.0)
    assert np.isclose(result["thermal_lift_gearbox_oil"].iloc[0], 24.0)


def test_extract_maintenance_features() -> None:
    """Verify feature extractor generates rolling and drift statistics."""
    df = make_synthetic_telemetry(50)
    feats = extract_maintenance_features(df)

    expected_cols = [
        "thermal_lift_bearing_de",
        "bearing_de_roll_mean_6h",
        "bearing_de_roll_std_6h",
        "bearing_de_roll_max_6h",
        "bearing_de_drift_24h",
        "gearbox_oil_roll_mean_6h",
        "rpm_deviation",
    ]
    for col in expected_cols:
        assert col in feats.columns
    assert len(feats) == 50


def test_get_maintenance_feature_names() -> None:
    """Feature names list is non-empty and consistent."""
    names = get_maintenance_feature_names()
    assert isinstance(names, list)
    assert len(names) > 5
    assert "thermal_lift_bearing_de" in names
