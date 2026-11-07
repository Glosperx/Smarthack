"""
# Wind power forecasting

Forecasting pipeline, physics-informed feature extraction, machine learning
models, training benchmark, and agent tool interface for wind turbine generation.

The following can be imported from this module:
- `RAW_WEATHER_COLUMNS`
- `WindPowerPredictor`
- `add_features`
- `evaluate_predictions`
- `format_forecast_table`
- `get_feature_columns`
- `get_wind_tool_spec`
- `load_dataset`
- `predict_wind_power`
- `resolve_data_dir`
- `resolve_models_dir`
- `train_and_benchmark`
"""

from smarthack.wind.agent_tool import format_forecast_table, get_wind_tool_spec, predict_wind_power
from smarthack.wind.features import RAW_WEATHER_COLUMNS, add_features, get_feature_columns
from smarthack.wind.predictor import WindPowerPredictor, resolve_models_dir
from smarthack.wind.training import (
    evaluate_predictions,
    load_dataset,
    resolve_data_dir,
    train_and_benchmark,
)

__all__ = [
    "RAW_WEATHER_COLUMNS",
    "WindPowerPredictor",
    "add_features",
    "evaluate_predictions",
    "format_forecast_table",
    "get_feature_columns",
    "get_wind_tool_spec",
    "load_dataset",
    "predict_wind_power",
    "resolve_data_dir",
    "resolve_models_dir",
    "train_and_benchmark",
]
