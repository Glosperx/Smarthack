"""
# Wind power predictor

Inference engine and Open-Meteo weather integration for wind turbine power forecasting.

The following can be imported from this module:
- `WindPowerPredictor`
- `resolve_models_dir`
"""

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from smarthack.config import wind_models_dir
from smarthack.wind.constants import (
    DEFAULT_FORECAST_DAYS,
    DEFAULT_LATITUDE,
    DEFAULT_LONGITUDE,
    DEFAULT_TURBINE_CAPACITY_KW,
    OPEN_METEO_API_URL,
    WEIGHT_CATBOOST,
    WEIGHT_LIGHTGBM,
    WEIGHT_XGBOOST,
)
from smarthack.wind.features import add_features, get_feature_columns

logger = logging.getLogger(__name__)


def resolve_models_dir(models_dir: str | Path | None = None) -> Path:
    """
    Resolve the filesystem path where model artifacts are stored.

    :param models_dir: Explicit path to directory, or None to use configuration.

    :returns path: Resolved absolute or existing Path.
    """
    if models_dir is not None:
        return Path(models_dir)
    return wind_models_dir()


class WindPowerPredictor:
    """
    Inference engine predicting wind turbine capacity factor and power generation.
    """

    def __init__(
        self,
        model: Any = None,
        feature_cols: list[str] | None = None,
        ensemble_models: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the predictor with an optional pre-loaded model or ensemble.

        :param model: Fitted estimator or string identifier such as `"tri_ensemble"`.
        :param feature_cols: Ordered list of feature names expected by the model.
        :param ensemble_models: Dictionary containing estimators keyed by family.
        """
        self.model = model
        self.feature_cols = feature_cols
        self.ensemble_models = ensemble_models or {}

    def load_model(
        self, model_path: str | Path, feature_cols_path: str | Path | None = None
    ) -> None:
        """
        Load a single serialized model file from disk (.json, .cbm, or .joblib).

        :param model_path: Path to serialized model file.
        :param feature_cols_path: Optional path to feature columns JSON file.

        :returns: None.
        :raises FileNotFoundError: If model_path does not exist.
        """
        path = Path(model_path)
        if not path.is_file():
            raise FileNotFoundError(f"Model file not found: {path}")

        suffix = path.suffix.lower()
        if suffix == ".json":
            # Deferred import to keep base imports lean
            import xgboost as xgb

            xgb_regressor = xgb.XGBRegressor()
            xgb_regressor.load_model(str(path))
            self.model = xgb_regressor
            if hasattr(self.model, "feature_names_in_"):
                self.feature_cols = list(self.model.feature_names_in_)
        elif suffix == ".cbm":
            from catboost import CatBoostRegressor

            cb_regressor = CatBoostRegressor()
            cb_regressor.load_model(str(path))
            self.model = cb_regressor
        else:
            import joblib

            self.model = joblib.load(path)

        if feature_cols_path is not None:
            cols_file = Path(feature_cols_path)
            if cols_file.is_file():
                self.feature_cols = json.loads(cols_file.read_text(encoding="utf-8"))

        logger.info("Loaded model from %s", path)

    def load_tri_ensemble(self, models_dir: str | Path | None = None) -> None:
        """
        Load the winning Tri-Ensemble (LightGBM + XGBoost + CatBoost).

        :param models_dir: Directory holding model artifacts and feature columns JSON.

        :returns: None.
        :raises FileNotFoundError: When any required model artifact is missing.
        """
        base_dir = resolve_models_dir(models_dir)

        features_path = base_dir / "feature_columns.json"
        xgb_path = base_dir / "xgboost_wind_power.json"
        lgb_path = base_dir / "lightgbm_wind_power.joblib"
        cb_path = base_dir / "catboost_wind_power.cbm"

        for required in (features_path, xgb_path, lgb_path, cb_path):
            if not required.is_file():
                raise FileNotFoundError(f"Missing required artifact: {required}")

        self.feature_cols = json.loads(features_path.read_text(encoding="utf-8"))

        # Heavy library imports deferred inside loading method
        from catboost import CatBoostRegressor
        import joblib
        import xgboost as xgb

        xgb_model = xgb.XGBRegressor()
        xgb_model.load_model(str(xgb_path))

        lgb_model = joblib.load(lgb_path)

        cb_model = CatBoostRegressor()
        cb_model.load_model(str(cb_path))

        self.ensemble_models = {
            "xgb": xgb_model,
            "lgb": lgb_model,
            "cb": cb_model,
        }
        self.model = "tri_ensemble"
        logger.info("Loaded Tri-Ensemble from %s", base_dir)

    def predict(
        self,
        weather_df: pd.DataFrame,
        location_id: int | None = 1,
    ) -> np.ndarray:
        """
        Predict normalized turbine power capacity factor [0.0, 1.0] from weather observations.

        :param weather_df: DataFrame containing raw meteorological forecast variables.
        :param location_id: Optional location ID for one-hot encoded profile (1-4).

        :returns predictions: Array of predicted capacity factors clipped to [0.0, 1.0].
        :raises ValueError: When no model is loaded.
        """
        if self.model is None:
            raise ValueError("No model loaded. Call load_model() or load_tri_ensemble() first.")

        featured_df = add_features(weather_df, is_training=False)

        if self.feature_cols is not None:
            for col in self.feature_cols:
                if col.startswith("loc_") and col not in featured_df.columns:
                    if location_id is not None:
                        featured_df[col] = 1.0 if col == f"loc_{location_id}" else 0.0
                    else:
                        featured_df[col] = 0.25
            cols_to_use = [c for c in self.feature_cols if c in featured_df.columns]
            x_matrix = featured_df[cols_to_use]
        else:
            cols_to_use = get_feature_columns(featured_df)
            x_matrix = featured_df[cols_to_use]

        if self.model == "tri_ensemble":
            p_xgb = self.ensemble_models["xgb"].predict(x_matrix)
            p_lgb = self.ensemble_models["lgb"].predict(x_matrix)
            p_cb = self.ensemble_models["cb"].predict(x_matrix)
            preds = WEIGHT_LIGHTGBM * p_lgb + WEIGHT_XGBOOST * p_xgb + WEIGHT_CATBOOST * p_cb
        else:
            preds = self.model.predict(x_matrix)

        return np.clip(preds, 0.0, 1.0)

    @staticmethod
    def fetch_open_meteo_forecast(
        latitude: float = DEFAULT_LATITUDE,
        longitude: float = DEFAULT_LONGITUDE,
        forecast_days: int = DEFAULT_FORECAST_DAYS,
    ) -> pd.DataFrame:
        """
        Fetch hourly meteorological weather forecast from Open-Meteo REST API.

        :param latitude: GPS latitude in decimal degrees.
        :param longitude: GPS longitude in decimal degrees.
        :param forecast_days: Number of forecast days ahead (1 to 16).

        :returns weather_df: Hourly atmospheric forecast DataFrame.
        :raises requests.RequestException: When the API request fails.
        """
        params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": [
                "temperature_2m",
                "relative_humidity_2m",
                "dew_point_2m",
                "wind_speed_10m",
                "wind_speed_100m",
                "wind_direction_10m",
                "wind_direction_100m",
                "wind_gusts_10m",
            ],
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "ms",
            "forecast_days": forecast_days,
            "timezone": "UTC",
        }

        response = requests.get(OPEN_METEO_API_URL, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        hourly = data["hourly"]
        df = pd.DataFrame(
            {
                "Time": hourly["time"],
                "temperature_2m": hourly["temperature_2m"],
                "relativehumidity_2m": hourly["relative_humidity_2m"],
                "dewpoint_2m": hourly["dew_point_2m"],
                "windspeed_10m": hourly["wind_speed_10m"],
                "windspeed_100m": hourly["wind_speed_100m"],
                "winddirection_10m": hourly["wind_direction_10m"],
                "winddirection_100m": hourly["wind_direction_100m"],
                "windgusts_10m": hourly["wind_gusts_10m"],
            }
        )
        df["Time"] = pd.to_datetime(df["Time"])
        return df

    def predict_forecast(
        self,
        latitude: float = DEFAULT_LATITUDE,
        longitude: float = DEFAULT_LONGITUDE,
        forecast_days: int = DEFAULT_FORECAST_DAYS,
        capacity_kw: float = DEFAULT_TURBINE_CAPACITY_KW,
        location_id: int | None = 1,
    ) -> pd.DataFrame:
        """
        Fetch real-time weather and compute hourly power forecasts in physical units.

        :param latitude: Site latitude in decimal degrees.
        :param longitude: Site longitude in decimal degrees.
        :param forecast_days: Number of forecast days (1 to 16).
        :param capacity_kw: Rated nameplate capacity of the turbine/farm in kW.
        :param location_id: Optional location profile identifier.

        :returns forecast_df: Enriched forecast with capacity factor and kW/MW columns.
        """
        df_weather = self.fetch_open_meteo_forecast(latitude, longitude, forecast_days)
        preds = self.predict(df_weather, location_id=location_id)

        df_weather["predicted_capacity_factor"] = preds
        df_weather["capacity_factor_percent"] = (preds * 100.0).round(2)
        df_weather["power_kw"] = (preds * capacity_kw).round(2)
        df_weather["power_mw"] = (df_weather["power_kw"] / 1000.0).round(4)

        return df_weather


__all__ = ["WindPowerPredictor", "resolve_models_dir"]
