# CARE ML2 at 15 minutes: power per turbine and quarter hour, one week ahead

**Status: this is the 15-minute variant of the ML2 baseline.** It gives one value every 15 minutes for the next 7 days
(672 values per turbine), because production schedules in Romania are made per quarter hour. The hourly baseline
(`notebooks/care_ml2_power_baseline.md`) stays the reference for hourly results, the target definition and the ordering of
turbines.

Source: `notebooks/care_ml2_power_15min.ipynb`, run from scratch on 2026-11-08 in the conda env `ml_def` (catboost
1.2.10) with nbconvert, 0 errors, 13 minutes. Every number below was computed in that run. No independent review was run
on it.

## 0. THE ML2 baseline: R2 by forecast lead time

**This table is the ML2 baseline** (designated 2026-11-08). It answers the question that matters at serving: how good is
the prediction 1, 3 or 7 days ahead, and over a whole week.

R2 per quarter hour, **CatBoost 15 min per farm**, new turbines (ML1 folds), on quarters with a clean target:

| lead time | Farm A | Farm B | Farm C | mean |
|---|---|---|---|---|
| measured wind (no forecast error) | 0.969 | 0.953 | 0.941 | 0.954 |
| day 1 | 0.815 | 0.764 | 0.712 | 0.764 |
| day 3 | 0.652 | 0.591 | 0.503 | 0.582 |
| day 7 | 0.331 | 0.295 | 0.152 | 0.259 |
| **whole week** (error growing from day 1 to day 7) | **0.605** | **0.556** | **0.462** | **0.541** |

Companion numbers, same setup:
- **The hourly ML2 model** (hourly R2, `care_ml2_power_baseline.md`), A / B / C:

  | lead time | A | B | C | mean |
  |---|---|---|---|---|
  | measured wind | 0.994 | 0.972 | 0.960 | 0.975 |
  | day 1 | 0.842 | 0.779 | 0.723 | 0.781 |
  | day 3 | 0.681 | 0.601 | 0.507 | 0.596 |
  | day 7 | 0.365 | 0.298 | 0.148 | 0.270 |
  | whole week | 0.635 | 0.565 | 0.466 | 0.555 |

- **The energy over the 7 days**, which the agent uses, is better read as a relative error than as R2. WAPE of the weekly
  energy, A / B / C:
  - 15-minute model: 0.037 / 0.035 / 0.064 with measured wind, 0.237 / 0.200 / 0.231 for the whole week with forecast
    error;
  - hourly model: 0.032 / 0.036 / 0.058 with measured wind, 0.229 / 0.197 / 0.229.

**How the forecast error was simulated.** The rows with a lead time perturb the hourly wind:
- one error shared by every turbine of the park, autocorrelated from hour to hour (AR(1), r = 0.95);
- standard deviation 1.5 m/s at day 1, 2.2 m/s at day 3 and 3.3 m/s at day 7;
- "whole week" grows the deviation linearly from day 1 to day 7 inside each calendar week;
- three draws, averaged.

**These deviations are assumed typical values for hub-height wind forecasts, not measured on our parks.** The real
Open-Meteo error can make the true numbers better or worse. Measuring it (archived forecasts against production with real
timestamps; CARE timestamps are anonymised) is the first thing that would change this baseline.

**Rule for every later ML2 model.** Report this same table: same target, folds, quarters and simulated errors, with the
seeds 500, 501 and 502 for the three draws. Count a model as better only if it beats this baseline on the whole-week row
in every farm, without being worse at day 1. Once the real forecast error is measured, rerun this table with it, and from
then on that rerun is the baseline.

The tables of every case and model are in `dataset/wind_turbine_scada_fault/cache/ml2_15min/results_15min_forecast_error.csv`
(15 minutes) and `cache/ml2_baseline/results_forecast_error.csv` (hourly), with the columns `scheme`, `farm`, `model`, `case`.

## 1. Task

- **Question.** For every turbine and every quarter hour of the next 7 days, how much would it produce?
- **Data.** CARE wind-turbine SCADA, comma variant, farms A, B, C. It is the same data preparation as the hourly
  baseline (sections 1 to 6 of the notebook repeat it unchanged): timelines with only identical overlaps merged, the
  cleaning rules for available production, and the same two validation schemes.
