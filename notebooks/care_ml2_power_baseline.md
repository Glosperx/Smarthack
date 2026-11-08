# CARE ML2 baseline: power per turbine from forecast-available inputs

**Status: hourly reference of ML2.** The ML2 baseline headline, R2 by forecast lead time (day 1 / 3 / 7 / whole
week), is section 0 of `notebooks/care_ml2_power_15min.md`. This page holds the hourly results, the target definition,
the cleaning rules and the ordering of turbines, and every later ML2 model is also compared against its numbers, on the
same target, folds, hours and pairs. Source: `notebooks/care_ml2_power_baseline.ipynb`, run from scratch on 2026-11-08 in the
conda env `ml_def` (catboost 1.2.10) with nbconvert, 0 errors, 14 minutes. Every number below was computed in that run.
No independent review was run on it.

## 1. Task

- **Question.** How much would each turbine produce in every hour of the next 7 days? When two or more turbines of the
  same park fail close together, the dispatch agent repairs the one with the higher 7-day production first. What matters
  is therefore the **7-day energy per turbine** and the **order between turbines of the same park**, not 10-minute accuracy.
- **Data.** CARE wind-turbine SCADA, `dataset/wind_turbine_scada_fault/raw`, comma variant only (`comma_*.csv`,
  `comma_event_info.csv`). Farms A, B and C: 95 datasets, 36 turbines, and 17 / 14 / 54 timelines after merging only
  identical overlaps (same rule as ML1).
- **Unit.** One (timeline, hour). The forecast is hourly, so 10-minute rows are averaged to the hour.
- **Target `cf`.** Hourly mean power as a capacity factor (CARE power is normalised per farm, p99 0.976 / 1.029 / 1.012),
  for a **healthy turbine in operation that is not held back** (section 2). An hour counts only when at least 4 of its 6
  rows are clean. MWh = sum of hourly `cf` x `capacity_kw` / 1000.
- **Serving constraint.** The main models use only features that can be computed from `park_wind_forecast`, which has
  one row per park and hour. Rotor speed, pitch, internal temperatures, reactive power and lags of power appear only in
  one diagnostic model, which is marked as not deployable.

## 2. Setup

### 2.1 Cleaning: what "available" means

| farm | 10-min rows | anomaly window % | repair 14 d % | stopped % | curtailed % | clean % | curtailed, share of rows at 13-20 m/s % |
|---|---|---|---|---|---|---|---|
| A | 1,014,782 | 1.63 | 0.67 | 1.96 | 0.17 | 95.6 | 0.7 |
| B | 806,909 | 4.21 | 0.57 | 6.78 | 12.19 | 76.2 | 53.2 |
| C | 3,014,965 | 2.02 | 0.48 | 6.48 | 11.58 | 79.4 | 47.1 |

The cleaning rules:
- **Removed:** anomaly windows (`event_start` .. `event_end`, located by `event_start_id` / `event_end_id`) and the 14
  days after each window, per timeline. The windows of normal datasets stay.
- **Removed, stopped:** wind 4.5 to 20 m/s and power at or below 0.01.
- **Removed, curtailed or derated:** wind 4.5 to 20 m/s and power below `0.70 x envelope(ws) - 0.05`. The envelope is the
  farm's 90th percentile of producing rows per 0.5 m/s bin, made monotone.
- **Never removed:** rows below 4.5 m/s (start-up, small negative consumption) and rows at or above 20 m/s (storm
  control).

How the curtailment rule holds up:
- **Against the turbines' own available-power signal** (A `power_29`, B `power_58`), the rule has precision 0.74 / 0.99
  and recall 0.68 / 0.62. C has no such signal.
- **The rule is deliberately conservative.** In B it keeps mild setpoints, so the mean power it keeps at 13 to 20 m/s is
  0.875 where the available-power signal says 1.015. **The available curve of B (and probably C) is about 14% too low at
  high wind.**
