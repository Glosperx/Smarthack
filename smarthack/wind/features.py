"""
# Wind feature engineering

Physics-informed feature engineering and sequential atmospheric dynamics for wind turbines.

The following can be imported from this module:
- `RAW_WEATHER_COLUMNS`
- `add_features`
- `get_feature_columns`
"""

import numpy as np
import pandas as pd

from smarthack.wind.constants import CUT_IN_WIND_SPEED, CUT_OUT_WIND_SPEED, RATED_WIND_SPEED

#: Meteorological columns expected from the weather forecast or observation feed.
RAW_WEATHER_COLUMNS: list[str] = [
    "temperature_2m",
    "relativehumidity_2m",
    "dewpoint_2m",
    "windspeed_10m",
    "windspeed_100m",
    "winddirection_10m",
    "winddirection_100m",
    "windgusts_10m",
]


def add_features(df: pd.DataFrame, is_training: bool = False) -> pd.DataFrame:
    """
    Compute physics-informed features and sequential dynamics from raw weather inputs.

    Calculates diurnal and seasonal cycles, air density proxy, kinetic energy
    and power density, vertical wind shear exponent, gust turbulence, cyclical
    wind vectors, Betz-law operational regimes, and sequential temporal dynamics.

    :param df: Input DataFrame containing Time and RAW_WEATHER_COLUMNS.
    :param is_training: Whether training mode is active (preserves target columns).

    :returns enriched: Enriched DataFrame containing all 46 engineered features.
    """
    data = df.copy()

    # 1. Parse Datetime features if Time column exists
    if "Time" in data.columns:
        if not pd.api.types.is_datetime64_any_dtype(data["Time"]):
            data["Time"] = pd.to_datetime(data["Time"])

        hours = data["Time"].dt.hour
        data["sin_hour"] = np.sin(2.0 * np.pi * hours / 24.0)
        data["cos_hour"] = np.cos(2.0 * np.pi * hours / 24.0)

        months = data["Time"].dt.month - 1
        data["sin_month"] = np.sin(2.0 * np.pi * months / 12.0)
        data["cos_month"] = np.cos(2.0 * np.pi * months / 12.0)

        if hasattr(data["Time"].dt, "day_of_year"):
            day_of_year = data["Time"].dt.day_of_year
        else:
            day_of_year = data["Time"].dt.dayofyear
        data["sin_doy"] = np.sin(2.0 * np.pi * day_of_year / 365.25)
        data["cos_doy"] = np.cos(2.0 * np.pi * day_of_year / 365.25)

    # 2. Temperature conversions and Air Density Proxy
    temp_k = (data["temperature_2m"] - 32.0) * (5.0 / 9.0) + 273.15
    data["air_density_proxy"] = 353.05 / np.maximum(temp_k, 200.0)
    data["temp_dewpoint_spread"] = data["temperature_2m"] - data["dewpoint_2m"]

    # 3. Kinetic Energy and Non-Linear Wind Speed Powers
    w100 = np.maximum(data["windspeed_100m"], 0.0)
    w10 = np.maximum(data["windspeed_10m"], 0.0)

    data["windspeed_100m_sq"] = w100**2
    data["windspeed_100m_cube"] = w100**3
    data["windspeed_10m_cube"] = w10**3

    # Theoretical Wind Power Density: 0.5 * rho * v^3 (W/m^2)
    data["wind_power_density_100m"] = 0.5 * data["air_density_proxy"] * data["windspeed_100m_cube"]

    # 4. Vertical Wind Shear (between 10m and 100m hub heights)
    eps = 0.05
    data["wind_shear_exponent"] = (
        np.log(np.maximum(w100, eps) / np.maximum(w10, eps)) / np.log(100.0 / 10.0)
    ).clip(-1.0, 2.0)
    data["wind_shear_diff"] = w100 - w10
    data["wind_shear_ratio"] = w100 / (w10 + 0.1)

    # 5. Turbulence & Gust Ratios
    gusts = np.maximum(data["windgusts_10m"], 0.0)
    data["gust_ratio_10m"] = gusts / (w10 + 0.1)
    data["gust_diff_10m"] = gusts - w10

    # 6. Circular Wind Direction (Cyclical Encoding)
    rad_100 = np.radians(data["winddirection_100m"])
    rad_10 = np.radians(data["winddirection_10m"])

    data["sin_winddir_100m"] = np.sin(rad_100)
    data["cos_winddir_100m"] = np.cos(rad_100)
    data["sin_winddir_10m"] = np.sin(rad_10)
    data["cos_winddir_10m"] = np.cos(rad_10)

    # Wind Veer (Directional change between 10m and 100m)
    dir_diff = (data["winddirection_100m"] - data["winddirection_10m"] + 180.0) % 360.0 - 180.0
    data["sin_wind_veer"] = np.sin(np.radians(dir_diff))
    data["cos_wind_veer"] = np.cos(np.radians(dir_diff))

    # 7. Meteorological Wind Vector Components
    data["wind_u_100m"] = -w100 * data["sin_winddir_100m"]
    data["wind_v_100m"] = -w100 * data["cos_winddir_100m"]
    data["wind_u_10m"] = -w10 * data["sin_winddir_10m"]
    data["wind_v_10m"] = -w10 * data["cos_winddir_10m"]

    # 8. Physical Piecewise Operational Regimes
    data["is_below_cutin"] = (w100 < CUT_IN_WIND_SPEED).astype(float)
    data["is_above_rated"] = (w100 >= RATED_WIND_SPEED).astype(float)
    data["is_above_cutout"] = (w100 >= CUT_OUT_WIND_SPEED).astype(float)
    data["physical_ramp_cubic"] = (
        np.clip((w100 - CUT_IN_WIND_SPEED) / (RATED_WIND_SPEED - CUT_IN_WIND_SPEED), 0.0, 1.0) ** 3
    )

    # 9. Sequential Temporal Dynamics
    group_col = "location_id" if "location_id" in data.columns else None
    if group_col:
        grouper = data.groupby(group_col)
        data["w100_lag1"] = grouper["windspeed_100m"].shift(1).bfill()
        data["w100_lead1"] = grouper["windspeed_100m"].shift(-1).ffill()
        data["w100_diff1"] = data["windspeed_100m"] - data["w100_lag1"]
        data["w100_roll_mean_3h"] = (
            grouper["windspeed_100m"].rolling(3, min_periods=1).mean().reset_index(drop=True)
        )
        data["w100_roll_std_3h"] = (
            grouper["windspeed_100m"]
            .rolling(3, min_periods=1)
            .std()
            .fillna(0.0)
            .reset_index(drop=True)
        )
        data["w100_roll_mean_6h"] = (
            grouper["windspeed_100m"].rolling(6, min_periods=1).mean().reset_index(drop=True)
        )
        data["temp_diff_3h"] = data["temperature_2m"] - grouper["temperature_2m"].shift(3).bfill()
    else:
        data["w100_lag1"] = data["windspeed_100m"].shift(1).bfill()
        data["w100_lead1"] = data["windspeed_100m"].shift(-1).ffill()
        data["w100_diff1"] = data["windspeed_100m"] - data["w100_lag1"]
        data["w100_roll_mean_3h"] = data["windspeed_100m"].rolling(3, min_periods=1).mean()
        data["w100_roll_std_3h"] = (
            data["windspeed_100m"].rolling(3, min_periods=1).std().fillna(0.0)
        )
        data["w100_roll_mean_6h"] = data["windspeed_100m"].rolling(6, min_periods=1).mean()
        data["temp_diff_3h"] = data["temperature_2m"] - data["temperature_2m"].shift(3).bfill()

    return data


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    """
    Return the list of engineered feature columns excluding identifiers and target.

    :param df: DataFrame containing features, metadata or target columns.

    :returns feature_names: Clean list of columns to be fed to models.
    """
    excluded = {"Time", "Power", "location_id", "Location"}
    return [c for c in df.columns if c not in excluded]


__all__ = ["RAW_WEATHER_COLUMNS", "add_features", "get_feature_columns"]
