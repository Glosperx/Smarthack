"""
# Wind climate forecasting for the next years

Turns NASA POWER annual mean wind speeds into a forecast of the mean wind over the next
full years, per coarse cell. A rolling-origin backtest compares simple baselines with a
learned blend, picks the estimator on a validation period, reports it on a later test
period, and calibrates a P10-P90 band from its own past errors.

Interannual wind variability is mostly chaotic, so a 1-2 year forecast of the mean is a
question of which climatology to trust and how wide the band is. The backtest is what
decides, not an assumption.

The following can be imported from this module:
- `AnnualWindCube`
- `BacktestResult`
- `ESTIMATORS`
- `ForecastResult`
- `estimate`
- `forecast_factor`
- `parse_power_regional`
- `run_backtest`
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: Missing-value marker NASA POWER uses.
_POWER_FILL = -999.0

#: Least-squares ridge penalty of the learned blend.
_RIDGE_ALPHA = 1.0

#: Fewest past origins the learned blend needs before it fits its weights.
_MIN_BLEND_ORIGINS = 8


@dataclass
class AnnualWindCube:
    """Annual mean wind speed on a regular coarse grid: `values[lat, lon, year]`."""

    lats: np.ndarray
    lons: np.ndarray
    years: np.ndarray
    values: np.ndarray

    def mean_over(self, first_year: int, last_year: int) -> np.ndarray:
        """
        Average the cube over an inclusive range of years.

        :param first_year: First year of the range.
        :param last_year: Last year of the range.

        :returns mean: `[lat, lon]` mean wind speed, NaN where no year has data.
        :raises ValueError: If no year of the cube falls in the range.
        """
        mask = (self.years >= first_year) & (self.years <= last_year)
        if not mask.any():
            raise ValueError(f"no data between {first_year} and {last_year}")
        with np.errstate(invalid="ignore"):
            return np.asarray(np.nanmean(self.values[..., mask], axis=-1))


def parse_power_regional(payload: dict[str, Any], parameter: str) -> AnnualWindCube:
    """
    Read a NASA POWER monthly regional GeoJSON response into an annual cube.

    The monthly endpoint returns twelve months plus month `13`, the annual mean; only the
    annual value is kept. Fill values become NaN.

    :param payload: Parsed JSON body of the regional endpoint.
    :param parameter: The parameter key, such as `WS50M`.

    :returns cube: Annual wind cube sorted by latitude, longitude and year.
    :raises ValueError: If the payload holds no feature with annual values.
    """
    records: list[tuple[float, float, int, float]] = []
    for feature in payload.get("features", []):
        lon, lat = feature["geometry"]["coordinates"][:2]
        series = feature["properties"]["parameter"][parameter]
        for key, value in series.items():
            if len(key) == 6 and key.endswith("13"):
                val = float(value)
                records.append(
                    (float(lat), float(lon), int(key[:4]), np.nan if val == _POWER_FILL else val)
                )
    if not records:
        raise ValueError("NASA POWER payload has no annual values")

    lats = np.array(sorted({r[0] for r in records}))
    lons = np.array(sorted({r[1] for r in records}))
    years = np.array(sorted({r[2] for r in records}))
    values = np.full((len(lats), len(lons), len(years)), np.nan)
    lat_idx = {v: i for i, v in enumerate(lats)}
    lon_idx = {v: i for i, v in enumerate(lons)}
    year_idx = {v: i for i, v in enumerate(years)}
    for lat, lon, year, val in records:
        values[lat_idx[lat], lon_idx[lon], year_idx[year]] = val
    return AnnualWindCube(lats=lats, lons=lons, years=years, values=values)


def _flat(cube: AnnualWindCube) -> np.ndarray:
    """Reshape the cube to `[cell, year]`."""
    return cube.values.reshape(-1, cube.values.shape[-1])


def _window_mean(data: np.ndarray, years: np.ndarray, origin: int, length: int) -> np.ndarray:
    """Mean of the `length` years ending at `origin` (inclusive), per cell."""
    mask = (years > origin - length) & (years <= origin)
    with np.errstate(invalid="ignore"):
        return np.asarray(np.nanmean(data[:, mask], axis=1))


def _ew_mean(data: np.ndarray, years: np.ndarray, origin: int, half_life: float) -> np.ndarray:
    """Exponentially weighted mean of all years up to `origin`, per cell."""
    mask = years <= origin
    weights = 0.5 ** ((origin - years[mask]) / half_life)
    block = data[:, mask]
    valid = np.isfinite(block)
    num = np.where(valid, block, 0.0) @ weights
    den = valid.astype(float) @ weights
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.asarray(num / den)


def _trend(data: np.ndarray, years: np.ndarray, origin: int, horizon: float) -> np.ndarray:
    """Extrapolate a 15-year linear trend `horizon` years past `origin`, per cell."""
    mask = (years > origin - 15) & (years <= origin)
    x = years[mask].astype(float) - origin
    block = data[:, mask]
    coef = np.polyfit(x, np.nan_to_num(block.T, nan=float(np.nanmean(block))), 1)
    return np.asarray(coef[1] + coef[0] * horizon)


#: Base estimators: each maps (cell x year data, years, origin, mid-horizon) to a forecast.
_BASE: dict[str, Callable[[np.ndarray, np.ndarray, int, float], np.ndarray]] = {
    "persistence": lambda d, y, o, h: np.asarray(d[:, y == o][:, 0]),
    "climatology_all": lambda d, y, o, h: _window_mean(d, y, o, 10_000),
    "climatology_10y": lambda d, y, o, h: _window_mean(d, y, o, 10),
    "climatology_5y": lambda d, y, o, h: _window_mean(d, y, o, 5),
    "exp_weighted_8y": lambda d, y, o, h: _ew_mean(d, y, o, 8.0),
    "linear_trend_15y": lambda d, y, o, h: _trend(d, y, o, h),
}

#: The base forecasts the learned blend combines.
_BLEND_INPUTS = ("persistence", "climatology_all", "climatology_10y", "climatology_5y")

#: Every estimator the backtest scores; the learned blend is fitted on past origins only.
ESTIMATORS: tuple[str, ...] = (*_BASE, "learned_blend")


def _target(data: np.ndarray, years: np.ndarray, origin: int, lead: tuple[int, int]) -> np.ndarray:
    """Mean wind over the lead years after `origin`, per cell."""
    mask = (years >= origin + lead[0]) & (years <= origin + lead[1])
    with np.errstate(invalid="ignore"):
        return np.asarray(np.nanmean(data[:, mask], axis=1))


def _blend_features(data: np.ndarray, years: np.ndarray, origin: int, mid: float) -> np.ndarray:
    """Stack the blend inputs as relative deviations from the full climatology."""
    base = _BASE["climatology_all"](data, years, origin, mid)
    cols = [_BASE[name](data, years, origin, mid) / base - 1.0 for name in _BLEND_INPUTS]
    return np.column_stack(cols)


def _fit_blend(
    data: np.ndarray, years: np.ndarray, origins: list[int], lead: tuple[int, int]
) -> np.ndarray:
    """
    Fit ridge weights mapping the blend inputs to the relative target over past origins.

    :param data: `[cell, year]` annual means.
    :param years: Year of each column.
    :param origins: Forecast origins whose targets are fully observed.
    :param lead: Lead years of the target.

    :returns weights: One weight per blend input.
    """
    mid = (lead[0] + lead[1]) / 2.0
    xs, ys = [], []
    for origin in origins:
        base = _BASE["climatology_all"](data, years, origin, mid)
        xs.append(_blend_features(data, years, origin, mid))
        ys.append(_target(data, years, origin, lead) / base - 1.0)
    x = np.vstack(xs)
    y = np.concatenate(ys)
    ok = np.isfinite(x).all(axis=1) & np.isfinite(y)
    x, y = x[ok], y[ok]
    gram = x.T @ x + _RIDGE_ALPHA * np.eye(x.shape[1])
    return np.asarray(np.linalg.solve(gram, x.T @ y))


def estimate(
    name: str,
    data: np.ndarray,
    years: np.ndarray,
    origin: int,
    lead: tuple[int, int],
    first_origin: int | None = None,
) -> np.ndarray:
    """
    Forecast the mean wind over the lead years after `origin` with one estimator.

    Uses only years up to `origin`. The learned blend is fitted on earlier origins whose
    targets were already observed at `origin`, so it never sees the future.

    :param name: One of `ESTIMATORS`.
    :param data: `[cell, year]` annual mean wind speeds.
    :param years: Year of each column of `data`.
    :param origin: Last year of data the forecast may use.
    :param lead: First and last lead year of the target, inclusive.
    :param first_origin: Earliest origin the learned blend may train on.

    :returns forecast: Per-cell forecast of the mean wind speed.
    :raises KeyError: If `name` is not a known estimator.
    """
    mid = (lead[0] + lead[1]) / 2.0
    if name in _BASE:
        return _BASE[name](data, years, origin, mid)
    if name != "learned_blend":
        raise KeyError(name)

    start = int(first_origin if first_origin is not None else years.min() + 10)
    past = [o for o in range(start, origin - lead[1] + 1)]
    base = _BASE["climatology_all"](data, years, origin, mid)
    if len(past) < _MIN_BLEND_ORIGINS:
        return base
    weights = _fit_blend(data, years, past, lead)
    return np.asarray(base * (1.0 + _blend_features(data, years, origin, mid) @ weights))


@dataclass
class BacktestResult:
    """Scores of every estimator and the band of the one selected."""

    lead: tuple[int, int]
    validation_targets: tuple[int, int]
    test_targets: tuple[int, int]
    mae_validation: dict[str, float]
    mae_test: dict[str, float]
    mape_test: dict[str, float]
    selected: str
    band_low: float
    band_high: float
    band_coverage_test: float
    rank_correlation_test: float
    residuals: dict[str, list[float]] = field(default_factory=dict)


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    """Spearman rank correlation of two vectors, ignoring non-finite pairs."""
    ok = np.isfinite(a) & np.isfinite(b)
    ra = np.argsort(np.argsort(a[ok])).astype(float)
    rb = np.argsort(np.argsort(b[ok])).astype(float)
    return float(np.corrcoef(ra, rb)[0, 1])


def run_backtest(
    cube: AnnualWindCube,
    lead: tuple[int, int],
    test_years: int = 10,
    validation_years: int = 12,
    min_history: int = 10,
) -> BacktestResult:
    """
    Score every estimator with rolling forecast origins and select one.

    Origins are split by the years their targets fall in: the last `test_years` target
    years form the test period, the `validation_years` before it the validation period.
    The estimator is chosen on validation MAE; the band is the 10th-90th percentile of its
    relative errors on every origin before the test period, and its coverage is then
    measured on the test period it never saw.

    :param cube: Annual wind cube.
    :param lead: First and last lead year of the target, inclusive.
    :param test_years: Number of most recent target years held out for testing.
    :param validation_years: Number of target years before those used to select.
    :param min_history: Years of data required before the first origin.

    :returns result: Per-estimator MAE, the selection and its calibrated band.
    :raises ValueError: If the record is too short for both periods.
    """
    data = _flat(cube)
    years = cube.years
    last = int(years.max())
    first_origin = int(years.min()) + min_history - 1
    test_first_target = last - test_years + 1
    val_first_target = test_first_target - validation_years
    origins = list(range(first_origin, last - lead[1] + 1))
    if not origins or origins[0] + lead[1] > val_first_target:
        raise ValueError("record too short for a validation and a test period")

    errors: dict[str, dict[int, np.ndarray]] = {name: {} for name in ESTIMATORS}
    truths: dict[int, np.ndarray] = {}
    for origin in origins:
        truth = _target(data, years, origin, lead)
        truths[origin] = truth
        for name in ESTIMATORS:
            pred = estimate(name, data, years, origin, lead, first_origin=first_origin)
            errors[name][origin] = pred - truth

    def end_year(o: int) -> int:
        """Last target year of an origin."""
        return o + lead[1]

    val = [o for o in origins if val_first_target <= end_year(o) < test_first_target]
    test = [o for o in origins if end_year(o) >= test_first_target]
    before_test = [o for o in origins if end_year(o) < test_first_target]

    def mae(name: str, subset: list[int]) -> float:
        """Mean absolute error of an estimator over a set of origins."""
        return float(np.nanmean(np.concatenate([np.abs(errors[name][o]) for o in subset])))

    def mape(name: str, subset: list[int]) -> float:
        """Mean absolute percentage error of an estimator over a set of origins."""
        parts = [np.abs(errors[name][o]) / truths[o] for o in subset]
        return float(np.nanmean(np.concatenate(parts)))

    mae_val = {n: mae(n, val) for n in ESTIMATORS}
    mae_test = {n: mae(n, test) for n in ESTIMATORS}
    mape_test = {n: mape(n, test) for n in ESTIMATORS}
    selected = min(mae_val, key=lambda n: mae_val[n])

    def rel(o: int) -> np.ndarray:
        """Relative error of the truth against the selected forecast for one origin."""
        pred = truths[o] + errors[selected][o]
        return np.asarray(truths[o] / pred - 1.0)

    rel_hist = np.concatenate([rel(o) for o in before_test])
    rel_hist = rel_hist[np.isfinite(rel_hist)]
    low, high = (float(q) for q in np.quantile(rel_hist, [0.1, 0.9]))
    rel_test = np.concatenate([rel(o) for o in test])
    rel_test = rel_test[np.isfinite(rel_test)]
    coverage = float(np.mean((rel_test >= low) & (rel_test <= high)))
    rank_corr = float(
        np.mean([_spearman(truths[o] + errors[selected][o], truths[o]) for o in test])
    )

    return BacktestResult(
        lead=lead,
        validation_targets=(val_first_target, test_first_target - 1),
        test_targets=(test_first_target, last),
        mae_validation=mae_val,
        mae_test=mae_test,
        mape_test=mape_test,
        selected=selected,
        band_low=low,
        band_high=high,
        band_coverage_test=coverage,
        rank_correlation_test=rank_corr,
        residuals={"before_test": [float(v) for v in rel_hist[:: max(1, len(rel_hist) // 2000)]]},
    )


@dataclass
class ForecastResult:
    """Forecast of the coarse grid and its ratio to the Global Wind Atlas reference."""

    target_years: tuple[int, int]
    forecast: np.ndarray
    reference: np.ndarray
    factor: np.ndarray


def forecast_factor(
    cube: AnnualWindCube,
    estimator: str,
    lead: tuple[int, int],
    reference_years: tuple[int, int],
    min_history: int = 10,
) -> ForecastResult:
    """
    Forecast the lead years after the last year of data and express it as a factor.

    The factor is the forecast divided by the mean over the reference years, the period a
    fine-scale atlas was built from; multiplying that atlas by the factor moves it to the
    forecast years while keeping its terrain detail.

    :param cube: Annual wind cube.
    :param estimator: One of `ESTIMATORS`.
    :param lead: First and last lead year of the target, inclusive.
    :param reference_years: First and last year of the fine atlas' reference period.
    :param min_history: Years of data before the first origin the blend may train on.

    :returns result: `[lat, lon]` forecast, reference mean and factor.
    """
    data = _flat(cube)
    origin = int(cube.years.max())
    first_origin = int(cube.years.min()) + min_history - 1
    shape = cube.values.shape[:2]
    pred = estimate(estimator, data, cube.years, origin, lead, first_origin=first_origin)
    reference = cube.mean_over(*reference_years)
    forecast = pred.reshape(shape)
    with np.errstate(invalid="ignore", divide="ignore"):
        factor = forecast / reference
    return ForecastResult(
        target_years=(origin + lead[0], origin + lead[1]),
        forecast=forecast,
        reference=reference,
        factor=np.asarray(factor),
    )


__all__ = [
    "AnnualWindCube",
    "BacktestResult",
    "ESTIMATORS",
    "ForecastResult",
    "estimate",
    "forecast_factor",
    "parse_power_regional",
    "run_backtest",
]
