"""
# Turbine health predictor and diagnostics

Scoring telemetry windows, computing fault risk, estimating lead time, and root-cause attribution.

The following can be imported from this module:
- `TurbineHealthPredictor`
- `resolve_maintenance_models_dir`
"""

import json
import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from smarthack.maintenance.constants import (
    DEFAULT_HEALTH_THRESHOLD_CRITICAL,
    DEFAULT_HEALTH_THRESHOLD_WARNING,
    DEFAULT_HEALTH_THRESHOLD_WATCH,
    HEALTH_STATUS_CRITICAL,
    HEALTH_STATUS_NORMAL,
    HEALTH_STATUS_WARNING,
    HEALTH_STATUS_WATCH,
    SENSOR_AMBIENT_TEMP,
    SENSOR_BEARING_DE,
    SENSOR_BEARING_NDE,
    SENSOR_GEARBOX_BEARING,
    SENSOR_GEARBOX_OIL,
)
from smarthack.maintenance.features import extract_maintenance_features

logger = logging.getLogger(__name__)


def resolve_maintenance_models_dir(models_dir: str | Path | None = None) -> Path:
    """
    Locate the directory containing trained maintenance model artifacts.

    :param models_dir: Explicit path or None to use default.

    :returns path: Resolved Path object.
    """
    if models_dir is not None:
        return Path(models_dir)
    return Path("/home/stefan/Smarthack/models/maintenance")


class TurbineHealthPredictor:
    """Evaluates SCADA telemetry streams to detect impending failures and diagnose subsystems."""

    def __init__(self) -> None:
        """Initialize the health predictor with uninitialized model state."""
        self.model: Any = None
        self.feature_columns: list[str] = []

    def load_model(
        self,
        model_path: str | Path | None = None,
        features_path: str | Path | None = None,
    ) -> None:
        """
        Load serialized LightGBM fault classifier and expected feature names.

        :param model_path: Path to `.joblib` model file.
        :param features_path: Path to `.json` feature list file.

        :raises FileNotFoundError: If required artifact files are missing.
        """
        base = resolve_maintenance_models_dir()
        resolved_model = Path(model_path) if model_path else base / "fault_classifier.joblib"
        resolved_feats = Path(features_path) if features_path else base / "fault_features.json"

        if not resolved_model.is_file():
            raise FileNotFoundError(f"Missing maintenance model file: {resolved_model}")
        if not resolved_feats.is_file():
            raise FileNotFoundError(f"Missing maintenance features file: {resolved_feats}")

        self.model = joblib.load(resolved_model)
        with open(resolved_feats, "r") as f:
            self.feature_columns = json.load(f)

    def evaluate_telemetry(
        self,
        telemetry_df: pd.DataFrame,
        asset_id: int = 0,
    ) -> dict[str, Any]:
        """
        Score a multi-interval SCADA observation window for impending failure risk.

        :param telemetry_df: Chronologically sorted SCADA observations.
        :param asset_id: Turbine asset identifier.

        :returns evaluation: Health assessment dictionary.
        """
        if self.model is None:
            self.load_model()

        if len(telemetry_df) == 0:
            return {
                "asset_id": asset_id,
                "status": HEALTH_STATUS_NORMAL,
                "health_score": 100.0,
                "fault_probability": 0.0,
                "estimated_days_to_failure": None,
                "suspected_subsystem": None,
                "anomalous_sensors": [],
            }

        features = extract_maintenance_features(telemetry_df)
        for col in self.feature_columns:
            if col not in features.columns:
                features[col] = 0.0

        x_eval = features[self.feature_columns].tail(1)
        prob = float(self.model.predict_proba(x_eval)[0, 1])

        # Physical safety rules and component diagnostics
        latest = telemetry_df.iloc[-1]
        ambient = float(latest.get(SENSOR_AMBIENT_TEMP, 20.0))
        de_temp = float(latest.get(SENSOR_BEARING_DE, 0.0))
        nde_temp = float(latest.get(SENSOR_BEARING_NDE, 0.0))
        gb_temp = float(latest.get(SENSOR_GEARBOX_BEARING, 0.0))
        gb_oil = float(latest.get(SENSOR_GEARBOX_OIL, 0.0))

        anomalous_sensors: list[str] = []
        suspected_subsystem: str | None = None
        physical_prob = 0.0

        # Bearing thermal excursion check
        if de_temp > 75.0 or (de_temp - ambient > 45.0) or (de_temp > nde_temp + 20.0):
            anomalous_sensors.append(f"{SENSOR_BEARING_DE} ({de_temp:.1f}°C)")
            suspected_subsystem = "Generator Bearing (Drive End)"
            physical_prob = 0.90 if de_temp > 80.0 else 0.70
        elif gb_temp > 70.0 or gb_oil > 62.0:
            anomalous_sensors.append(f"{SENSOR_GEARBOX_BEARING} ({gb_temp:.1f}°C)")
            suspected_subsystem = "Gearbox Transmission"
            physical_prob = 0.88 if gb_temp > 75.0 else 0.65

        # Fuse ML probability with physical safety limits
        combined_prob = max(prob, physical_prob)
        health_score = round(float(np.clip(100.0 * (1.0 - combined_prob), 0.0, 100.0)), 1)

        if combined_prob >= DEFAULT_HEALTH_THRESHOLD_CRITICAL:
            status = HEALTH_STATUS_CRITICAL
        elif combined_prob >= DEFAULT_HEALTH_THRESHOLD_WARNING:
            status = HEALTH_STATUS_WARNING
        elif combined_prob >= DEFAULT_HEALTH_THRESHOLD_WATCH:
            status = HEALTH_STATUS_WATCH
        else:
            status = HEALTH_STATUS_NORMAL

        # Estimated lead time before breakdown
        days_to_failure: float | None = None
        if combined_prob >= DEFAULT_HEALTH_THRESHOLD_WATCH:
            days_to_failure = round(float(max(1.0, (1.0 - combined_prob) * 9.0 + 1.2)), 1)
            if suspected_subsystem is None:
                suspected_subsystem = "Drivetrain Mechanical Group"

        return {
            "asset_id": asset_id,
            "status": status,
            "health_score": health_score,
            "fault_probability": round(combined_prob, 3),
            "estimated_days_to_failure": days_to_failure,
            "suspected_subsystem": suspected_subsystem,
            "anomalous_sensors": anomalous_sensors,
            "records_evaluated": len(telemetry_df),
        }


__all__ = ["TurbineHealthPredictor", "resolve_maintenance_models_dir"]
