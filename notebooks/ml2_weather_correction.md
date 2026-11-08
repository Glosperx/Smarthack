# ML2 with real forecast error: Open-Meteo at Kelmarsh, correction and horizons

**Status: this replaces the assumed forecast error of the ML2 baseline with a measured one.** Section 0 of
`care_ml2_power_15min.md` simulated the error (1.5 / 2.2 / 3.3 m/s at day 1 / 3 / 7, AR(1) r = 0.95), because CARE
locations are anonymised. Here the error is measured on archived Open-Meteo forecasts against a real park, Kelmarsh (UK),
corrected, and pushed through the same wind-to-power recipe.

Source: `notebooks/ml2_weather_correction.ipynb`, run from scratch on 2026-11-08 in the conda env `ml_def` (catboost
1.2.10) with nbconvert, 0 errors, under a minute once the forecasts are cached. Every number below comes from that run.
No independent review was run on it.

## 0. THE new ML2 reference with real forecast error

R2 per quarter hour, every clean quarter of the six Kelmarsh turbines in the test months (Sep-Dec 2024, never used for
fitting). WAPE is the energy error: daily energy per turbine for a lead day, weekly energy per turbine for the measured
wind and the whole week.

| lead time | assumed error, baseline method | app today (best_match 100 m, raw) | raw ECMWF 80 m | mean of 7 models, raw | **corrected: weights per lead day, expected power** |
|---|---|---|---|---|---|
| measured wind (no forecast error) | 0.972 | 0.972 | 0.972 | 0.972 | 0.972 |
| day 1 | 0.740 | 0.092 | 0.479 | 0.549 | **0.799** |
| day 3 | 0.510 | 0.189 | 0.274 | 0.426 | **0.685** |
| day 7 | 0.108 | -0.160 | -0.085 | 0.013 | **0.333** |
| **whole week** (day k uses lead day k) | 0.464 | 0.089 | 0.198 | 0.326 | **0.592** |

| WAPE of the energy | assumed error | app today | raw ECMWF 80 m | mean of 7 models, raw | **corrected** |
|---|---|---|---|---|---|
| measured wind, weekly | 0.019 | 0.019 | 0.019 | 0.019 | 0.019 |
| day 1, daily | 0.284 | 0.673 | 0.462 | 0.414 | **0.183** |
| day 3, daily | 0.401 | 0.559 | 0.504 | 0.439 | **0.249** |
| day 7, daily | 0.556 | 0.606 | 0.569 | 0.575 | **0.482** |
| **whole week, weekly** | 0.253 | 0.477 | 0.410 | 0.381 | **0.197** |

How to read it:
- **"Assumed error"** is the baseline's simulation applied to these same Kelmarsh turbines and quarters (seeds 500-502),
  so the columns compare like with like.
- **The application today** reads `wind_speed_100m` from Open-Meteo without `models` (the `best_match` mix). Raw, it
  **over-forecasts the energy by 46% over the week** (+67% at day 1): the forecast wind is 1.2-2.0 m/s above the nacelle
  wind that the power model was trained on.
- **After correction the real forecast is better than the assumed one** at every lead time: R2 over the week 0.59
  against 0.46, weekly WAPE 0.20 against 0.25.
- **The corrected energy is low by 5-15% per day** (weekly -10%) in these autumn-winter test months, after a fit on
  spring-summer. A monthly refit is the cure (section 7).

**Rule for every later ML2 model.** Report this table: Kelmarsh, same test months, same clean quarters, same lead days.
Count a model as better only if it beats the corrected column on the whole-week row (R2 0.592, weekly WAPE 0.197)
without being worse at day 1 (0.799 / 0.183). The CARE table of `care_ml2_power_15min.md` stays the reference for
CARE-specific questions (turbine ordering, new turbines).

## 1. Checks before any computation

### 1.1 Site and time