- **Measurement interval.** CARE has SCADA averages every 10 minutes, at :00, :10, ..., :50 (no gaps inside the grid),
  not billing-meter readings.
- **Unit.** One (timeline, quarter hour).
- **Target `cf15`.** Mean power over the quarter hour as a capacity factor, for a healthy turbine in operation that is
  not held back. It is kept only when all of the quarter's 10-minute rows are clean.
  - kWh per quarter = `cf15` x `capacity_kw` x 0.25.
- **Serving constraint.** The forecast table `park_wind_forecast` stays hourly. ML2 at 15 minutes turns the hourly forecast
  into quarter-hour values.

## 2. Setup

### 2.1 From 10-minute rows to quarter hours: exact re-binning, not interpolation

- **How.** Every 10-minute row is an average, so it is taken as constant over its 10 minutes. Each row is split into two
  5-minute halves and every quarter takes three halves:
  - quarter :00-:15 = (10 min of row :00 + 5 min of row :10) / 15;
  - quarter :15-:30 = (5 min of row :10 + 10 min of row :20) / 15;
  - and so on, every 30 minutes.
- **Energy check.** Energy is conserved exactly. On 630,607 full hours the mean of the four quarters differs from the
  hourly value by at most 1.2e-7.
- **Size.** 3,224,781 quarters, 2,616,655 with a clean target: A 644,827, B 404,223, C 1,567,605.

### 2.2 Input wind: the hourly wind, interpolated to the quarter

- **Why.** At serving there is only an hourly forecast. A model trained on the wind measured per quarter would rely on
  detail inside the hour that the forecast cannot give.
- **In training:** the hourly mean wind is placed at the centre of its hour and interpolated linearly to each quarter's
  centre (7.5, 22.5, 37.5, 52.5 minutes).
- **At serving:** each hourly Open-Meteo value is taken as the instantaneous wind at `forecast_time`, and is interpolated
  to the quarter centres between T and T+1 h.
- **How close it gets:** the interpolated hourly wind and the wind measured per quarter correlate r = 0.993, with a mean
  absolute difference of 0.33 m/s.

**Features** (the hourly forecast set, plus the quarter):

| feature | how it is built |
|---|---|
| `ws` | interpolated hourly wind |
| `ws_d1`, `ws_sd3` | from the hourly series, applied to the hour's 4 quarters |
| `temp` | from the hour |
| `wd_sin`, `wd_cos` | from the hour (A and B only) |
| `hod_sin`, `hod_cos` | local time of the quarter centre |
| `doy_sin`, `doy_cos` | day of year |
| `quarter` | k = 0..3 |
| `turbine` | farm models only |

The generic model uses only wind, time and quarter.

### 2.3 Models

| name | what it is |
|---|---|
| **CatBoost 15 min per farm** | one model per farm |
| **CatBoost 15 min generic** | all farms, no site-specific input: the candidate for parks outside CARE |
| hourly CatBoost per farm, flat | the hourly ML2 model, its value repeated over the four quarters: **the bar** |
| empirical curve (median) | per farm, median `cf15` per 0.5 m/s bin of the interpolated wind |
| theoretical curve, climatology | as in the hourly baseline; climatology per turbine and quarter of day |
| true hourly value, flat (diagnostic) | the measured hourly mean repeated over the quarters: the best any flat profile can do |
| measured quarter wind (diagnostic, future only) | the wind measured per quarter: what a perfect 15-minute forecast would give |

- **CatBoost parameters:** depth 6, at most 600 trees, learning rate 0.05, L2 10, RMSE.
- **Number of trees:** from three inner fits grouped by turbine.
- **Training size:** at most 500,000 randomly drawn quarters per fit (quarters are strongly autocorrelated).

### 2.4 Validation and metrics