- **Against `status_type_id`** (comparison only, never a filter): status != 0 covers 24.8% / 10.0% / 10.5% of the rows
  outside anomaly windows, the physical rule 2.2% / 19.9% / 18.5%. Every row that only the physical rule removes has
  status 0, so curtailment in B and C happens under "normal" status. In A, status removes 23% of rows that the rule keeps,
  mostly idling at low wind.

### 2.2 Availability per turbine

Availability is energy-based and measured outside anomaly windows: actual energy divided by the energy the turbine would
have produced on its stopped and curtailed rows if it had followed the farm's available curve.

| farm | median | range | stop loss (mean) | curtailment loss (mean) |
|---|---|---|---|---|
| A | 0.954 | 0.930-0.995 | 4.1% | 0.2% |
| B | 0.808 | 0.737-0.852 | 8.6% | 11.2% |
| C | 0.785 | 0.622-0.918 | 9.4% | 12.1% |

`expected production = available production x availability`.

### 2.3 Time-aligned groups (needed for the ordering metric)

- **Why they are needed.** Timestamps are anonymised per dataset, so turbines can only be compared in "the same week"
  where their data really share a time axis.
- **How they are built.** Two timelines of different turbines go into the same group when their hourly wind speeds
  correlate above 0.8 over at least 3 shared days.
- **The split is clean:** no pair falls between 0.5 and 0.8. That gives A 7 groups (largest 4 turbines), B 8 (largest 3)
  and C 15 (largest 7).
- **Consistency check:** no turbine shows different data inside one group.

### 2.4 Hourly aggregation and its bias

Applying a power curve to the hourly mean wind is not the same as averaging the curve over the 10-minute winds. The
difference, `curve(hourly mean wind)` minus `mean(curve(10-minute wind))`, is -1.34% (A), -0.35% (B) and -0.06% (C) of
energy.
- In a single 1 m/s bin it reaches up to 0.14 cf (A).
- It is negative where the curve is convex and positive near rated, so over a week it mostly cancels.
- CatBoost learns hourly targets from hourly inputs, so it absorbs this bias. It matters for physical curves applied to an
  hourly forecast.

### 2.5 Features

| feature | from `park_wind_forecast` | in CARE | models |
|---|---|---|---|
| `ws` | `wind_speed_100m` (m/s) | hourly mean nacelle wind | all |
| `ws_d1` | change of `wind_speed_100m` from the previous hour | same | all |
| `ws_sd3` | std of `wind_speed_100m` over t-1..t+1 h | same | all |
| `temp` | `temperature_2m` (C) minus the park's reference temperature | ambient minus the farm median (C is shifted, median 28.1 C) | per farm, pooled |
| `wd_sin`, `wd_cos` | `wind_direction_100m` | absolute direction, A `sensor_1`, B `sensor_4`, C none | per farm A/B, pooled |
| `hod_*`, `doy_*` | local solar hour and day of year of `forecast_time` | timestamp | all |
| `turbine`, `farm` | CARE ids | CARE ids | per farm, pooled |

- **No cube or wind bins as features.** A tree model is invariant to monotone transforms of one feature.
- **Gusts are only an ablation.** Their counterpart in CARE is loose: the nacelle 10-minute maximum, and the max/mean
  ratio is 1.9 in A against 1.4 in B and C.
- **Some forecast columns cannot be used.** Pressure, humidity and dew point are not in CARE; `wind_speed_10m` and
  `wind_direction_10m` have no hub-height counterpart.

### 2.6 Models