| item | value | source |
|---|---|---|
| park | Kelmarsh, UK, 6 x Senvion MM92, 2050 kW, rotor 92 m, in operation since 2016-04-15 | `Kelmarsh_WT_static.csv` of the Zenodo record (Cubico, v4, record 16807551) |
| coordinates | 52.3988-52.4038 N, -0.9495 to -0.9361 E; centre 52.4015 N, -0.9431 E | same file |
| hub height | **78.5 m** (T01, T02, T04, T05) and **68.5 m** (T03, T06); nearest Open-Meteo level: **80 m** | same file |
| time zone | **UTC** | header of every yearly SCADA export |
| timestamp | **start of the 10-minute interval** (a row at 00:00 covers 00:00-00:10) | inferred: headers give `2020-01-01 00:00:00 - 2021-01-01 00:00:00` and rows run 00:00-23:50; not stated in the documentation |
| SCADA range | 2016-01-21 to **2024-12-31 23:50**, 2,816,215 rows | `kelmarsh_10min.parquet` and the raw CSVs |

### 1.2 What Open-Meteo archives (documentation of 2026-11, then probed at the park)

- **Historical Forecast API**: the first hours of each run stitched into one series, from about 2021-2022. A near-analysis,
  **not a forecast at a lead time**, so it cannot measure the day-1 to day-7 error.
- **Previous Runs API**: each variable at fixed lead offsets, `<variable>_previous_dayN`, the value predicted N x 24 h
  before the valid time. Documented from January 2024 (GFS temperature from March 2021).
- **Single Runs API**: whole runs by start time; ECMWF IFS HRES from March 2024, other models from April 2026.

Probed at Kelmarsh (80 / 100 / 120 m wind, every global model):

| model (Open-Meteo name) | levels | lead days | first day with day 1..7 |
|---|---|---|---|
| ECMWF IFS 0.25 (`ecmwf_ifs025`) | 80, 100, 120 m | 0-7 | 2024-03-06 (day 7 from 03-13) |
| GFS (`gfs_global`) | 80, 100, 120 m | 0-7 | 2024-02-16 |
| ICON (`icon_global`) | 80, 100, 120 m | 0-6 | 2024-02-16 |
| ICON-EU (`icon_eu`) | 80, 100, 120 m | 0-4 | 2024-02-16 |
| GEM (`gem_global`) | 80, 120 m | 0-7 | 2024-02-16 |
| BOM ACCESS (`bom_access_global`) | 80, 120 m | 0-7 | 2024-02-17 |
| CMA GRAPES (`cma_grapes_global`) | 120 m (80 and 100 m only day 0) | 0-7 | 2024-02-16 |
| `best_match` (what the app gets) | 80, 100 m | 0-7 | 2024-03-06 |
| UK Met Office, JMA, ECMWF 9 km, ECMWF AIFS | none at a lead day | - | - |

GFS wind has no lead-day archive before 2024 either. **Overlap with Kelmarsh: about 10 months**, 2024-03-13 to
2024-12-31 with every model at every lead day: above the 6-month threshold, so the study went on. The cost: one year,
so season cannot be learned from repeated years.

Forecasts were downloaded month by month (77 + 11 requests, 3 s apart, cached as parquet in
`dataset/ml2_weather/open_meteo/`, not in git).

## 2. Data

- **Clean 10-minute row** (wind truth and power target): wind 0-40 m/s and power present; `Lost Production to Downtime
  and Curtailment Total` = 0 (missing counts as not clean); not a silent stop (wind >= 4.5 m/s and power <= 1% of
  rated); anemometer not stuck (same value > 0 over 6 slots). 96.2% of rows are clean (1.3% invalid, 3.6% downtime or
  curtailment, 1.7% silent stops). `Turbine Power setpoint` follows production (median 1252 kW), so it was not used.
- **Wind truth at the full hour H** (forecasts are instantaneous): mean of clean rows from H-30 to H+30 min, at least 4
  of 6 per turbine; park truth = mean over at least 3 turbines. 77,057 park hours.
- **Power target `cf15`** exactly as ML2: 5-minute halves, three per quarter, all clean; cf = power / 2050 kW, idle
  consumption set to 0. 1,801,201 clean quarters.
- **Caveat**: the truth is the **nacelle** anemometer behind the rotor. Part of the raw bias below is that instrument and
  the height, not the weather model; it is real for ML2 anyway, because the power model learns on nacelle wind.