- **Validation schemes:** new turbines (ML1 `cv_folds.parquet`, seed 0) and future (last 20% of every timeline).
- **15-minute metrics:** R2, MAE and bias on quarters with a clean target.
- **Shape inside the hour:** on hours with all four quarters, the deviation of each quarter from its hour's mean, true
  against predicted.
  - R2 of the shape = 1 - sum((dev_true - dev_pred)^2) / sum(dev_true^2).
  - A flat profile scores 0. This is the direct test of whether 15 minutes adds anything over the hourly model.
- **7-day metrics:** WAPE and energy bias on weeks with at least 480 clean quarters.
- **95% intervals:** cluster bootstrap over turbines, 1000 resamples.
- **Ordering of turbines** is not repeated: it uses 7-day energy, which does not depend on the time step.

## 3. Headline

### 3.1 With measured wind

| scheme | farm | model | R2 15 min [95% CI] | shape R2 [95% CI] | WAPE 7d [95% CI] | energy bias 7d |
|---|---|---|---|---|---|---|
| new turbines | A | **CatBoost 15 min per farm** | **0.969 [0.965, 0.973]** | **0.260 [0.255, 0.266]** | 0.037 [0.019, 0.057] | +0.018 |
| new turbines | A | CatBoost 15 min generic | 0.966 [0.961, 0.970] | 0.251 | 0.036 | +0.021 |
| new turbines | A | hourly, flat | 0.963 [0.960, 0.966] | 0 | 0.032 [0.019, 0.045] | +0.005 |
| new turbines | A | empirical curve | 0.966 | 0.250 | 0.041 | -0.002 |
| new turbines | A | true hourly value, flat (diagnostic) | 0.969 | 0 | 0.000 | 0 |
| new turbines | B | **CatBoost 15 min per farm** | **0.953 [0.947, 0.959]** | **0.222 [0.218, 0.226]** | 0.035 [0.026, 0.044] | -0.002 |
| new turbines | B | CatBoost 15 min generic | 0.906 [0.895, 0.917] | 0.191 | 0.133 | +0.128 |
| new turbines | B | hourly, flat | 0.948 [0.942, 0.953] | 0 | 0.035 [0.028, 0.042] | -0.002 |
| new turbines | B | empirical curve | 0.939 | 0.209 | 0.041 | -0.002 |
| new turbines | B | true hourly value, flat (diagnostic) | 0.975 | 0 | 0.000 | 0 |
| new turbines | C | **CatBoost 15 min per farm** | **0.941 [0.938, 0.944]** | **0.177 [0.169, 0.184]** | 0.064 [0.054, 0.071] | -0.053 |
| new turbines | C | CatBoost 15 min generic | 0.941 [0.939, 0.943] | 0.179 | 0.062 | -0.055 |
| new turbines | C | hourly, flat | 0.937 [0.934, 0.940] | 0 | 0.058 [0.050, 0.066] | -0.045 |
| new turbines | C | empirical curve | 0.937 | 0.177 | 0.044 | -0.007 |
| new turbines | C | true hourly value, flat (diagnostic) | 0.977 | 0 | 0.001 | 0 |
| future | A | **CatBoost 15 min per farm** | **0.972 [0.969, 0.974]** | 0.256 | 0.016 [0.012, 0.022] | -0.003 |
| future | A | hourly, flat | 0.966 | 0 | 0.013 | -0.003 |
| future | A | measured quarter wind (diagnostic) | 0.997 | 0.964 | 0.012 | -0.004 |
| future | B | **CatBoost 15 min per farm** | **0.960 [0.950, 0.968]** | 0.228 | 0.020 [0.017, 0.023] | +0.003 |
| future | B | hourly, flat | 0.955 | 0 | 0.018 | +0.001 |
| future | B | measured quarter wind (diagnostic) | 0.980 | 0.875 | 0.017 | +0.002 |
| future | C | **CatBoost 15 min per farm** | **0.949 [0.941, 0.955]** | 0.174 | 0.038 [0.031, 0.046] | -0.002 |
| future | C | hourly, flat | 0.944 | 0 | 0.038 | -0.004 |
| future | C | measured quarter wind (diagnostic) | 0.970 | 0.829 | 0.036 | -0.001 |

**15-minute model against the hourly model repeated over the quarters** (paired bootstrap over turbines):