| name | what it is |
|---|---|
| **CatBoost per farm** | one model per farm, forecast features + `turbine` |
| **CatBoost per farm, park wind** | the same, but trained and served on the park's median wind, temperature and direction, so every turbine of a group gets the same weather row (the serving situation) |
| **CatBoost pooled** | one model for A, B, C, forecast features + `farm` + `turbine` |
| **CatBoost generic** | one model for A, B, C with only `ws`, `ws_d1`, `ws_sd3`, hour and day of year: no site-specific input, the only candidate for parks outside CARE |
| SCADA complete (diagnostic, **not deployable**) | per farm, + rotor speed, pitch, 10-minute wind std and max |
| (a) theoretical curve | 3 / 13 / 25 m/s, `((ws - 3) / 10) ** 3`, as in `smarthack/wind` |
| (b) empirical curve | per farm, median hourly `cf` per 0.5 m/s bin on the training rows; **the bar**. A mean-per-bin variant is shown too |
| (c) climatology | mean `cf` per turbine and hour of day on the training rows |
| per-turbine curve | future scheme only: median curve per turbine |

- **CatBoost parameters:** depth 6, at most 600 trees, learning rate 0.05, L2 10, RMSE.
- **Number of trees:** the median best iteration of 3 inner fits, grouped by turbine, at most 150,000 rows each. B and the
  generic model reached the 600 cap.

### 2.7 Validation, metrics

- **Validation schemes:**
  - **New turbines:** `cache/catboost_baseline/cv_folds.parquet`, seed 0 (the ML1 folds). Per-farm models use the
    `per_farm` scheme (A and B leave one turbine out, C five folds); pooled and generic models use the `pooled` scheme.
  - **Future:** in every timeline, the first 80% of its time span trains and the last 20% tests.
- **Hourly metrics** (hours with a clean target): MAE, RMSE, R2 and bias, in capacity-factor units.
- **7-day metrics:** per timeline and calendar week with at least 120 clean hours.
  - WAPE = sum of |error| / sum of true energy.
  - Energy bias.
  - Median absolute relative error.
- **Decision metrics:** pairs of different turbines in the same time group and week, with at least 120 common clean
  hours; energy is compared on the common hours.
  - Pair accuracy: a tie counts one half.
  - The same accuracy on pairs whose true gap is at least 5%.
  - Spearman correlation inside windows with 3 or more turbines and at least 72 common hours.
  - All decision metrics are reported with each turbine's own wind and with the park's wind.
  - Pairs: new turbines A 756, B 119, C 2,363; future A 59, B 10, C 94. The median true gap is 6 to 11% of energy.
- **95% intervals:** cluster bootstrap over turbines, 1000 resamples, the same resamples for all models of a farm.
  Spearman intervals are bootstrapped over windows.

## 3. Headline

### 3.1 Hourly accuracy and 7-day energy (measured nacelle wind)