## 3. Real forecast error (2024-03-13 to 2024-12-31, hourly, park mean)

RMSE (m/s), raw, every model and lead day:

| lead day | ECMWF | GFS | ICON | ICON-EU | GEM | BOM | CMA | mean of 7 | best_match 100 m |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 1.77 | 1.92 | 1.68 | 1.59 | 1.79 | 1.84 | 1.95 | 1.64 | 2.08 |
| 1 | 1.85 | 2.12 | 1.82 | 1.77 | 1.95 | 2.22 | 2.44 | 1.79 | 2.32 |
| 2 | 1.95 | 2.13 | 1.96 | 1.92 | 2.18 | 2.38 | 2.69 | 1.83 | 2.10 |
| 3 | 2.16 | 2.33 | 2.32 | 2.27 | 2.45 | 2.88 | 2.97 | 2.02 | 2.30 |
| 4 | 2.62 | 2.72 | 2.68 | 2.62 | 2.68 | 3.20 | 3.26 | 2.24 | 2.74 |
| 5 | 2.81 | 3.06 | 3.04 | - | 3.20 | 3.41 | 3.33 | 2.44 | 2.93 |
| 6 | 2.97 | 3.33 | 3.17 | - | 3.35 | 3.51 | 3.60 | 2.46 | 3.08 |
| 7 | 3.02 | 3.55 | - | - | 3.40 | 3.78 | 3.72 | 2.62 | 3.13 |

Bias (forecast minus measured) is **+0.9 to +1.7 m/s for every model and lead day** (ECMWF +1.0 to +1.3; mean of 7 +1.2
to +1.4; best_match +1.2 to +1.7). MAE: ECMWF 1.51 / 1.72 / 2.40 at day 1 / 3 / 7, mean of 7 1.45 / 1.58 / 2.06.

**Real against assumed error:**

| lead day | assumed SD | ECMWF SD | ECMWF bias | ECMWF RMSE | mean of 7 SD | mean of 7 RMSE | best_match SD | best_match RMSE | r hour-to-hour (ECMWF) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1.5 | 1.34 | +1.28 | 1.85 | 1.27 | 1.79 | 1.59 | 2.32 | 0.81 (assumed 0.95) |
| 3 | 2.2 | 1.80 | +1.19 | 2.16 | 1.59 | 2.02 | 1.84 | 2.30 | 0.87 |
| 7 | 3.3 | 2.86 | +0.99 | 3.02 | 2.31 | 2.62 | 2.91 | 3.13 | 0.93 |

- **The random part of the error is smaller than assumed** (SD 10-20% lower for ECMWF, 15-30% lower for the mean of
  models) and less persistent hour to hour.
- **A systematic bias of about +1.2 m/s was not in the assumption.** It costs more than the random part raw, and it is
  the easiest to remove.

By hour, direction and season (ECMWF, raw; full tables in the notebook, section 3.2):
- **hour:** day-1 bias +1.06 (09-12 UTC) to +1.43 m/s (18-24 UTC): larger in the stable night;
- **direction:** day-1 bias +0.75 (N) to +1.65 m/s (SE); RMSE 1.42 (N) to 2.15 m/s (S, SE). South-west is the most frequent
  sector (1737 h);
- **season:** day-1 RMSE 1.65 (summer) to 2.02 m/s (spring); each season is seen once, so this is not a seasonal
  correction.

