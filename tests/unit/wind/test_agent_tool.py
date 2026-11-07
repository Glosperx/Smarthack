"""
Unit tests for the wind forecasting agent tool and interface adapter.
"""

from unittest.mock import MagicMock, patch

from smarthack.wind.agent_tool import (
    format_forecast_table,
    get_wind_tool_spec,
    predict_wind_power,
)
from tests.conftest import skip_module_without_extra
from tests.unit.wind.test_features import make_synthetic_weather

skip_module_without_extra("wind")


def test_get_wind_tool_spec_schema() -> None:
    """Agent tool spec follows OpenAI/Gemini function calling schema standards."""
    spec = get_wind_tool_spec()
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "predict_wind_power"
    props = spec["function"]["parameters"]["properties"]
    assert "latitude" in props
    assert "longitude" in props
    assert "forecast_days" in props
    assert "capacity_kw" in props
    assert "latitude" in spec["function"]["parameters"]["required"]


@patch("smarthack.wind.predictor.WindPowerPredictor.fetch_open_meteo_forecast")
def test_predict_wind_power_tool_payload(mock_fetch: MagicMock) -> None:
    """Tool execution produces structured JSON summary and time series."""
    mock_fetch.return_value = make_synthetic_weather(24)

    payload = predict_wind_power(
        latitude=35.2,
        longitude=-101.8,
        forecast_days=1,
        capacity_kw=3000.0,
        use_ensemble=True,
    )

    assert payload["status"] == "success"
    assert payload["location"]["latitude"] == 35.2
    assert payload["capacity_kw"] == 3000.0
    assert payload["capacity_mw"] == 3.0
    assert "summary" in payload
    assert "hourly_forecast" in payload
    assert len(payload["hourly_forecast"]) == 24
    assert "summary_text" in payload
    assert "MWh" in payload["summary_text"]

    table = format_forecast_table(payload, max_rows=5)
    assert "Time" in table
    assert "Power (kW)" in table


@patch("smarthack.wind.predictor.WindPowerPredictor.fetch_open_meteo_forecast")
def test_predict_wind_power_single_model_fallback(mock_fetch: MagicMock) -> None:
    """Tool execution works when use_ensemble=False."""
    mock_fetch.return_value = make_synthetic_weather(12)
    payload = predict_wind_power(
        latitude=35.2,
        longitude=-101.8,
        forecast_days=1,
        use_ensemble=False,
    )
    assert payload["status"] == "success"
    assert len(payload["hourly_forecast"]) == 12