| scheme | farm | model | R2 [95% CI] | MAE | bias | WAPE 7d [95% CI] | energy bias 7d |
|---|---|---|---|---|---|---|---|
| new turbines | A | **CatBoost per farm** | **0.994 [0.992, 0.995]** | 0.0156 | +0.0015 | **0.032 [0.019, 0.045]** | +0.005 |
| new turbines | A | CatBoost pooled | 0.992 [0.990, 0.994] | 0.0183 | -0.0069 | 0.043 [0.032, 0.057] | -0.025 |
| new turbines | A | CatBoost generic | 0.990 [0.986, 0.993] | 0.0191 | +0.0062 | 0.036 [0.020, 0.057] | +0.022 |
| new turbines | A | empirical curve (median) | 0.993 [0.991, 0.994] | 0.0154 | +0.0001 | 0.039 [0.031, 0.048] | -0.000 |
| new turbines | A | theoretical curve | 0.645 | 0.1349 | -0.1296 | 0.465 | -0.465 |
| new turbines | A | climatology | 0.029 | 0.2713 | +0.0002 | 0.454 | -0.002 |
| new turbines | B | **CatBoost per farm** | **0.972 [0.965, 0.978]** | 0.0306 | +0.0017 | **0.036 [0.029, 0.043]** | -0.000 |
| new turbines | B | CatBoost pooled | 0.965 [0.962, 0.968] | 0.0339 | +0.0040 | 0.036 [0.030, 0.043] | +0.003 |
| new turbines | B | CatBoost generic | 0.925 [0.915, 0.935] | 0.0660 | +0.0430 | 0.132 [0.114, 0.147] | +0.127 |
| new turbines | B | empirical curve (median) | 0.960 [0.957, 0.963] | 0.0353 | +0.0039 | 0.043 [0.039, 0.046] | +0.004 |
| new turbines | C | **CatBoost per farm** | **0.960 [0.956, 0.963]** | 0.0381 | -0.0101 | **0.058 [0.050, 0.065]** | -0.042 |
| new turbines | C | CatBoost pooled | 0.960 [0.957, 0.964] | 0.0378 | -0.0096 | 0.058 [0.051, 0.065] | -0.041 |
| new turbines | C | CatBoost generic | 0.960 [0.957, 0.962] | 0.0397 | -0.0137 | 0.061 [0.054, 0.067] | -0.053 |
| new turbines | C | empirical curve (median) | 0.957 [0.954, 0.960] | 0.0372 | +0.0039 | 0.047 [0.042, 0.052] | -0.000 |
| future | A | **CatBoost per farm** | **0.997 [0.996, 0.997]** | 0.0102 | -0.0010 | **0.013 [0.009, 0.018]** | -0.003 |
| future | A | empirical curve (median) | 0.993 [0.991, 0.995] | 0.0140 | +0.0039 | 0.033 [0.023, 0.043] | +0.013 |
| future | A | per-turbine curve | 0.994 [0.992, 0.996] | 0.0123 | +0.0029 | 0.026 [0.023, 0.031] | +0.010 |
| future | B | **CatBoost per farm** | **0.981 [0.973, 0.987]** | 0.0248 | +0.0016 | **0.020 [0.016, 0.023]** | +0.004 |
| future | B | empirical curve (median) | 0.970 [0.958, 0.979] | 0.0308 | +0.0073 | 0.044 [0.032, 0.055] | +0.025 |
| future | C | **CatBoost per farm** | **0.969 [0.963, 0.973]** | 0.0304 | +0.0025 | **0.040 [0.032, 0.048]** | -0.001 |
| future | C | empirical curve (median) | 0.959 [0.951, 0.966] | 0.0336 | +0.0099 | 0.051 [0.044, 0.059] | +0.016 |
| future | C | per-turbine curve | 0.963 [0.956, 0.968] | 0.0319 | +0.0060 | 0.047 [0.040, 0.056] | +0.015 |

The diagnostic SCADA-complete model reaches R2 0.983 to 0.998 and WAPE 0.011 to 0.034: that is the ceiling with
information nobody has seven days ahead. The full table, with every model and both schemes, is in
`cache/ml2_baseline/results_main.csv`.

**CatBoost against the empirical curve** (paired bootstrap over turbines, CatBoost per farm minus the curve):

| scheme | farm | R2 difference [CI] | WAPE difference [CI] | beats the curve? |
|---|---|---|---|---|
| new turbines | A | +0.001 [+0.001, +0.002] | -0.008 [-0.014, -0.003] | yes, both |
| new turbines | B | +0.012 [+0.005, +0.017] | -0.006 [-0.013, -0.000] | yes, both |
| new turbines | C | +0.003 [-0.001, +0.006] | +0.011 [+0.000, +0.020] | **no** (energy bias -4.2%) |
| future | A | +0.003 [+0.002, +0.005] | -0.020 [-0.026, -0.013] | yes, both |
| future | B | +0.011 [+0.007, +0.015] | -0.024 [-0.036, -0.013] | yes, both |
| future | C | +0.010 [+0.006, +0.014] | -0.012 [-0.020, -0.004] | yes, both |

How to read it:
- **The margin over the curve is small.** Wind speed is 87 to 98% of every CatBoost model's feature importance. CatBoost
  wins mostly where it knows the turbine (the future scheme).
- **For a new C turbine CatBoost is worse than the curve on energy**: its prior for an unseen turbine runs 4% low.

### 3.2 Ordering turbines of the same park (the decision)

Pair accuracy [95% CI], first with each turbine's own measured wind, then with the park's wind (one weather row for all
turbines of the park, as at serving):

