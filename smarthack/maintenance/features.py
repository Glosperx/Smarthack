"""
# Predictive maintenance feature engineering

Extraction of thermal lift differentials, moving statistics, and telemetry signals.

The following can be imported from this module:
- `RAW_SCADA_COLUMNS`
- `compute_thermal_lifts`
- `extract_maintenance_features`
- `get_maintenance_feature_names`
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
    SENSOR_HYDRAULIC_OIL,
    SENSOR_NACELLE_TEMP,
    SENSOR_PITCH_ANGLE,
    SENSOR_ROTOR_RPM,
    SENSOR_STATOR_PHASE1,
    SENSOR_STATOR_PHASE2,
    SENSOR_STATOR_PHASE3,
    SENSOR_TRANSFORMER_L1,
    SENSOR_TRANSFORMER_L2,
    SENSOR_TRANSFORMER_L3,
    SENSOR_WIND_SPEED,
)

#: Core raw SCADA columns for feature extraction.
RAW_SCADA_COLUMNS: list[str] = [
    SENSOR_AMBIENT_TEMP,
    SENSOR_WIND_SPEED,
    SENSOR_PITCH_ANGLE,
    SENSOR_GEARBOX_BEARING,
    SENSOR_GEARBOX_OIL,
    SENSOR_BEARING_DE,
    SENSOR_BEARING_NDE,
    SENSOR_GENERATOR_RPM,
    SENSOR_GRID_POWER,
]


def compute_thermal_lifts(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute component temperature differentials relative to ambient conditions.

    :param df: DataFrame containing component temperatures and ambient temperature.

    :returns result: DataFrame augmented with thermal lift series.
    """
    data = df.copy()
    ambient = data[SENSOR_AMBIENT_TEMP]

    # Bearing and Gearbox thermal lifts
    data["thermal_lift_bearing_de"] = data[SENSOR_BEARING_DE] - ambient
    data["thermal_lift_bearing_nde"] = data[SENSOR_BEARING_NDE] - ambient
    data["thermal_lift_gearbox_oil"] = data[SENSOR_GEARBOX_OIL] - ambient
    data["thermal_lift_gearbox_bearing"] = data[SENSOR_GEARBOX_BEARING] - ambient
    data["bearing_temp_ratio"] = (data[SENSOR_BEARING_DE] + 1e-5) / (
        data[SENSOR_BEARING_NDE] + 1e-5
    )

    # Hydraulic group thermal lift (fallback to gearbox oil - 5°C if sensor missing)
    if SENSOR_HYDRAULIC_OIL in data.columns:
        data["thermal_lift_hydraulic_oil"] = data[SENSOR_HYDRAULIC_OIL] - ambient
    else:
        data["thermal_lift_hydraulic_oil"] = data["thermal_lift_gearbox_oil"] - 5.0
        data[SENSOR_HYDRAULIC_OIL] = ambient + data["thermal_lift_hydraulic_oil"]

    # Transformer thermal lifts and inter-phase imbalance
    has_trans = (
        SENSOR_TRANSFORMER_L1 in data.columns
        and SENSOR_TRANSFORMER_L2 in data.columns
        and SENSOR_TRANSFORMER_L3 in data.columns
    )
    if has_trans:
        trans_max = data[[SENSOR_TRANSFORMER_L1, SENSOR_TRANSFORMER_L2, SENSOR_TRANSFORMER_L3]].max(
            axis=1
        )
        trans_min = data[[SENSOR_TRANSFORMER_L1, SENSOR_TRANSFORMER_L2, SENSOR_TRANSFORMER_L3]].min(
            axis=1
        )
        data["thermal_lift_transformer"] = trans_max - ambient
        data["transformer_phase_imbalance"] = trans_max - trans_min
    else:
        data["thermal_lift_transformer"] = 35.0
        data["transformer_phase_imbalance"] = 2.0

    # Generator stator winding thermal lifts and inter-phase imbalance
    has_stator = (
        SENSOR_STATOR_PHASE1 in data.columns
        and SENSOR_STATOR_PHASE2 in data.columns
        and SENSOR_STATOR_PHASE3 in data.columns
    )
    if has_stator:
        stator_max = data[[SENSOR_STATOR_PHASE1, SENSOR_STATOR_PHASE2, SENSOR_STATOR_PHASE3]].max(
            axis=1
        )
        stator_min = data[[SENSOR_STATOR_PHASE1, SENSOR_STATOR_PHASE2, SENSOR_STATOR_PHASE3]].min(
            axis=1
        )
        data["thermal_lift_stator"] = stator_max - ambient
        data["stator_phase_imbalance"] = stator_max - stator_min
    else:
        data["thermal_lift_stator"] = 32.0
        data["stator_phase_imbalance"] = 1.5

    # Nacelle temperature lift
    if SENSOR_NACELLE_TEMP in data.columns:
        data["thermal_lift_nacelle"] = data[SENSOR_NACELLE_TEMP] - ambient
    else:
        data["thermal_lift_nacelle"] = 12.0

    # Rotor speed fallback
    if SENSOR_ROTOR_RPM not in data.columns:
        data[SENSOR_ROTOR_RPM] = data[SENSOR_GENERATOR_RPM] / 100.0

    return data