| scheme | farm | R2 15 min difference [CI] | WAPE 7d difference [CI] |
|---|---|---|---|
| new turbines | A | +0.0066 [+0.0049, +0.0079] | +0.0049 [-0.0042, +0.0151] |
| new turbines | B | +0.0054 [+0.0048, +0.0061] | -0.0000 [-0.0032, +0.0032] |
| new turbines | C | +0.0041 [+0.0029, +0.0052] | +0.0053 [-0.0007, +0.0112] |
| future | A | +0.0061 [+0.0048, +0.0072] | +0.0029 [-0.0019, +0.0087] |
| future | B | +0.0048 [+0.0043, +0.0056] | +0.0014 [+0.0001, +0.0025] |
| future | C | +0.0046 [+0.0040, +0.0052] | -0.0007 [-0.0015, +0.0000] |

How to read it:
- **Little variance lives inside the hour.** The measured hourly value repeated over the quarters already reaches R2
  0.969 to 0.977, so only 2 to 3% of the 15-minute variance is inside the hour.
- **The 15-minute model captures 17 to 26% of the shape inside the hour**, through the interpolated wind. That is worth
  R2 +0.004 to +0.007 over repeating the hourly value, significant in every farm and scheme.
- **7-day energy does not change.** The WAPE differences are within the intervals; only B in the future scheme is
  slightly worse, by 0.0014.
- **A real 15-minute wind would capture 83 to 96% of the shape** (the measured-quarter-wind diagnostic). The limit is the
  hourly forecast, not the model.

### 3.2 With forecast error (assumed, not measured)

The error is applied to the hourly wind before interpolation: shared by the park, AR(1), r = 0.95, standard deviation
1.5 / 2.2 / 3.3 m/s at 1 / 3 / 7 days, plus a ramp from day 1 to day 7. New turbines:

| farm | model | R2 15 min: measured / day 1 / day 3 / day 7 | shape R2: measured / day 1 / day 3 / day 7 | WAPE 7d, ramp |
|---|---|---|---|---|
| A | CatBoost 15 min per farm | 0.969 / 0.815 / 0.652 / 0.331 | 0.260 / 0.196 / 0.137 / 0.027 | 0.237 |
| A | hourly, flat | 0.963 / 0.816 / 0.661 / 0.355 | 0 | 0.228 |
| B | CatBoost 15 min per farm | 0.953 / 0.764 / 0.591 / 0.295 | 0.222 / 0.132 / 0.056 / -0.075 | 0.200 |
| B | hourly, flat | 0.948 / 0.760 / 0.588 / 0.293 | 0 | 0.199 |
| C | CatBoost 15 min per farm | 0.941 / 0.712 / 0.503 / 0.152 | 0.177 / 0.076 / -0.014 / -0.168 | 0.231 |
| C | hourly, flat | 0.937 / 0.708 / 0.500 / 0.150 | 0 | 0.230 |

- **Under forecast error, the 15-minute model and the repeated hourly value are equal** (R2 within 0.03 everywhere,
  equal 7-day WAPE).
- **The shape inside the hour fades with lead time.** By day 7 in B and C it is negative: the interpolated profile follows
  wind ramps that the forecast places wrongly.

### 3.3 One week ahead, every 15 minutes (worked example)

This is the serving path, run on turbine C23 for one unseen test week of the future scheme (week starting 2029-01-18,
an anonymised CARE date):
- **Input:** 168 hourly rows shaped like `park_wind_forecast`. As a stand-in for the forecast, the measured wind at each
  full hour is used.
- **Output:** 672 quarter-hour rows with `quarter_start`, `ws_interp`, `cf`, `power_kw` and `energy_kwh`, at 2050 kW
  (the database default).

| model | MAE per quarter (cf) | predicted MWh | measured MWh |
|---|---|---|---|
| CatBoost 15 min per farm | 0.026 | 63.5 | 63.0 |
| CatBoost 15 min generic | 0.026 | 62.4 | 63.0 |
| CatBoost 15 min per farm, with one draw of the ramp forecast error | 0.135 | 18.1 | 63.0 |