By turbine (ECMWF day 1 against each turbine's own wind): bias +0.89 (T02) to +1.65 m/s (T06); the two 68.5 m turbines
are among the highest (T03 +1.38, T06 +1.65). SD is the same everywhere (1.39-1.51).

80 m against 100 m: 100 m is worse for every model (ECMWF day-1 RMSE 2.02 against 1.85, GFS 2.41 against 2.12, ICON 2.70
against 1.82). The level nearest to the hub is the right input.

## 4. Wind correction (train 2024-03-13 to 08-31, test 2024-09-01 to 12-31)

Test RMSE (m/s) by lead day:

| method | d0 | d1 | d2 | d3 | d4 | d5 | d6 | d7 |
|---|---|---|---|---|---|---|---|---|
| (a) raw ECMWF | 1.79 | 1.88 | 2.00 | 2.25 | 2.68 | 2.84 | 3.00 | 2.99 |
| (a) raw best single (chosen on train) | 1.60 | 1.80 | 2.00 | 2.25 | 2.84 | 2.84 | 3.00 | 2.99 |
| app today: best_match 100 m raw | 2.28 | 2.62 | 2.16 | 2.40 | 2.80 | 2.98 | 3.13 | 3.10 |
| (a2) ECMWF, linear a + b x | 1.06 | 1.18 | 1.38 | 1.63 | 2.10 | 2.17 | 2.36 | 2.46 |
| (b) mean of 7, raw | 1.67 | 1.81 | 1.84 | 2.09 | 2.33 | 2.49 | 2.49 | 2.65 |
| (b2) mean of 7, minus train bias | 1.15 | 1.28 | 1.37 | 1.64 | 1.93 | 2.07 | 2.13 | 2.34 |
| **(c) weights per lead day** | **0.85** | **0.99** | **1.16** | **1.40** | **1.75** | **1.93** | **2.06** | **2.27** |
| (d) CatBoost MOS, chosen variant (hybrid, no season), P50 | 0.84 | 1.00 | 1.16 | 1.41 | 1.77 | 1.94 | 2.06 | 2.27 |
| (d) CatBoost MOS, direct, with season, P50 | 1.18 | 1.28 | 1.38 | 1.61 | 1.85 | 2.05 | 2.15 | 2.35 |

**Gain against raw ECMWF** (RMSE reduction): (b) 4-17%; (b2) 22-36%; **(c) 24-52%** (47% at day 1, 38% at day 3, 24% at
day 7). Where the gain comes from:
- **bias removal: two thirds or more** ((b2) against (b): 32 of the 47 points at day 1, 22 of 24 at day 7);
- **weights per lead day: the rest**, significant up to day 5 ((c) - (b2): -0.28 [-0.36, -0.22] m/s at day 1, -0.24
  [-0.38, -0.12] at day 3, -0.08 [-0.26, +0.11] at day 7; paired bootstrap over the 122 test days);
- **CatBoost: nothing.** (d) - (c) is within +/-0.02 m/s at every lead day, never significant.
- **Choosing the single best model gains little**: the best one changes with the lead day (ICON-EU at short leads,
  ECMWF later); it beats the plain mean only at day 0 (1.60 against 1.67) and ties it at day 1, and from day 2 on the
  mean wins.

The weights (fitted on train): ECMWF has the largest weight up to day 3 (0.20-0.28); from day 4 GFS, GEM and ECMWF share
it (0.10-0.16 each); ICON global gets nothing up to day 4 and CMA almost nothing except at day 5. The intercept grows from 0.6 to 2.2 m/s and the sum of weights falls from 0.74 to 0.50 with lead day:
at long leads the correction pulls the forecast towards the mean, as a good MOS should.

**Interval P10-P90** (nominal 0.80), test:

| method | coverage d0-d7 | width d1 / d3 / d7 (m/s) | mean pinball d1 / d3 / d7 |
|---|---|---|---|
| **(c) + 9 train residual quantiles per lead day** | **0.76-0.79** | 2.27 / 3.17 / 5.15 | 0.303 / 0.420 / 0.685 |
| (d) chosen, calibrated on out-of-fold train | 0.75-0.80 | 2.26 / 3.18 / 5.44 | 0.305 / 0.419 / 0.686 |
| (d) direct, with season | 0.70-0.80 | 2.63 / 3.11 / 4.77 | 0.368 / 0.476 / 0.716 |

The CatBoost quantiles depend on direction, hour and model spread, but they are not better than the fixed residual
quantiles of (c).

**How the CatBoost variant was chosen, and a disclosure.** The direct CatBoost of the task statement (with day of year)
was run on test first: early stopping kept 55 trees and it lost to (c). A hybrid form (CatBoost on the residual of (c)) was
then added, and the choice among four variants (direct / hybrid, with / without season) was made by forward validation
inside train (fit before June, July, August; validate on that month), by pinball loss: hybrid without season won (0.409,
against 0.432 for direct with season). The test was not used for that choice. Day of year hurts because the train months
(March-August) never contain the test season.

## 5. Power through the ML2 recipe

- **Wind-to-power model, untuned:** CatBoost with the ML2 parameters and the generic 15-minute features, trained on
  Kelmarsh **measured** wind 2016-01 to 2024-08 (333 trees by early stopping on the last 12 months before test). With
  measured wind it reaches R2 **0.972** per quarter and weekly WAPE 0.019 on the test months, the same level as CARE
  (0.94-0.97).
- **Serving recipe of `feature_contract_15min.json`:** the hourly forecast is instantaneous at the full hour, interpolated
  to quarter centres; one park forecast for all six turbines.
- **Expected power:** the 9 quantile series of the corrected wind each go through the power model and the 9 powers are
  averaged. Power is convex below rated, so the power of the average wind is too low; this lifts the energy.

Test, R2 per quarter / WAPE of the daily energy / bias of the daily energy, by lead day:

| scenario | d0 | d1 | d2 | d3 | d4 | d5 | d6 | d7 | whole week |
|---|---|---|---|---|---|---|---|---|---|
| app today, R2 | 0.272 | 0.092 | 0.329 | 0.189 | -0.020 | -0.188 | -0.225 | -0.160 | 0.089 |
| raw ECMWF 80 m, R2 | 0.500 | 0.479 | 0.418 | 0.274 | 0.064 | -0.094 | -0.143 | -0.085 | 0.198 |
| mean of 7 raw, R2 | 0.606 | 0.549 | 0.524 | 0.426 | 0.291 | 0.168 | 0.131 | 0.013 | 0.326 |
| (c) point, R2 | 0.827 | 0.795 | 0.755 | 0.676 | 0.586 | 0.471 | 0.432 | 0.304 | 0.574 |
| **(c) expected power, R2** | **0.829** | **0.799** | **0.760** | **0.685** | **0.599** | **0.493** | **0.453** | **0.333** | **0.592** |
| (d) CatBoost expected power, R2 | 0.826 | 0.790 | 0.752 | 0.672 | 0.584 | 0.472 | 0.443 | 0.323 | 0.577 |
| app today, daily WAPE | 0.616 | 0.673 | 0.529 | 0.559 | 0.617 | 0.647 | 0.629 | 0.606 | 0.477 weekly |
| raw ECMWF 80 m, daily WAPE | 0.457 | 0.462 | 0.467 | 0.504 | 0.569 | 0.600 | 0.593 | 0.569 | 0.410 weekly |
| **(c) expected power, daily WAPE** | **0.162** | **0.183** | **0.204** | **0.249** | **0.308** | **0.361** | **0.409** | **0.482** | **0.197 weekly** |
| app today, energy bias | +0.62 | +0.67 | +0.52 | +0.51 | +0.50 | +0.55 | +0.50 | +0.41 | +0.46 weekly |
| (c) expected power, energy bias | -0.05 | -0.06 | -0.07 | -0.05 | -0.07 | -0.08 | -0.09 | -0.15 | -0.10 weekly |

Paired bootstrap over the 18 test calendar weeks, partial at both ends (difference [95% CI]):

| comparison | day 1 R2 | day 1 WAPE | whole week R2 | whole week WAPE |
|---|---|---|---|---|
| (c) expected power - raw ECMWF | +0.325 [+0.186, +0.570] | -0.281 [-0.419, -0.175] | +0.400 [+0.202, +0.727] | -0.213 [-0.415, -0.056] |
| (c) expected power - app today | +0.725 [+0.467, +1.178] | -0.497 [-0.697, -0.339] | +0.510 [+0.279, +0.899] | -0.281 [-0.503, -0.105] |
| (c) expected power - (c) point | +0.004 [+0.002, +0.006] | -0.002 [-0.006, +0.002] | +0.018 [+0.002, +0.036] | -0.018 [-0.040, +0.005] |
| (d) CatBoost expected power - (c) expected power | -0.008 [-0.018, +0.000] | +0.009 [-0.002, +0.019] | -0.015 [-0.025, -0.007] | +0.007 [-0.002, +0.019] |

At day 7 the corrected forecast still beats raw ECMWF on R2 (+0.43 [+0.15, +0.88]); the daily WAPE gain (-0.09) is not
significant there.

**Interval in power** ((c), P10 / P90 wind through the power model):
- per quarter it covers only 0.56-0.71 (nominal 0.80): inside-the-hour variation, the gap between one turbine and the park
  mean, and the power model's own error are not in the wind interval;
- for **daily energy** (sum of the quarter P10 and P90) it covers **0.87-0.90**, a conservative band; median width 1.0x
  the energy at day 1, 1.4x at day 3, 2.4x at day 7.

**Carrying the real error to CARE (notebook section 5.1).** CARE locations are anonymised, so the real error can only be
simulated there (`care_ml2_real_error.md`). The simulation was first checked here, against the real forecast, on the
test months:

| error | lead | R2 real | R2, baseline form | R2, park form | WAPE real | WAPE, baseline form | WAPE, park form |
|---|---|---|---|---|---|---|---|
| corrected (c) | day 1 | 0.795 | 0.867 | 0.816 | 0.185 | 0.114 | 0.178 |
| corrected (c) | day 3 | 0.676 | 0.771 | 0.715 | 0.252 | 0.193 | 0.260 |
| corrected (c) | day 7 | 0.304 | 0.516 | 0.317 | 0.479 | 0.376 | 0.513 |
| corrected (c) | week | 0.574 | 0.697 | 0.616 | 0.214 | 0.141 | 0.226 |
| raw ECMWF | day 1 | 0.479 | 0.509 | 0.471 | 0.462 | 0.460 | 0.463 |
| raw ECMWF | week | 0.198 | 0.250 | 0.160 | 0.410 | 0.460 | 0.465 |
| app today | day 1 | 0.092 | 0.089 | 0.118 | 0.673 | 0.678 | 0.656 |
| app today | week | 0.089 | 0.121 | 0.044 | 0.477 | 0.536 | 0.537 |

- **Baseline form** (the method of `care_ml2_power_15min`): each turbine keeps its own measured wind plus an AR(1) error
  shared by the park, with the real bias, SD and r. **It is too optimistic for a corrected forecast** (R2 +0.07 to +0.21),
  for two reasons:
  - at serving one park forecast feeds every turbine, while the simulation keeps each turbine's own wind (with measured
    wind alone this is worth R2 0.972 against **0.926** for one park wind);
  - a corrected forecast shrinks towards the mean (beta 0.83 at day 1, 0.23 at day 7), so its error depends on the true
    wind; an added independent error ignores that.