| scheme | farm | model | own wind | park wind | park wind, gap >= 5% | Spearman, park |
|---|---|---|---|---|---|---|
| new turbines | A | CatBoost per farm | 0.800 [0.648, 0.958] | 0.452 [0.293, 0.734] | 0.434 | -0.19 |
| new turbines | A | theoretical curve | 0.843 [0.722, 0.913] | 0.500 (ties) | 0.500 | 0.00 |
| new turbines | B | CatBoost per farm | 0.882 [0.783, 1.000] | 0.487 [0.351, 0.658] | 0.559 | - |
| new turbines | C | CatBoost per farm | 0.867 [0.788, 0.932] | 0.474 [0.299, 0.653] | 0.476 | -0.14 |
| new turbines | C | CatBoost generic | 0.889 [0.838, 0.937] | 0.522 [0.410, 0.625] | 0.538 | 0.06 |
| future | A | CatBoost per farm | 0.966 [0.889, 1.000] | 0.627 [0.167, 0.905] | 0.676 | 0.36 |
| future | A | **CatBoost per farm, park wind** | 0.966 [0.875, 1.000] | **0.797 [0.739, 0.900]** | 0.811 | 0.79 |
| future | A | climatology (turbine x hour) | 0.814 [0.556, 0.905] | 0.814 [0.556, 0.905] | 0.865 | 0.43 |
| future | A | per-turbine curve | 0.966 [0.875, 1.000] | 0.678 [0.125, 0.905] | 0.784 | 0.36 |
| future | B | **CatBoost per farm, park wind** | 1.000 | **0.900** (10 pairs) | 0.800 | - |
| future | B | climatology (turbine x hour) | 0.400 | 0.400 | 0.600 | - |
| future | C | CatBoost per farm | 0.957 [0.833, 1.000] | 0.468 [0.167, 0.741] | 0.475 | -0.11 |
| future | C | **CatBoost per farm, park wind** | 0.936 [0.789, 1.000] | **0.734 [0.442, 0.938]** | 0.787 | 0.57 |
| future | C | climatology (turbine x hour) | 0.681 [0.339, 0.932] | 0.681 [0.339, 0.932] | 0.725 | 0.33 |
| future | C | CatBoost generic, any curve | 0.947 | 0.500 (ties) | 0.500 | 0.00 |

How to read it:
- **With its own wind, every model orders well, including the theoretical curve** (0.81 to 1.00). Most of the ordering
  comes from each turbine's own measured wind, and that is not available at serving: there is one forecast row per park.
- **With the park's wind, a new turbine cannot be ordered.** A model that does not know the turbine gives identical
  predictions, which is 0.5 by construction.
  - The values below 0.5 for new turbines are a leave-one-out artifact: a turbine's prediction comes from a model trained
    without it, so a strong turbine meets a lower curve.
- **Known turbines can be ordered only by a model trained on the park's wind** (`CatBoost per farm, park wind`): 0.80
  (A), 0.90 (B, 10 pairs), 0.73 (C). The intervals are wide (59 / 10 / 94 pairs), and in A and C it is not shown to beat
  plain climatology per turbine (0.81, 0.68).
- **A model trained on each turbine's own wind and then fed park wind** (`CatBoost per farm`) does not order known
  turbines (0.63 / 0.50 / 0.47). Its turbine effect is conditional on the turbine's own wind, so the position-in-park
  effect (wakes, terrain) is missing.

### 3.3 Forecast error (the CARE numbers are an upper bound)

The test wind was perturbed with an error shared by the park:
- AR(1) with r = 0.95 per hour;
- standard deviation 1.5 / 2.2 / 3.3 m/s, taken as typical NWP hub-height errors at 1, 3 and 7 days. **These values are
  assumed, not measured on our parks.**
- "ramp" grows the error from day 1 to day 7 within each week.

CatBoost per farm, new turbines:

| farm | R2: measured / day 1 / day 3 / day 7 | WAPE 7d: measured / day 1 / day 3 / day 7 / ramp |
|---|---|---|
| A | 0.994 / 0.842 / 0.681 / 0.365 | 0.032 / 0.146 / 0.213 / 0.313 / 0.229 |
| B | 0.972 / 0.779 / 0.601 / 0.298 | 0.036 / 0.136 / 0.187 / 0.257 / 0.197 |
| C | 0.960 / 0.723 / 0.507 / 0.148 | 0.058 / 0.159 / 0.220 / 0.303 / 0.229 |

- **The forecast error swamps everything else.** A realistic 7-day energy error is 20 to 23% (ramp), against 3 to 6% with
  measured wind. Under noise CatBoost stays at or slightly above the empirical curve (C day 7: R2 0.15 against 0.06).
- **A shared error barely moves the ordering:** the park-wind model in the future scheme keeps 0.80 (A), 0.70 (C), and B
  falls from 0.90 to 0.70.
- **Not modelled:** the systematic part of forecast error (grid cell against hub, smoothed peaks). It can only be
  measured against the parks' own production.

### 3.4 A park that is not in CARE (generic model, leave one farm out)

| farm held out | model | R2 [95% CI] | WAPE 7d [95% CI] | energy bias 7d |
|---|---|---|---|---|
| A | CatBoost generic | 0.981 [0.977, 0.985] | 0.048 [0.034, 0.065] | +0.023 |
| A | empirical curve of the other two farms | 0.977 | 0.055 | +0.040 |
| B | CatBoost generic | 0.888 [0.874, 0.903] | 0.163 [0.144, 0.180] | +0.157 |
| B | empirical curve of the other two farms | 0.885 | 0.177 | +0.175 |
| C | CatBoost generic | 0.913 [0.909, 0.916] | 0.133 [0.128, 0.138] | -0.131 |
| C | empirical curve of the other two farms | 0.908 | 0.118 | -0.109 |

On a new park, a power curve borrowed from other parks misses the energy level by 2 to 16% **before** any forecast error,
because turbine types differ. In C the generic model is worse than the borrowed curve.

### 3.5 Expected production against what turbines really produced

Future scheme. Availability is measured on each turbine's training period, then applied to the test weeks.

| farm | WAPE, available only | bias, available only | WAPE, available x availability | bias, available x availability |
|---|---|---|---|---|
| A | 0.035 | +0.022 | 0.054 | -0.027 |
| B | 0.158 | +0.156 | 0.155 | -0.090 |
| C | 0.294 | +0.286 | 0.204 | +0.007 |

- **The factor fixes the level in C**, overcorrects in B and makes A worse.
- **One constant is crude:** curtailment depends on wind (only at high wind), stops do not.

## 4. Ablations (future scheme, CatBoost per farm, same tree count)

| change | R2 A / B / C | WAPE 7d A / B / C |
|---|---|---|
| main | 0.997 / 0.981 / 0.969 | 0.013 / 0.020 / 0.040 |
| no temperature | 0.997 / 0.979 / 0.969 | 0.014 / 0.023 / 0.040 |
| no direction (A, B) | 0.997 / 0.979 / - | 0.013 / 0.021 / - |
| no turbine id | 0.996 / 0.979 / 0.966 | 0.020 / 0.031 / 0.048 |
| no hour, no day of year | 0.997 / 0.976 / 0.967 | 0.012 / 0.021 / 0.042 |
| wind speed and turbine only | 0.995 / 0.972 / 0.965 | 0.027 / 0.042 / 0.046 |
| plus gust factor | 0.997 / 0.981 / 0.969 | 0.013 / 0.019 / 0.039 |

- **Temperature, direction, time and gusts each change WAPE by at most 0.003**, within the intervals.
- **The turbine id is worth 0.7 to 1.1 WAPE points** for known turbines.
- **Pair accuracy in this table moves by single pairs** (B has 10), so it is not read here.

## 5. Deliverables