The last row is a single draw, shown only to make the point: the forecast error, not the time step, decides how good the
week is. Rows and figure: `cache/ml2_15min/ml2_15min_demo_week.parquet`, `demo_week_15min.png`.

## 4. Deliverables

- `notebooks/care_ml2_power_15min.ipynb`: executed, 263 KB.
- `models/ml2/`:
  - `ml2_cf15_generic.cbm`: the only model for parks outside CARE;
  - `ml2_cf15_farm_A.cbm`, `ml2_cf15_farm_B.cbm`, `ml2_cf15_farm_C.cbm`: CARE turbines only;
  - `feature_contract_15min.json`: how to build the 672 quarter rows from the 168 hourly forecast rows, the features with
    units, the energy conversion, and the time convention.
- **File sizes.** All files are under the 500 KB hook. A, B and generic keep their first 406 / 363 / 418 trees (of 427 /
  600 / 600). That changes their in-sample output by an RMS of 0.0006 / 0.0081 / 0.0036 cf.
- `dataset/wind_turbine_scada_fault/cache/ml2_15min/`:
  - `ml2_15min_predictions_future.parquet`: every test quarter of the future scheme, true value and four predictions;
  - `ml2_15min_weekly.parquet`: weekly energies, both schemes;
  - `ml2_15min_demo_week.parquet`, `results_15min_*.csv`, PNGs.
- **Serving recipe** (in the contract and implemented in the notebook as `quarters_from_forecast` and
  `predict_week_15min`):
  1. For each forecast hour T, build quarters starting at T, T+15, T+30 and T+45 min.
  2. Interpolate wind to the quarter centre between T and T+1 h.
  3. Predict `cf`, clip it to [0, 1], and compute kWh = cf x capacity_kw x 0.25.

## 5. What does not work, and what it means

- **The 15-minute profile is a smooth interpolation, not a forecast of what happens inside the hour.**
  - With an hourly forecast it adds R2 +0.004 to +0.007 with measured wind, and nothing under realistic forecast error.
  - It never changes the 7-day energy that the agent uses.
- **Real detail at 15 minutes needs a 15-minute wind forecast.** The diagnostic shows such a forecast, if accurate, would
  explain 83 to 96% of the shape inside the hour. Open-Meteo has a 15-minute option; whether it is native or interpolated
  for Romania has to be checked before relying on it, and it would change the forecast job and the table.
- **The hourly baseline's limits carry over:**
  - forecast error dominates (7-day WAPE about 0.20-0.29 with the ramp);
  - the generic model misses the energy level of a new park;
  - turbines of the same park cannot be ordered without turbine history.
- **The 600-tree cap was reached** by B and the generic model, as in the hourly baseline.

## 6. Recommendation

- **The 15-minute output can be delivered now with `ml2_cf15_generic.cbm`** (or a farm model for CARE turbines) and the
  contract above. It satisfies the 15-minute format and costs nothing in weekly energy.
- **Do not expect more precision from the 15-minute step.** Repeating the hourly prediction over four quarters would be
  almost as good.
- **The precision gain is in the forecast**: measuring and correcting its error at the parks, and possibly a native
  15-minute forecast.

## 7. How to compare a new 15-minute model

Same target `cf15` (exact re-binning, all halves clean), same quarters, same folds and future split. Only inputs that an
hourly (or a declared 15-minute) forecast provides. A new model counts as better only if:

1. **It beats the hourly model repeated over the quarters** on 15-minute R2, with a paired turbine-bootstrap interval
   above zero. **And it beats this baseline:**
   - new turbines: 0.969 / 0.953 / 0.941;
   - future: 0.972 / 0.960 / 0.949.
2. **Its shape R2 is above this baseline:** new turbines 0.260 / 0.222 / 0.177.
3. **Its 7-day WAPE is not worse than the hourly model**, interval of the difference containing or below zero.
4. **It is reported under the ramp forecast error.** Bars, 15-minute R2: 0.605 / 0.556 / 0.462 (new turbines).
   - The `ramp` column in `results_15min_forecast_error.csv` has them.
