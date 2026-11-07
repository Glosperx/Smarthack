"""
# Turbine health predictor and diagnostics

Scoring telemetry windows, computing fault risk, estimating lead time, and root-cause attribution.

The following can be imported from this module:
- `TurbineHealthPredictor`
- `resolve_maintenance_models_dir`
"""

from datetime import datetime, timedelta
import json
import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from smarthack.config import maintenance_models_dir
from smarthack.maintenance.constants import (
    DEFAULT_FORECAST_HORIZON_DAYS,
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
    SENSOR_HYDRAULIC_OIL,
    SENSOR_TRANSFORMER_L1,
    SENSOR_TRANSFORMER_L2,
    SENSOR_TRANSFORMER_L3,
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
    return maintenance_models_dir()


def _get_recommended_action(subsystem: str | None, status: str) -> str:
    """Produce actionable maintenance recommendation based on diagnosed subsystem."""
    if status == HEALTH_STATUS_NORMAL or subsystem is None:
        return (
            "All subsystems operating within nominal limits. Maintain routine maintenance schedule."
        )

    if subsystem == "Generator Bearing":
        if status == HEALTH_STATUS_CRITICAL:
            return (
                "IMMEDIATE ACTION: Derate turbine or execute controlled shutdown. Inspect generator "
                "drive-end bearing for thermal runaway, bearing cage spalling, and grease degradation."
            )
        return (
            "SCHEDULED ACTION: Inspect generator drive-end bearing lubrication, measure high-frequency "
            "vibration spectra, and schedule replacement within 48 to 72 hours."
        )

    if subsystem == "Gearbox":
        if status == HEALTH_STATUS_CRITICAL:
            return (
                "IMMEDIATE ACTION: Stop turbine for mechanical inspection. Check magnetic chip detector "
                "for metallic debris, inspect high-speed shaft bearing, and sample gearbox oil."
            )
        return (
            "SCHEDULED ACTION: Check gearbox oil viscosity, inspect high-speed stage bearing temperature, "
            "and verify lubrication oil cooler pump operation within 3 days."
        )

    if subsystem == "Hydraulic Group":
        if status == HEALTH_STATUS_CRITICAL:
            return (
                "IMMEDIATE ACTION: Inspect hydraulic pitch emergency accumulators, check main pump duty "
                "cycle for continuous pumping (leak), and inspect proportional valves."
            )
        return (
            "SCHEDULED ACTION: Check hydraulic oil filter differential pressure, top off hydraulic fluid, "
            "and inspect blade pitch cylinder seals within 5 days."
        )

    if subsystem == "Transformer":
        if status == HEALTH_STATUS_CRITICAL:
            return (
                "IMMEDIATE ACTION: Derate power output immediately to reduce thermal loading. Inspect "
                "HV transformer cooling fans and check dissolved gas analysis (DGA) for arcing/overheating."
            )
        return (
            "SCHEDULED ACTION: Clean transformer cooling radiator fins, verify phase balance, and "
            "inspect busbar connections within 48 hours."
        )

    return (
        "SCHEDULED ACTION: Dispatch technician for diagnostic inspection of drivetrain components."
    )


class TurbineHealthPredictor:
    """Evaluates SCADA telemetry streams to detect impending failures and diagnose subsystems."""

    def __init__(self) -> None:
        """Initialize the health predictor with uninitialized model state."""
        self.model: Any = None
        self.subsystem_model: Any = None
        self.feature_columns: list[str] = []

    def load_model(
        self,
        model_path: str | Path | None = None,
        subsystem_path: str | Path | None = None,
        features_path: str | Path | None = None,
    ) -> None:
        """
        Load serialized LightGBM fault classifier and expected feature names.

        :param model_path: Path to binary `.joblib` model file.
        :param subsystem_path: Path to multi-class `.joblib` subsystem model file.
        :param features_path: Path to `.json` feature list file.

        :raises FileNotFoundError: If required artifact files are missing.
        """
        base = resolve_maintenance_models_dir()
        resolved_model = Path(model_path) if model_path else base / "fault_classifier.joblib"
        resolved_subsys = (
            Path(subsystem_path) if subsystem_path else base / "subsystem_classifier.joblib"
        )
        resolved_feats = Path(features_path) if features_path else base / "fault_features.json"

        if not resolved_model.is_file():
            raise FileNotFoundError(f"Missing maintenance model file: {resolved_model}")
        if not resolved_feats.is_file():
            raise FileNotFoundError(f"Missing maintenance features file: {resolved_feats}")

        self.model = joblib.load(resolved_model)
        if resolved_subsys.is_file():
            self.subsystem_model = joblib.load(resolved_subsys)

        with open(resolved_feats, "r") as f:
            self.feature_columns = json.load(f)

    def compute_daily_forecast(
        self,
        fault_prob: float,
        days_to_failure: float | None,
        subsystem: str | None,
        start_date: datetime | None = None,
        horizon_days: int = DEFAULT_FORECAST_HORIZON_DAYS,
    ) -> list[dict[str, Any]]:
        """
        Forecast failure probabilities day-by-day across an upcoming time horizon.

        :param fault_prob: Overall failure probability (0.0 to 1.0).
        :param days_to_failure: Estimated lead time in days, or None if healthy.
        :param subsystem: Primary diagnosed subsystem, or None.
        :param start_date: Starting datetime for the forecast (default now).
        :param horizon_days: Forecast horizon in days (default 7).

        :returns daily_forecast: Day-by-day risk breakdown list.
        """
        if start_date is None:
            start_date = datetime.now()

        forecast: list[dict[str, Any]] = []
        prev_cum = 0.0

        if fault_prob < DEFAULT_HEALTH_THRESHOLD_WATCH or days_to_failure is None:
            for d in range(1, horizon_days + 1):
                date_str = (start_date + timedelta(days=d)).strftime("%Y-%m-%d")
                cum = round(float(min(0.30, fault_prob * (1.0 - np.exp(-0.15 * d)))), 3)
                daily_p = round(float(max(0.005, cum - prev_cum)), 3)
                prev_cum = cum
                forecast.append(
                    {
                        "day": d,
                        "date": date_str,
                        "daily_fault_probability": daily_p,
                        "cumulative_fault_probability": cum,
                        "status": HEALTH_STATUS_NORMAL,
                        "suspected_subsystem": None,
                    }
                )
        else:
            t_crit = max(0.8, days_to_failure)
            beta = 2.4
            eta = t_crit / (np.log(2.0) ** (1.0 / beta))

            for d in range(1, horizon_days + 1):
                date_str = (start_date + timedelta(days=d)).strftime("%Y-%m-%d")
                weibull_cdf = 1.0 - np.exp(-((d / eta) ** beta))
                cum = round(float(np.clip(weibull_cdf * fault_prob, 0.01, 0.999)), 3)
                daily_p = round(float(np.clip(cum - prev_cum, 0.001, 1.0)), 3)
                prev_cum = cum

                if cum >= DEFAULT_HEALTH_THRESHOLD_CRITICAL:
                    day_status = HEALTH_STATUS_CRITICAL
                elif cum >= DEFAULT_HEALTH_THRESHOLD_WARNING:
                    day_status = HEALTH_STATUS_WARNING
                elif cum >= DEFAULT_HEALTH_THRESHOLD_WATCH:
                    day_status = HEALTH_STATUS_WATCH
                else:
                    day_status = HEALTH_STATUS_NORMAL

                forecast.append(
                    {
                        "day": d,
                        "date": date_str,
                        "daily_fault_probability": daily_p,
                        "cumulative_fault_probability": cum,
                        "status": day_status,
                        "suspected_subsystem": subsystem,
                    }
                )

        return forecast

    def evaluate_telemetry(
        self,
        telemetry_df: pd.DataFrame,
        asset_id: int = 0,
        horizon_days: int = DEFAULT_FORECAST_HORIZON_DAYS,
    ) -> dict[str, Any]:
        """
        Score a multi-interval SCADA observation window for impending failure risk.

        :param telemetry_df: Chronologically sorted SCADA observations.
        :param asset_id: Turbine asset identifier.
        :param horizon_days: Days ahead to project daily risk probabilities.

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
                "subsystem_risks": {},
                "daily_forecast": self.compute_daily_forecast(
                    0.0, None, None, horizon_days=horizon_days
                ),
                "recommended_action": _get_recommended_action(None, HEALTH_STATUS_NORMAL),
                "anomalous_sensors": [],
                "records_evaluated": 0,
            }

        features = extract_maintenance_features(telemetry_df)
        for col in self.feature_columns:
            if col not in features.columns:
                features[col] = 0.0

        x_eval = features[self.feature_columns].tail(1)
        prob = float(self.model.predict_proba(x_eval)[0, 1])

        # Subsystem risk probabilities from multi-class model
        subsystem_risks: dict[str, float] = {}
        if self.subsystem_model is not None:
            subsys_probs = self.subsystem_model.predict_proba(x_eval)[0]
            for cls_name, p in zip(self.subsystem_model.classes_, subsys_probs):
                name_str = str(cls_name)
                if name_str != "Normal":
                    subsystem_risks[name_str] = round(float(p), 3)

        # Physical safety rules and component diagnostics
        latest = telemetry_df.iloc[-1]
        ambient = float(latest.get(SENSOR_AMBIENT_TEMP, 20.0))
        de_temp = float(latest.get(SENSOR_BEARING_DE, 0.0))
        nde_temp = float(latest.get(SENSOR_BEARING_NDE, 0.0))
        gb_temp = float(latest.get(SENSOR_GEARBOX_BEARING, 0.0))
        gb_oil = float(latest.get(SENSOR_GEARBOX_OIL, 0.0))
        hyd_oil = float(latest.get(SENSOR_HYDRAULIC_OIL, 0.0))
        trans_l1 = float(latest.get(SENSOR_TRANSFORMER_L1, 0.0))
        trans_l2 = float(latest.get(SENSOR_TRANSFORMER_L2, 0.0))
        trans_l3 = float(latest.get(SENSOR_TRANSFORMER_L3, 0.0))
        trans_max = max(trans_l1, trans_l2, trans_l3)
        trans_diff = trans_max - min(trans_l1, trans_l2, trans_l3)

        anomalous_sensors: list[str] = []

        # 1. Bearing physical safety check
        if de_temp > 75.0 or (de_temp - ambient > 45.0) or (de_temp > nde_temp + 20.0):
            anomalous_sensors.append(f"{SENSOR_BEARING_DE} ({de_temp:.1f}°C)")
            subsystem_risks["Generator Bearing"] = max(
                subsystem_risks.get("Generator Bearing", 0.0),
                0.94 if de_temp > 80.0 else 0.72,
            )

        # 2. Gearbox physical safety check
        if gb_temp > 70.0 or gb_oil > 62.0:
            anomalous_sensors.append(f"{SENSOR_GEARBOX_BEARING} ({gb_temp:.1f}°C)")
            subsystem_risks["Gearbox"] = max(
                subsystem_risks.get("Gearbox", 0.0),
                0.92 if gb_temp > 75.0 else 0.68,
            )

        # 3. Hydraulic group physical safety check
        if hyd_oil > 50.0 or (hyd_oil - ambient > 25.0):
            anomalous_sensors.append(f"{SENSOR_HYDRAULIC_OIL} ({hyd_oil:.1f}°C)")
            subsystem_risks["Hydraulic Group"] = max(
                subsystem_risks.get("Hydraulic Group", 0.0),
                0.88 if hyd_oil > 53.0 else 0.65,
            )

        # 4. Transformer physical safety check
        if trans_max > 85.0 or trans_diff > 15.0:
            anomalous_sensors.append(f"Transformer ({trans_max:.1f}°C, Δ{trans_diff:.1f}°C)")
            subsystem_risks["Transformer"] = max(
                subsystem_risks.get("Transformer", 0.0),
                0.95 if trans_max > 95.0 else 0.70,
            )

        # Fuse ML probability with highest physical subsystem risk
        max_subsys_risk = max(subsystem_risks.values()) if subsystem_risks else 0.0
        combined_prob = max(prob, max_subsys_risk)
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
        suspected_subsystem: str | None = None

        if combined_prob >= DEFAULT_HEALTH_THRESHOLD_WATCH:
            days_to_failure = round(float(max(1.0, (1.0 - combined_prob) * 9.0 + 1.2)), 1)
            if subsystem_risks:
                suspected_subsystem = max(subsystem_risks.items(), key=lambda item: item[1])[0]
            else:
                suspected_subsystem = "Drivetrain Mechanical Group"

        recommended_action = _get_recommended_action(suspected_subsystem, status)

        # Determine reference date from telemetry time_stamp if available
        last_ts = None
        if "time_stamp" in telemetry_df.columns:
            try:
                raw_ts = telemetry_df["time_stamp"].iloc[-1]
                if isinstance(raw_ts, str):
                    last_ts = datetime.fromisoformat(raw_ts)
                elif isinstance(raw_ts, datetime):
                    last_ts = raw_ts
            except Exception:
                last_ts = None

        daily_forecast = self.compute_daily_forecast(
            fault_prob=combined_prob,
            days_to_failure=days_to_failure,
            subsystem=suspected_subsystem,
            start_date=last_ts,
            horizon_days=horizon_days,
        )

        return {
            "asset_id": asset_id,
            "status": status,
            "health_score": health_score,
            "fault_probability": round(combined_prob, 3),
            "estimated_days_to_failure": days_to_failure,
            "suspected_subsystem": suspected_subsystem,
            "subsystem_risks": subsystem_risks,
            "daily_forecast": daily_forecast,
            "recommended_action": recommended_action,
            "anomalous_sensors": anomalous_sensors,
            "records_evaluated": len(telemetry_df),
        }


__all__ = ["TurbineHealthPredictor", "resolve_maintenance_models_dir"]