- **Park form**: one park wind for all turbines, forecast = m + bias + beta x (park wind - m) + u, u AR(1). It lands within
  0.01-0.04 R2 of the real forecast at days 1 and 3 and over the week (slightly optimistic for the corrected forecast,
  slightly pessimistic for raw at day 7). This is the form used for CARE, with the parameters of all 10 months
  (`dataset/ml2_weather/out/real_error_generator.json`).

## 6. Horizons: nowcasting from live SCADA against the corrected forecast

**Nowcasting needs live SCADA (the last hours of power and wind of each turbine). The application's database does not
receive SCADA yet, so this section describes what that feed would add, not something that can run today.**

Nowcast: one CatBoost per horizon (ML2 parameters), pooled turbines, inputs = the last 8 quarters of power, hourly means
3-6 h back, recent nacelle wind, park power, target time. It follows the `kelmarsh_energy/` comparison (XGBoost, LSTM and
Mamba2 within 0.01 R2 of each other at 10-100 min); XGBoost is not installed in `ml_def`, so the boosted trees are
CatBoost. Fitted on 2022-01 to 2024-02; blend weights fitted on 2024-03 to 2024-08 with an out-of-fold forecast; test as
above. The forecast's lead time at a short horizon lies between two bounds the archive gives exactly: day 0 (lead 0-6 h,
optimistic) and day 1 (lead 24-30 h, pessimistic). In the application a run is usable 4-8 h after its start and the job
refreshes every 12 h, so the real case is in between.

