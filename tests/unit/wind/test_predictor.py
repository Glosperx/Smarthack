"""
Unit tests for wind power prediction engine.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from smarthack.config import wind_models_dir
from smarthack.wind.predictor import WindPowerPredictor, resolve_models_dir
from tests.conftest import skip_module_without_extra
from tests.unit.wind.test_features import make_synthetic_weather

skip_module_without_extra("wind")


def test_resolve_models_dir_defaults_to_config() -> None:
    """resolve_models_dir returns configured directory when none specified."""
    assert resolve_models_dir() == wind_models_dir()
    assert str(resolve_models_dir("custom/dir")) == "custom/dir"


def test_predictor_unloaded_raises_value_error() -> None:
    """Calling predict on unloaded predictor raises ValueError."""
    predictor = WindPowerPredictor()
    df = make_synthetic_weather(10)
    with pytest.raises(ValueError, match="No model loaded"):
        predictor.predict(df)


def test_predictor_missing_file_raises_not_found(tmp_path: Path) -> None:
    """load_model and load_tri_ensemble raise FileNotFoundError on missing files."""
    predictor = WindPowerPredictor()
    with pytest.raises(FileNotFoundError):
        predictor.load_model(tmp_path / "nonexistent.json")
    with pytest.raises(FileNotFoundError):
        predictor.load_tri_ensemble(tmp_path)


def test_predictor_loads_catboost_and_joblib_single_models() -> None:
    """Predictor loads .cbm and .joblib single models directly."""
    models_path = wind_models_dir()
    cb_file = models_path / "catboost_wind_power.cbm"
    lgb_file = models_path / "lightgbm_wind_power.joblib"
    feat_file = models_path / "feature_columns.json"

    if cb_file.is_file():
        p_cb = WindPowerPredictor()
        p_cb.load_model(cb_file, feat_file)
        preds_cb = p_cb.predict(make_synthetic_weather(8), location_id=None)
        assert len(preds_cb) == 8

    if lgb_file.is_file():
        p_lgb = WindPowerPredictor()
        p_lgb.load_model(lgb_file, feat_file)
        preds_lgb = p_lgb.predict(make_synthetic_weather(8))
        assert len(preds_lgb) == 8


def test_predictor_loads_single_xgboost_model() -> None:
    """Predictor loads saved XGBoost JSON model and predicts bounded values."""
    models_path = wind_models_dir()
    xgb_file = models_path / "xgboost_wind_power.json"
    feat_file = models_path / "feature_columns.json"

    if not xgb_file.is_file() or not feat_file.is_file():
        pytest.skip("Trained model files not present in models directory")

    predictor = WindPowerPredictor()
    predictor.load_model(xgb_file, feat_file)

    weather = make_synthetic_weather(16)
    preds = predictor.predict(weather)

    assert len(preds) == 16
    assert (preds >= 0.0).all()
    assert (preds <= 1.0).all()


def test_predictor_loads_tri_ensemble() -> None:
    """Predictor loads LightGBM, XGBoost, and CatBoost models as a Tri-Ensemble."""
    models_path = wind_models_dir()
    cb_file = models_path / "catboost_wind_power.cbm"
    if not cb_file.is_file():
        pytest.skip("CatBoost model artifact not found")

    predictor = WindPowerPredictor()
    predictor.load_tri_ensemble(models_path)

    assert predictor.model == "tri_ensemble"
    assert "xgb" in predictor.ensemble_models
    assert "lgb" in predictor.ensemble_models
    assert "cb" in predictor.ensemble_models

    weather = make_synthetic_weather(20)
    preds = predictor.predict(weather)

    assert len(preds) == 20
    assert (preds >= 0.0).all()
    assert (preds <= 1.0).all()


@patch("requests.get")
def test_fetch_open_meteo_forecast_parses_response(mock_get: MagicMock) -> None:
    """Open-Meteo REST API JSON is parsed into the standard DataFrame."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "hourly": {
            "time": ["2026-06-01T00:00", "2026-06-01T01:00"],
            "temperature_2m": [68.0, 67.5],
            "relative_humidity_2m": [50.0, 52.0],
            "dew_point_2m": [45.0, 46.0],
            "wind_speed_10m": [5.0, 5.5],
            "wind_speed_100m": [8.0, 8.5],
            "wind_direction_10m": [180.0, 185.0],
            "wind_direction_100m": [190.0, 195.0],
            "wind_gusts_10m": [10.0, 11.0],
        }
    }
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    df = WindPowerPredictor.fetch_open_meteo_forecast(
        latitude=35.0, longitude=-101.0, forecast_days=1
    )
    assert len(df) == 2
    assert "Time" in df.columns
    assert "windspeed_100m" in df.columns


@patch.object(WindPowerPredictor, "fetch_open_meteo_forecast")
def test_predict_forecast_adds_power_units(mock_fetch: MagicMock) -> None:
    """predict_forecast converts normalized capacity factor into kW and MW."""
    mock_fetch.return_value = make_synthetic_weather(12)

    class DummyModel:
        def predict(self, X: pd.DataFrame) -> np.ndarray:
            return np.full(len(X), 0.5)

    predictor = WindPowerPredictor(model=DummyModel())
    result = predictor.predict_forecast(capacity_kw=2000.0)

    assert len(result) == 12
    assert (result["predicted_capacity_factor"] == 0.5).all()
    assert (result["capacity_factor_percent"] == 50.0).all()
    assert (result["power_kw"] == 1000.0).all()
    assert (result["power_mw"] == 1.0).all()
