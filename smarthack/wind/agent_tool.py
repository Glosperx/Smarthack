"""
# Wind agent tool and interface API

High-level tool function and JSON schema definition for LLM agents and UI interfaces.

The following can be imported from this module:
- `format_forecast_table`
- `get_wind_tool_spec`
- `predict_wind_power`
"""

import logging
from pathlib import Path
from typing import Any

from smarthack.wind.constants import (
    DEFAULT_FORECAST_DAYS,
    DEFAULT_LATITUDE,
    DEFAULT_LONGITUDE,
    DEFAULT_TURBINE_CAPACITY_KW,
)
from smarthack.wind.predictor import WindPowerPredictor, resolve_models_dir

logger = logging.getLogger(__name__)


def get_wind_tool_spec() -> dict[str, Any]:
    """
    Return the function-calling JSON schema specification for LLM agents.

    :returns spec: Standard OpenAI/Gemini-compatible function tool definition.
    """
    return {
        "type": "function",
        "function": {
            "name": "predict_wind_power",
            "description": (
                "Predict hourly wind farm electricity generation (kW/MW and capacity factor) "
                "for any global GPS coordinates using real-time atmospheric weather forecasts "
                "and physics-informed gradient boosting models."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "latitude": {
                        "type": "number",
                        "description": "Latitude of the wind turbine or wind farm (e.g. 35.2).",
                    },
                    "longitude": {
                        "type": "number",
                        "description": "Longitude of the wind turbine or wind farm (e.g. -101.8).",
                    },
                    "forecast_days": {
                        "type": "integer",
                        "description": "Number of forecast days ahead (1 to 16, default 3).",
                        "default": 3,
                    },
                    "capacity_kw": {
                        "type": "number",
                        "description": (
                            "Rated nameplate turbine or farm capacity in kilowatts "
                            "(default 2500 kW = 2.5 MW)."
                        ),
                        "default": 2500.0,
                    },
                },
                "required": ["latitude", "longitude"],
            },
        },
    }


def predict_wind_power(
    latitude: float = DEFAULT_LATITUDE,
    longitude: float = DEFAULT_LONGITUDE,
    forecast_days: int = DEFAULT_FORECAST_DAYS,
    capacity_kw: float = DEFAULT_TURBINE_CAPACITY_KW,
    location_id: int | None = 1,
    models_dir: str | Path | None = None,
    use_ensemble: bool = True,
) -> dict[str, Any]:
    """
    Execute end-to-end wind power prediction for a location and forecast horizon.

    Designed for seamless consumption by autonomous LLM agents or web dashboards.
    Fetches weather, evaluates the physics-informed pipeline, and returns
    structured statistics along with full hourly time-series data.

    :param latitude: GPS latitude of the site.
    :param longitude: GPS longitude of the site.
    :param forecast_days: Number of days to forecast (1 to 16).
    :param capacity_kw: Rated nameplate capacity in kW.
    :param location_id: Optional turbine profile identifier (1 to 4).
    :param models_dir: Optional custom path to model artifacts.
    :param use_ensemble: Whether to use Tri-Ensemble (falls back to single XGBoost).

    :returns result: Structured payload containing summary metrics and hourly records.
    """
    resolved_dir = resolve_models_dir(models_dir)
    predictor = WindPowerPredictor()

    catboost_path = resolved_dir / "catboost_wind_power.cbm"
    if use_ensemble and catboost_path.is_file():
        predictor.load_tri_ensemble(resolved_dir)
    else:
        xgb_path = resolved_dir / "xgboost_wind_power.json"
        feat_path = resolved_dir / "feature_columns.json"
        predictor.load_model(xgb_path, feat_path)

    forecast_df = predictor.predict_forecast(
        latitude=latitude,
        longitude=longitude,
        forecast_days=forecast_days,
        capacity_kw=capacity_kw,
        location_id=location_id,
    )

    total_kwh = float(forecast_df["power_kw"].sum())
    total_mwh = round(total_kwh / 1000.0, 3)
    avg_cf = round(float(forecast_df["capacity_factor_percent"].mean()), 2)
    max_cf = round(float(forecast_df["capacity_factor_percent"].max()), 2)
    max_kw = round(float(forecast_df["power_kw"].max()), 1)
    max_mw = round(max_kw / 1000.0, 3)
    avg_wind = round(float(forecast_df["windspeed_100m"].mean()), 2)
    max_wind = round(float(forecast_df["windspeed_100m"].max()), 2)

    hourly_records: list[dict[str, Any]] = []
    for _, row in forecast_df.iterrows():
        time_str = (
            row["Time"].isoformat() if hasattr(row["Time"], "isoformat") else str(row["Time"])
        )
        hourly_records.append(
            {
                "time": time_str,
                "wind_speed_100m_ms": float(row["windspeed_100m"]),
                "wind_direction_100m_deg": float(row["winddirection_100m"]),
                "temperature_2m_f": float(row["temperature_2m"]),
                "capacity_factor_percent": float(row["capacity_factor_percent"]),
                "power_kw": float(row["power_kw"]),
                "power_mw": float(row["power_mw"]),
            }
        )

    summary_text = (
        f"Wind power forecast for ({latitude:.4f}, {longitude:.4f}) over {forecast_days} days: "
        f"Projected generation is {total_mwh:,.2f} MWh ({total_kwh:,.0f} kWh) with an average "
        f"capacity factor of {avg_cf:.1f}% (peak {max_cf:.1f}%, peak output {max_mw:.2f} MW). "
        f"Average wind speed at 100m hub height is {avg_wind:.1f} m/s (peak {max_wind:.1f} m/s)."
    )

    return {
        "status": "success",
        "location": {
            "latitude": latitude,
            "longitude": longitude,
        },
        "forecast_days": forecast_days,
        "capacity_kw": capacity_kw,
        "capacity_mw": round(capacity_kw / 1000.0, 3),
        "model_used": predictor.model,
        "summary": {
            "average_capacity_factor_percent": avg_cf,
            "peak_capacity_factor_percent": max_cf,
            "total_generation_kwh": round(total_kwh, 1),
            "total_generation_mwh": total_mwh,
            "peak_power_kw": max_kw,
            "peak_power_mw": max_mw,
            "average_wind_speed_100m_ms": avg_wind,
            "peak_wind_speed_100m_ms": max_wind,
        },
        "summary_text": summary_text,
        "hourly_forecast": hourly_records,
    }


def format_forecast_table(result: dict[str, Any], max_rows: int = 24) -> str:
    """
    Format hourly forecast records into a clean text table suitable for console display.

    :param result: Dictionary returned by predict_wind_power.
    :param max_rows: Maximum number of hourly rows to display.

    :returns table: Formatted text table.
    """
    records = result.get("hourly_forecast", [])[:max_rows]
    header = f"{'Time':<20} | {'Wind 100m (m/s)':<16} | {'Cap Factor %':<14} | {'Power (kW)':<12} | {'Power (MW)':<10}"
    divider = "-" * len(header)
    rows = [header, divider]
    for r in records:
        time_part = r["time"].replace("T", " ")[:19]
        row_str = (
            f"{time_part:<20} | "
            f"{r['wind_speed_100m_ms']:<16.1f} | "
            f"{r['capacity_factor_percent']:<14.1f} | "
            f"{r['power_kw']:<12.1f} | "
            f"{r['power_mw']:<10.3f}"
        )
        rows.append(row_str)
    return "\n".join(rows)


__all__ = ["format_forecast_table", "get_wind_tool_spec", "predict_wind_power"]