Test, R2 per quarter by horizon:

| horizon | persistence | nowcast | forecast, day-0 bound | forecast, day-1 bound | blend, day-0 | blend, day-1 | nowcast weight (day-0 / day-1) |
|---|---|---|---|---|---|---|---|
| 15 min | 0.944 | 0.948 | 0.830 | 0.798 | 0.949 | 0.948 | 0.85 / 0.88 |
| 30 min | 0.900 | 0.908 | 0.828 | 0.798 | 0.911 | 0.909 | 0.70 / 0.76 |
| 1 h | 0.840 | 0.857 | 0.830 | 0.800 | 0.875 | 0.868 | 0.49 / 0.59 |
| 2 h | 0.750 | 0.780 | 0.830 | 0.800 | 0.846 | 0.827 | 0.24 / 0.32 |
| 3 h | 0.669 | 0.710 | 0.830 | 0.800 | 0.837 | 0.812 | 0.14 / 0.18 |
| 4 h | 0.594 | 0.647 | 0.830 | 0.800 | 0.833 | 0.805 | 0.08 / 0.11 |
| 6 h | 0.458 | 0.533 | 0.830 | 0.800 | 0.831 | 0.801 | 0.05 / 0.06 |
| 12 h | 0.109 | 0.300 | 0.830 | 0.800 | 0.830 | 0.800 | 0.03 / 0.02 |
| 24 h | -0.132 | 0.099 | 0.830 | 0.800 | 0.829 | 0.799 | 0.02 / 0.02 |

