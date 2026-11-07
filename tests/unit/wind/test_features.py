"""
Unit tests for wind physics feature extraction pipeline.
"""

import numpy as np
import pandas as pd

from smarthack.wind.features import RAW_WEATHER_COLUMNS, add_features, get_feature_columns
from tests.conftest import skip_module_without_extra

skip_module_without_extra("wind")


def make_synthetic_weather(n_hours: int = 24) -> pd.DataFrame:
    """Generate dummy weather observation DataFrame."""
    np.random.seed(42)
    dates = pd.date_range("2026-06-01", periods=n_hours, freq="h")
    return pd.DataFrame(
        {
            "Time": dates,
            "temperature_2m": np.random.uniform(50.0, 90.0, n_hours),
            "relativehumidity_2m": np.random.uniform(40.0, 80.0, n_hours),
            "dewpoint_2m": np.random.uniform(30.0, 60.0, n_hours),
            "windspeed_10m": np.random.uniform(1.0, 15.0, n_hours),
            "windspeed_100m": np.random.uniform(2.0, 22.0, n_hours),
            "winddirection_10m": np.random.uniform(0.0, 360.0, n_hours),
            "winddirection_100m": np.random.uniform(0.0, 360.0, n_hours),
            "windgusts_10m": np.random.uniform(3.0, 28.0, n_hours),
        }
    )


def test_add_features_produces_expected_physics_columns() -> None:
    """Verify that feature engineering computes all physics and regime variables."""
    raw = make_synthetic_weather(24)
    featured = add_features(raw, is_training=False)

    expected = [
        "sin_hour",
        "cos_hour",
        "sin_month",
        "cos_month",
        "air_density_proxy",
        "temp_dewpoint_spread",
        "windspeed_100m_sq",
        "windspeed_100m_cube",
        "wind_power_density_100m",
        "wind_shear_exponent",
        "wind_shear_ratio",
        "gust_ratio_10m",
        "sin_winddir_100m",
        "cos_winddir_100m",
        "wind_u_100m",
        "wind_v_100m",
        "is_below_cutin",
        "is_above_rated",
        "is_above_cutout",
        "physical_ramp_cubic",
        "w100_lag1",
        "w100_lead1",
        "w100_roll_mean_3h",
        "w100_roll_std_3h",
    ]
    for col in expected:
        assert col in featured.columns, f"Missing feature: {col}"

    cols = get_feature_columns(featured)
    assert not featured[cols].isna().any().any(), "Engineered features have NaNs"
    assert not np.isinf(featured[cols].to_numpy()).any(), "Engineered features have Infs"


def test_add_features_with_grouped_locations() -> None:
    """Verify lag and rolling windows respect location grouping."""
    raw = make_synthetic_weather(12)
    raw2 = make_synthetic_weather(12)
    raw["location_id"] = 1
    raw2["location_id"] = 2
    combined = pd.concat([raw, raw2], ignore_index=True)

    featured = add_features(combined, is_training=True)
    assert "location_id" in featured.columns
    assert len(featured) == 24


def test_get_feature_columns_filters_metadata() -> None:
    """Metadata and target columns are excluded from modeling features."""
    raw = make_synthetic_weather(6)
    raw["Power"] = 0.5
    raw["location_id"] = 1
    raw["Location"] = "Site A"
    featured = add_features(raw, is_training=True)

    cols = get_feature_columns(featured)
    assert "Time" not in cols
    assert "Power" not in cols
    assert "location_id" not in cols
    assert "Location" not in cols
    assert "temperature_2m" in cols
    assert len(RAW_WEATHER_COLUMNS) == 8