def extract_maintenance_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute rolling statistics, thermal drift, and kinematic ratios across a telemetry window.

    :param df: Chronologically sorted SCADA observations (10-minute intervals).

    :returns features: Computed feature matrix ready for model scoring.
    """
    data = compute_thermal_lifts(df)

    win_6h = min(36, max(3, len(data)))
    win_24h = min(144, max(6, len(data)))

    features = pd.DataFrame(index=data.index)

    # Core instantaneous measurements
    features[SENSOR_AMBIENT_TEMP] = data[SENSOR_AMBIENT_TEMP]
    features[SENSOR_WIND_SPEED] = data[SENSOR_WIND_SPEED]
    features[SENSOR_GENERATOR_RPM] = data[SENSOR_GENERATOR_RPM]
    features[SENSOR_GRID_POWER] = data[SENSOR_GRID_POWER]
    features[SENSOR_PITCH_ANGLE] = data[SENSOR_PITCH_ANGLE]
    features[SENSOR_ROTOR_RPM] = data[SENSOR_ROTOR_RPM]

    # Subsystem thermal lifts and phase balances
    features["thermal_lift_bearing_de"] = data["thermal_lift_bearing_de"]
    features["thermal_lift_bearing_nde"] = data["thermal_lift_bearing_nde"]
    features["bearing_temp_ratio"] = data["bearing_temp_ratio"]
    features["thermal_lift_gearbox_bearing"] = data["thermal_lift_gearbox_bearing"]
    features["thermal_lift_gearbox_oil"] = data["thermal_lift_gearbox_oil"]
    features["thermal_lift_hydraulic_oil"] = data["thermal_lift_hydraulic_oil"]
    features["thermal_lift_transformer"] = data["thermal_lift_transformer"]
    features["transformer_phase_imbalance"] = data["transformer_phase_imbalance"]
    features["thermal_lift_stator"] = data["thermal_lift_stator"]
    features["stator_phase_imbalance"] = data["stator_phase_imbalance"]

    # Rolling aggregations for generator bearing (DE)
    features["bearing_de_roll_mean_6h"] = (
        data[SENSOR_BEARING_DE].rolling(win_6h, min_periods=1).mean()
    )
    features["bearing_de_roll_std_6h"] = (
        data[SENSOR_BEARING_DE].rolling(win_6h, min_periods=1).std().fillna(0.0)
    )
    features["bearing_de_roll_max_6h"] = (
        data[SENSOR_BEARING_DE].rolling(win_6h, min_periods=1).max()
    )
    features["bearing_de_drift_24h"] = (
        data[SENSOR_BEARING_DE] - data[SENSOR_BEARING_DE].rolling(win_24h, min_periods=1).mean()
    )

    # Rolling aggregations for gearbox
    features["gearbox_oil_roll_mean_6h"] = (
        data[SENSOR_GEARBOX_OIL].rolling(win_6h, min_periods=1).mean()
    )
    features["gearbox_oil_roll_std_6h"] = (
        data[SENSOR_GEARBOX_OIL].rolling(win_6h, min_periods=1).std().fillna(0.0)
    )
    features["gearbox_bearing_drift_24h"] = (
        data[SENSOR_GEARBOX_BEARING]
        - data[SENSOR_GEARBOX_BEARING].rolling(win_24h, min_periods=1).mean()
    )

    # Rolling aggregations for hydraulic group
    features["hydraulic_oil_roll_mean_6h"] = (
        data[SENSOR_HYDRAULIC_OIL].rolling(win_6h, min_periods=1).mean()
    )
    features["hydraulic_oil_drift_24h"] = (
        data[SENSOR_HYDRAULIC_OIL]
        - data[SENSOR_HYDRAULIC_OIL].rolling(win_24h, min_periods=1).mean()
    )

    # Rolling aggregations for transformer
    features["transformer_roll_mean_6h"] = (
        data["thermal_lift_transformer"].rolling(win_6h, min_periods=1).mean()
    )
    features["transformer_drift_24h"] = (
        data["thermal_lift_transformer"]
        - data["thermal_lift_transformer"].rolling(win_24h, min_periods=1).mean()
    )

    # Drivetrain kinematics: gear ratio and RPM deviation
    features["gearbox_speed_ratio"] = (data[SENSOR_GENERATOR_RPM] + 1e-5) / (
        data[SENSOR_ROTOR_RPM] + 1e-5
    )
    expected_rpm = np.clip(data[SENSOR_WIND_SPEED] * 120.0, 0.0, 1800.0)
    features["rpm_deviation"] = np.abs(data[SENSOR_GENERATOR_RPM] - expected_rpm)

    return features


def get_maintenance_feature_names() -> list[str]:
    """
    Return the ordered list of feature names used by the maintenance model.

    :returns names: List of string feature column names.
    """
    dummy = pd.DataFrame({col: [20.0, 21.0, 22.0] for col in RAW_SCADA_COLUMNS})
    return list(extract_maintenance_features(dummy).columns)


__all__ = [
    "RAW_SCADA_COLUMNS",
    "compute_thermal_lifts",
    "extract_maintenance_features",
    "get_maintenance_feature_names",
]