- `notebooks/care_ml2_power_baseline.ipynb`: executed, 296 KB. Inline figures are small; full-size PNGs are in the cache.
- `models/ml2/`:
  - `ml2_cf_generic.cbm`: the only model usable on parks outside CARE;
  - `ml2_cf_pooled.cbm`, `ml2_cf_farm_A.cbm`, `ml2_cf_farm_B.cbm`, `ml2_cf_farm_C.cbm`: CARE turbines only;
  - `feature_contract.json`: which `park_wind_forecast` column feeds which feature, with units and transforms, the target,
    the energy conversion, the unused columns and why, and the headline metrics.
- **File sizes.** Every file is under the 500 KB hook. B (598 trees), pooled (361) and generic (600) would have been
  larger, so they keep their first 391 / 335 / 418 trees. That changes their in-sample output by an RMS of 0.0074 /
  0.0011 / 0.0036 cf. The CV numbers above are for the untruncated models.
- `dataset/wind_turbine_scada_fault/cache/ml2_baseline/`:
  - `ml2_weekly_predictions.parquet`: one row per scheme, turbine, timeline and calendar week (4,339 rows).
    - Energy columns are in capacity-factor hours (MWh = value x `capacity_kw` / 1000): true energy; CatBoost per farm
      with own and with park wind; the park-wind model; pooled; generic; the three baselines.
    - Also the availability used and `expected = CatBoost per farm x availability`. Availability is the turbine's
      training-period value in the future scheme, the farm median in the new-turbine scheme.
    - `week_start` is an anonymised CARE date.
  - `results_*.csv`, `availability_per_turbine.csv`, `cleaning_cut.csv`, `averaging_bias.csv`, `iterations.csv`, PNGs.

## 6. What does not work

- **Ordering turbines of the same park from the park forecast is mostly not possible.**
  - All turbines of a park get the same forecast row, so weather alone gives identical predictions.
  - For a turbine without history the order is a coin flip.
  - With history, a park-wind model reaches 0.73 to 0.80 on few pairs, not shown better than per-turbine climatology.
- **In production this is worse.**
  - The database turbines are not CARE turbines and have no production history, so no turbine id can be used.
  - The `turbine` table has no `capacity_kw` (`db_get_turbine_location` returns a constant 2050 kW).
  - Every turbine of a park therefore gets the same MWh from ML2, and the decision falls through to the next sort key.
- **The current agent tool returns 0 MWh.** `predict_wind_power_mwh` reads `mean_predicted_kw`, a key that
  `predict_wind_power` never returns, so it computes 0.0 for every turbine.
- **CatBoost barely beats the empirical curve** (R2 +0.001 to +0.012), and not on energy for new C turbines.
- **A new park:** the generic model misses the energy level by +16% (B) or -13% (C) even with perfect wind.
- **Forecast error dominates:** 7-day WAPE goes from 3-6% to about 20-23% under the assumed errors.
- **The available curve of B and C is about 14% low at high wind:** the conservative curtailment rule keeps mild
  setpoints.
- **The availability factor** is a single constant per turbine. It improves C, overcorrects B and hurts A.
- **Temperature, direction, hour, day of year and gusts add nothing measurable.**

## 7. Where the specification did not hold on the data

1. **Negative power share**: measured 29.3% (A), 19.4% (B), 16.3% (C), not 13-29%. p99 and the Farm C ambient median
   (28.1 C) match.
2. **Curtailment is the normal regime in B and C**, not an exception. At 13 to 20 m/s, 53% (B) and 47% (C) of rows are
   held below the curve, all with status 0. B's available-power signal confirms it.
   - "Available production" is what a turbine *can* produce. What the park *did* produce is about 20% lower (availability
     0.81 / 0.79).
3. **"Same 7-day window" needed real time alignment.** About half of the overlaps between different turbines are
   time-aligned, so time groups were built (2.3).
4. **The order between turbines of the same park cannot come from the forecast**, which is one row per park. It can only
   come from what the model knows about each turbine.
