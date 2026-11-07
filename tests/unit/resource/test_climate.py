"""
Unit tests for the wind climate backtest and forecast.
"""

import numpy as np
import pytest

from smarthack.resource.climate import (
    ESTIMATORS,
    AnnualWindCube,
    estimate,
    forecast_factor,
    parse_power_regional,
    run_backtest,
)
from tests.conftest import skip_module_without_extra

skip_module_without_extra("resource")


def make_cube(n_years: int = 40, seed: int = 0, trend: float = 0.0) -> AnnualWindCube:
    """A 3 x 4 cube: a fixed spatial pattern times noisy, spatially coherent years."""
    rng = np.random.default_rng(seed)
    years = np.arange(1981, 1981 + n_years)
    pattern = np.linspace(4.0, 8.0, 12).reshape(3, 4)
    yearly = 1.0 + rng.normal(0.0, 0.03, n_years) + trend * (years - years[0])
    values = pattern[..., None] * yearly[None, None, :]
    return AnnualWindCube(
        lats=np.array([44.0, 44.5, 45.0]),
        lons=np.array([20.0, 20.625, 21.25, 21.875]),
        years=years,
        values=values,
    )


def test_parse_power_regional_keeps_only_annual_values_and_fill_becomes_nan() -> None:
    """Month 13 is the annual mean; -999 is NASA's fill value."""
    payload = {
        "features": [
            {
                "geometry": {"coordinates": [20.0, 44.0, 100.0]},
                "properties": {"parameter": {"WS50M": {"200001": 9.9, "200013": 5.0}}},
            },
            {
                "geometry": {"coordinates": [20.625, 44.0, 100.0]},
                "properties": {"parameter": {"WS50M": {"200013": -999.0}}},
            },
        ]
    }
    cube = parse_power_regional(payload, "WS50M")
    assert cube.values.shape == (1, 2, 1)
    assert cube.values[0, 0, 0] == 5.0
    assert np.isnan(cube.values[0, 1, 0])


def test_parse_power_regional_rejects_an_empty_payload() -> None:
    """Without annual values there is nothing to forecast from."""
    with pytest.raises(ValueError):
        parse_power_regional({"features": []}, "WS50M")


def test_mean_over_rejects_a_range_without_data() -> None:
    """Asking for a reference period the record does not cover is an error."""
    with pytest.raises(ValueError):
        make_cube().mean_over(1900, 1910)


@pytest.mark.parametrize("name", ESTIMATORS)
def test_estimators_never_look_past_the_origin(name: str) -> None:
    """Changing years after the origin must not change any forecast."""
    cube = make_cube()
    data = cube.values.reshape(-1, cube.values.shape[-1])
    origin = 2010
    before = estimate(name, data, cube.years, origin, (2, 3), first_origin=1990)
    tampered = data.copy()
    tampered[:, cube.years > origin] *= 3.0
    after = estimate(name, tampered, cube.years, origin, (2, 3), first_origin=1990)
    np.testing.assert_allclose(before, after)


def test_estimate_rejects_an_unknown_method() -> None:
    """A typo in the estimator name fails loudly."""
    cube = make_cube()
    with pytest.raises(KeyError):
        estimate("magic", cube.values.reshape(12, -1), cube.years, 2000, (2, 3))


def test_backtest_prefers_climatology_over_persistence_on_stationary_noise() -> None:
    """Pure year-to-year noise: last year is the worst guess, a long mean the best kind."""
    result = run_backtest(make_cube(seed=1), (2, 3))
    assert result.mae_test["persistence"] > result.mae_test["climatology_all"]
    assert result.selected != "persistence"
    assert result.band_low < 0 < result.band_high
    assert 0.0 <= result.band_coverage_test <= 1.0
    assert result.rank_correlation_test > 0.99


def test_backtest_periods_do_not_overlap() -> None:
    """Selection and reporting use different target years."""
    result = run_backtest(make_cube(), (2, 3), test_years=10, validation_years=12)
    assert result.validation_targets[1] < result.test_targets[0]
    assert result.test_targets == (2011, 2020)


def test_backtest_needs_enough_history() -> None:
    """A record too short for validation and test periods is refused."""
    with pytest.raises(ValueError):
        run_backtest(make_cube(n_years=15), (2, 3))


def test_forecast_factor_is_one_for_a_flat_climate() -> None:
    """With identical years, the forecast equals the reference mean everywhere."""
    cube = make_cube()
    cube.values = np.repeat(cube.values[..., :1], cube.values.shape[-1], axis=-1)
    result = forecast_factor(cube, "climatology_10y", (2, 3), (2008, 2017))
    assert result.target_years == (2022, 2023)
    np.testing.assert_allclose(result.factor, 1.0)


def test_forecast_factor_follows_a_trend_with_the_trend_estimator() -> None:
    """A strengthening wind is extrapolated above the reference by the trend method."""
    result = forecast_factor(
        make_cube(trend=0.01, seed=3), "linear_trend_15y", (2, 3), (2008, 2017)
    )
    assert np.all(result.factor > 1.05)