- **Below about 1 h the nowcast wins alone**; the blend adds 0.001-0.02.
- **From 1 to 3-4 h the blend beats both.**
- **The blend stops adding 0.01 R2 at 3 h (day-0 bound) to 4 h (day-1 bound).** Beyond that the corrected forecast alone
  is as good.

## 7. Recommendations for the application (design only, no code changed)

**Model per horizon:**

| horizon | model | needs |
|---|---|---|
| 0-1 h | nowcast from live SCADA (blend weight 0.85 -> 0.5) | live SCADA feed: not available |
| 1-4 h | blend of nowcast and corrected forecast, weight by horizon (0.5 -> 0.1) | live SCADA feed: not available |
| 4 h - 7 days | **corrected multi-model forecast, expected power, P10-P90 per day** | multi-model forecast; measured wind or production at the park for the correction |
| without live SCADA, every horizon | corrected forecast (R2 0.80-0.83 in the first hours) | as above |

**1. What to ask Open-Meteo.** Name the models instead of the default `best_match`: `models=ecmwf_ifs025,gfs_global,
icon_global,icon_eu,gem_global,bom_access_global,cma_grapes_global`, with `wind_speed_80m`, `wind_direction_80m` (CMA:
`wind_speed_120m`) and the current variables. Reasons: best_match was the worst input here (raw RMSE 2.62 m/s at day 1
on test, against 1.81 for the plain mean of models); its mix differs by region and changes without notice, so a
correction fitted on it cannot be trusted; ICON-EU and every global model cover Romania. For a hub near 100 m, take
`wind_speed_100m` where the model has it (GEM, BOM, CMA do not).

**2. How to store several models.** `park_wind_forecast` is a snapshot overwritten at every refresh, so no history
exists to measure the error at our parks later. Proposed:
- a long, **append-only** table `park_wind_forecast_run` (park_id, model, run_time or fetched_at, forecast_time,
  lead_day, wind_speed_80m, wind_speed_100m, wind_direction_80m), one row per model and hour, keyed on (park_id, model,
  fetched_at, forecast_time);
- `park_wind_forecast` keeps its role (what ML2 reads), with new columns for the corrected hub wind and its P10 / P50 / P90;
- a `park_wind_correction` table: per park and lead day, intercept, weights per model, the 9 residual quantiles, fit
  period and number of hours (the format of `models/ml2/wind_correction_kelmarsh.json`).