5. **`capacity_kw` from the database** does not exist; a constant is used.
6. **Wind cube and bins** carry nothing extra for a tree model. **Gusts** have no matching scale in CARE.
7. **Model size**: depth 6 and up to 600 trees exceed 500 KB (about 1.1 KB per tree), so trees were dropped (section 5).
   The 600-tree cap was reached by B and the generic model.

## 8. How to compare a new ML2 model against this baseline

Same target and cleaning (section 2), same hours (`has_target`), same new-turbine folds (`cv_folds.parquet`, seed 0) and
future split (first 80% of each timeline), same pairs (time groups, calendar weeks, at least 120 common clean hours). Only
features computable from `park_wind_forecast`. A new model counts as better only if all of these hold:

1. **It beats the empirical median curve** per farm and in both schemes, with a paired turbine-bootstrap interval of the
   WAPE difference below zero. **And it beats this baseline:**
   - new turbines, CatBoost per farm: R2 0.994 / 0.972 / 0.960, WAPE 0.032 / 0.036 / 0.058;
   - future: R2 0.997 / 0.981 / 0.969, WAPE 0.013 / 0.020 / 0.040.
2. **Ordering is judged with park wind only**, in the future scheme:
   - bars: 0.797 / 0.900 / 0.734 (the park-wind model) and climatology per turbine 0.814 / 0.400 / 0.681;
   - a claim needs the interval above 0.5 and above climatology;
   - new-turbine park-wind accuracy is 0.5 by construction and is not evidence either way.
3. **It is reported under forecast error** (the ramp case). Bar, 7-day WAPE: 0.229 / 0.197 / 0.229.
4. **For a model meant for parks outside CARE**, leave one farm out. Bar, 7-day WAPE: 0.048 / 0.163 / 0.133.
5. **No status column, no rotor, pitch, internal temperature or power lag** as input. A model that needs them is a
   diagnostic, like the SCADA-complete one.

## 9. Is the model worth improving? (verdict, 2026-11-08)

**What the R2 of about 0.98 measures.**
- It is the mean over the three farms: 0.975 for new turbines, 0.982 for the future scheme.
- It uses the wind **measured** at the nacelle. It shows how well the model turns wind into power, not how well ML2 will
  predict next week.

**There is little room left in turning wind into power.**
- The empirical curve already reaches 0.957 to 0.993.
- CatBoost adds +0.001 to +0.012.
- The SCADA-complete ceiling, with rotor speed and pitch (not available at serving), is 0.983 to 0.998.
- Every extra input the forecast offers (temperature, direction, hour, gusts) adds nothing measurable.
- **Tuning CatBoost or adding forecast features is not worth the effort.**

**What limits ML2 in use, by impact:**
1. **Forecast error.**
   - Under the assumed errors, hourly R2 falls to 0.72-0.84 at day 1 and 0.15-0.37 at day 7; the 7-day WAPE becomes
     0.20-0.23.
   - What pays off: measure the real Open-Meteo error at our parks (archived forecasts against production) and correct
     it, for example with a per-park bias correction of `wind_speed_100m`. Once production history exists, train on the
     forecast instead of measured wind.
2. **Ordering turbines of the same park.** It needs information per turbine; without it ML2 returns ties.
   - What pays off: a capacity per turbine in the database, and a production history per turbine (availability, the
     offset of its position in the park).
3. **A park outside CARE.** The turbine type is unknown, so the energy level can be off by up to 16%.
   - What pays off: store the turbine model, rated power and rated wind speed per park, or calibrate the curve on the
     first weeks of production.
4. **Wiring.** The current agent tool returns 0 MWh (`predict_wind_power_mwh` reads a key that does not exist).
   - What pays off: replace it with the ML2 function proposed for `smarthack/wind/ml2.py` (rank 1) and
     `services/agent/tools.py` (rank 3).

**Verdict.** Keep the CatBoost models as they are, as the ML2 baseline. Put further work into the forecast input, the
turbine data in the database and the wiring, not into the model.
