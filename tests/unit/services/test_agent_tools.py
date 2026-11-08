"""
# Unit tests for the agent's wind power tool

The projected output of a turbine is what breaks ties between turbines and weighs the repair
plans, so it must be the number the wind predictor reports, never a silent zero.
"""

from typing import Any

import pytest

from smarthack.services.agent import tools


def test_projected_output_is_the_total_the_predictor_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The result carries the horizon's total in `summary`; the tool returns it, rounded."""
    seen: list[dict[str, Any]] = []

    def predictor(**kwargs: Any) -> dict[str, Any]:
        """Answer in the shape `predict_wind_power` returns."""
        seen.append(kwargs)
        return {
            "status": "success",
            "summary": {"total_generation_kwh": 104781.4, "total_generation_mwh": 104.781},
            "hourly_forecast": [{"power_kw": 623.7}] * 168,
        }

    monkeypatch.setattr(tools, "predict_wind_power", predictor)

    mwh = tools.predict_wind_power_mwh(
        latitude=35.2, longitude=-101.8, forecast_days=7, capacity_kw=2050.0
    )

    assert mwh == 104.78
    assert seen == [
        {"latitude": 35.2, "longitude": -101.8, "forecast_days": 7, "capacity_kw": 2050.0}
    ]


def test_projected_output_is_not_zero_for_a_forecast_with_power(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: the tool once read a key the predictor never sets and returned 0.0 always."""
    monkeypatch.setattr(
        tools,
        "predict_wind_power",
        lambda **kwargs: {
            "summary": {"total_generation_mwh": 12.5},
            "hourly_forecast": [{"power_kw": 1.0}] * 24,
        },
    )

    assert tools.predict_wind_power_mwh(latitude=1.0, longitude=2.0) > 0.0