- The Previous Runs API can backfill the forecast history of every Romanian park from 2024 today; only the measured side
  is missing.

**3. Where the correction applies.** In the forecast service, after the fetch and before the write: corrected wind =
intercept_d + sum of weight x model wind, per lead day; quantiles = corrected + residual quantiles of that lead day. ML2
then runs the 15-minute recipe on each of the 9 quantile series and averages them (expected power); P10 / P90 power
from the P10 / P90 series. A park with no correction yet falls back to the plain mean of models, flagged as uncorrected.
Refit monthly per park once it has measured wind or clean production.

**4. The interval for the agent and for repair prioritisation.** Give daily energy per turbine as expected (P50) with
P10-P90 (the daily band covers 87-90% here; the per-quarter band covers only 56-71%, so do not show quarters with an
interval):
- **prioritisation:** rank on the expected lost energy, and use the band as a confidence: a repair slot is safe when its
  P90 energy is low (calm even in the windy case); a ranking decided only at day 4-7, where the band is 1.7-2.4x the
  energy, should be re-checked at the next refresh before crews move;
- **agent text:** "expected 12 MWh in the next 3 days (P10-P90: 6-19 MWh)"; say "low confidence" past day 4.

**5. What carries over to the parks in Romania, and what does not.**
- **Transfers:** the method (weights per lead day plus residual quantiles, refitted per park), the choice of models and
  levels, using the expected power over the distribution instead of the power of one wind, the warning that raw
  forecasts fed to a power model trained on nacelle wind over-forecast energy, the shape of the uncertainty (growing
  from day 1 to day 7), and the horizon split (nowcasting only matters below 3-4 h, and only with SCADA).
- **Does not transfer:** the Kelmarsh numbers: the +1.2 m/s bias, the weights, intercepts and quantiles. They mix this
  site's terrain and the nacelle anemometers of MM92 turbines. Applying them in Romania would be guessing; correcting a
  Romanian park needs measured wind or clean production at that park. Until then, its energy is uncorrected and likely
  too high, and the interval should come from the Kelmarsh widths only as a rough prior, labelled as such.

## 8. Deliverables

- `notebooks/ml2_weather_correction.ipynb`: executed, 0 errors, 295 KB.
- `models/ml2/wind_correction_kelmarsh.json` (8 KB): the kept model **and** its contract: per lead day the intercept,
  the weights per model, the 9 residual quantiles; the Open-Meteo request; the formula; the test results; the limits.
  **Kelmarsh only.** The CatBoost MOS was not saved: it did not beat (c) (sections 4 and 5) and would add 470 KB.
- `dataset/ml2_weather/` (not in git): `open_meteo/` (88 monthly parquet files of archived forecasts),
  `kelmarsh_10min_ext.parquet` (SCADA with the cleaning columns), `out/` (CSV of every table, PNG figures,
  `real_error_hourly.parquet` and `real_error_generator.json`, which `care_ml2_real_error.ipynb` reads).

## 9. Limits

- **One park, ten months.** Train March-August, test September-December: different seasons, which is why the corrected
  energy is 5-15% low on test. More months, and a monthly refit, are the fix.
- **Lead day, not exact lead hours.** `previous_dayN` mixes runs from 24N to about 24N + 6 h before the valid time. In
  the week table, day k of the week uses lead day k, as in the baseline; real first-day hours have shorter leads and do
  slightly better (day 0: R2 0.83 against 0.80 at day 1).
- **Nacelle truth.** The target is what the power model needs, not the free wind; the bias is part instrument, part model.
- **The power model for the blend months was trained on a period that includes them** (2016-2024-08); with measured wind
  near its ceiling this hardly matters, but the blend weights are slightly in favour of the forecast.
- **Not reviewed independently.**

Sources: [Kelmarsh wind farm data, Zenodo record 16807551](https://zenodo.org/records/16807551);
[Open-Meteo Previous Runs API](https://open-meteo.com/en/docs/previous-runs-api);
[Open-Meteo Historical Forecast API](https://open-meteo.com/en/docs/historical-forecast-api);
[Open-Meteo Single Runs API](https://open-meteo.com/en/docs/single-runs-api).
