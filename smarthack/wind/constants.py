"""
# Wind forecasting constants

Scalars and physical thresholds for wind power forecasting and turbine regimes.

The following can be imported from this module:
- `CUT_IN_WIND_SPEED`
- `CUT_OUT_WIND_SPEED`
- `DEFAULT_FORECAST_DAYS`
- `DEFAULT_LATITUDE`
- `DEFAULT_LONGITUDE`
- `DEFAULT_TURBINE_CAPACITY_KW`
- `OPEN_METEO_API_URL`
- `RATED_WIND_SPEED`
- `WEIGHT_CATBOOST`
- `WEIGHT_LIGHTGBM`
- `WEIGHT_XGBOOST`
"""

#: Wind speed (m/s) below which modern turbines cannot generate electricity.
CUT_IN_WIND_SPEED: float = 3.0

#: Wind speed (m/s) at which a turbine reaches rated plate capacity.
RATED_WIND_SPEED: float = 13.0

#: Cut-out wind speed (m/s) triggering protective automatic shutoff.
CUT_OUT_WIND_SPEED: float = 25.0

#: Standard default turbine capacity in kilowatts (2500 kW = 2.5 MW).
DEFAULT_TURBINE_CAPACITY_KW: float = 2500.0

#: Default forecast horizon in days.
DEFAULT_FORECAST_DAYS: int = 3

#: Default latitude for Texas Panhandle wind farm corridor.
DEFAULT_LATITUDE: float = 35.2

#: Default longitude for Texas Panhandle wind farm corridor.
DEFAULT_LONGITUDE: float = -101.8

#: Public REST endpoint for hourly atmospheric forecasts.
OPEN_METEO_API_URL: str = "https://api.open-meteo.com/v1/forecast"

#: Blending weight for LightGBM in the Tri-Ensemble.
WEIGHT_LIGHTGBM: float = 0.40

#: Blending weight for XGBoost in the Tri-Ensemble.
WEIGHT_XGBOOST: float = 0.40

#: Blending weight for CatBoost in the Tri-Ensemble.
WEIGHT_CATBOOST: float = 0.20

__all__ = [
    "CUT_IN_WIND_SPEED",
    "CUT_OUT_WIND_SPEED",
    "DEFAULT_FORECAST_DAYS",
    "DEFAULT_LATITUDE",
    "DEFAULT_LONGITUDE",
    "DEFAULT_TURBINE_CAPACITY_KW",
    "OPEN_METEO_API_URL",
    "RATED_WIND_SPEED",
    "WEIGHT_CATBOOST",
    "WEIGHT_LIGHTGBM",
    "WEIGHT_XGBOOST",
]
