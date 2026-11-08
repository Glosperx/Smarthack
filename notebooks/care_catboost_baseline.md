# CARE CatBoost baseline: reference results

**Status: this is the baseline.** Every later model on CARE (the LSTM with attention first) is compared against the numbers on
this page, on the same folds, labels and checks. Source: `notebooks/care_catboost_baseline.ipynb`, run from scratch on
2026-11-08 in the conda env `ml_def` (catboost 1.2.10) with nbconvert, 0 errors. A second full run gave identical numbers.
Every number below was computed in that run. No independent review was run on it.

## 1. Task

- **Question.** For every turbine and every day, the probability that the turbine needs maintenance, and an alarm flag.
- **Data.** CARE wind-turbine SCADA, `dataset/wind_turbine_scada_fault/raw`, comma variant only (`comma_*.csv`,
  `comma_event_info.csv`). Farms A, B and C: 95 datasets, 36 turbines, 44 anomaly events (A 11, B 6, C 27).
- **Unit.** One (timeline, day). The anchor is the end of day t, so day t's features use data up to the end of that day.
  A timeline is one turbine with only the datasets whose overlapping rows are identical merged (section 6).
- **Main target, horizon k (1 to 7 days).** Positive if day t is inside an anomaly window, or a window starts in (t, t+k].
  Cumulative and monotone in k. **Headline horizon: k = 7.**
- **Strict target (secondary).** Positive only if a window starts in (t, t+k]; days already inside a window are excluded.
- **Excluded from both targets:**
  - the 14 days after a window ends (repair);
  - a 7-day gray zone before the first positive day;
  - days with no baseline: fewer than 90 valid days in the baseline window;
  - days with fewer than 48 valid 10-minute rows.
- **Normal-dataset windows.** Ordinary negative days.
- **Labelled days at k = 7.** A 4,322 (4.70% positive), B 3,209 (8.85%), C 12,289 (5.06%). All 44 events have labelled days.
  Median event length: A 8 days, B 37.5, C 15.

## 2. Setup

**Inputs.**
- `_avg` and `_std` columns only.
- Never used as inputs: `status_type_id`, counters, row counts, absolute wind and nacelle direction.
- Relative wind direction is wrapped to +-180 and kept as a yaw error; Farm B's yaw error is rebuilt from wind minus nacelle
  direction. Pitch and blade or motor positions stay numeric.
- Quasi-constant columns and columns with more than 50% missing are dropped.
- Ambient temperature and wind speed are covariates only.
- Deviation columns kept: A 50, B 111, C 468.

**Deviation.**
- Baseline: a **fixed 120-day trailing window [t-180, t-60)**, refitted every 30 days.
- Each column is regressed on wind, power and ambient (polynomial terms) over the baseline. Power itself becomes a power-curve
  residual (power against wind and ambient).
- The residual is turned into a robust z (median / 1.4826 MAD), and the absolute value is taken on every 10-minute row before
  the daily mean and 95th percentile.

**Features.**
- Per column: daily mean |rz|, daily 95th percentile, 7-day rolling mean, change against days t-60 to t-30.
- Per sensor group (temperature, electrical, power, pitch, speed, wind/yaw, vibration, pressure, other, all): mean, max and
  95th percentile across the group's columns, each with day value, 3/7/14-day rolling means, 7-day slope and change against
  t-60 to t-30.
- Context: daily wind, power and ambient.
- Sets: `full` A 347, B 609, C 2,055 features; `pooled` 129 (groups present in all three farms).

**Models.**

| name | what it is |
|---|---|
| CatBoost per farm | one model per farm, `full` features |
| CatBoost pooled | one model for all three farms, `pooled` features |
| season only | CatBoost on daily ambient, its 7-day mean, sin and cos of day of year |
| deviation rule | 3-day mean of the overall deviation index against a threshold, no learning |
| prevalence | the training-fold share of positive days |

- CatBoost parameters, fixed everywhere: depth 4, at most 400 trees, learning rate 0.05, L2 20, rsm 0.3, 64 borders.
- The number of trees is the median early-stopping point of 3 inner fits grouped by turbine.

**Cross-validation.**
- Grouped by turbine: A leave one turbine out (5 folds), B leave one turbine out (9 folds), C 5 folds dealt by event count.
- Pooled scheme: 5 folds over all 36 turbines.
- Seeds 0, 1, 2 (they re-deal the Farm C folds and set the CatBoost seed).
- Saved in `dataset/wind_turbine_scada_fault/cache/catboost_baseline/cv_folds.parquet`.

**Threshold, alarm, calibration.**
- The threshold comes from the training turbines' inner out-of-fold scores: the lowest one giving at most 1 false alarm per
  turbine-month.
- An alarm needs 2 of the last 3 days above the threshold, and a continuing alarm notifies again every 7 days.
- The risk percentage is an isotonic calibration fitted on the same inner out-of-fold scores.

**Metrics.**
- Day-level ROC-AUC: pooled over all out-of-fold days, and within turbine.
- Event recall: an alarm between 7 days before onset and the end of the window.
- Day recall, false alarms per turbine-month on the test turbines, PR-AUC, Brier.
- 95% intervals: cluster bootstrap over turbines, 1000 resamples.
- Point estimates: the three-seed ensemble (mean risk; an alarm needs a majority of seeds).

## 3. Headline: ROC-AUC and recall (k = 7, out-of-fold)

| farm | model | ROC-AUC pooled [95% CI] | ROC-AUC within turbine [95% CI] | event recall [95% CI] | day recall [95% CI] | day specificity | false alarms / turbine-month | events |
|---|---|---|---|---|---|---|---|---|
| A | deviation rule | 0.523 [0.441, 0.606] | 0.572 [0.475, 0.663] | 0.73 [0.55, 0.92] | 0.24 [0.16, 0.29] | 0.877 | 0.97 | 11 |
| A | season only | 0.645 [0.473, 0.883] | 0.673 [0.518, 0.876] | 0.91 [0.70, 1.00] | 0.74 [0.53, 1.00] | 0.277 | 3.21 | 11 |
| A | **CatBoost per farm** | **0.658 [0.604, 0.756]** | **0.695 [0.639, 0.767]** | **0.73 [0.60, 0.90]** | 0.47 [0.40, 0.54] | 0.846 | 0.91 | 11 |
| A | CatBoost pooled | 0.612 [0.546, 0.773] | 0.632 [0.564, 0.770] | 0.45 [0.36, 0.62] | 0.22 [0.15, 0.33] | 0.932 | 0.45 | 11 |
| B | deviation rule | 0.527 [0.452, 0.630] | 0.608 [0.469, 0.723] | 0.83 [0.50, 1.00] | 0.15 [0.04, 0.33] | 0.865 | 1.01 | 6 |
| B | season only | 0.287 [0.136, 0.387] | 0.385 [0.210, 0.500] | 0.50 [0.12, 1.00] | 0.18 [0.01, 0.49] | 0.497 | 2.26 | 6 |
| B | **CatBoost per farm** | **0.403 [0.307, 0.500]** | **0.550 [0.518, 0.599]** | **0.33 [0.00, 0.75]** | 0.04 [0.00, 0.12] | 0.784 | 1.23 | 6 |
| B | CatBoost pooled | 0.436 [0.337, 0.568] | 0.504 [0.350, 0.676] | 0.83 [0.50, 1.00] | 0.15 [0.05, 0.25] | 0.739 | 1.46 | 6 |
| C | deviation rule | 0.577 [0.481, 0.669] | 0.630 [0.534, 0.709] | 0.70 [0.54, 0.86] | 0.24 [0.14, 0.34] | 0.864 | 0.99 | 27 |
| C | season only | 0.447 [0.381, 0.520] | 0.496 [0.437, 0.553] | 0.96 [0.88, 1.00] | 0.79 [0.66, 0.92] | 0.303 | 3.20 | 27 |
| C | **CatBoost per farm** | **0.714 [0.584, 0.813]** | **0.728 [0.604, 0.820]** | **0.85 [0.71, 0.97]** | 0.55 [0.36, 0.71] | 0.821 | 1.06 | 27 |
| C | CatBoost pooled | 0.663 [0.557, 0.756] | 0.682 [0.573, 0.772] | 0.70 [0.52, 0.86] | 0.44 [0.27, 0.57] | 0.830 | 0.95 | 27 |

How to read it:
- **Recall only counts at the false-alarm budget.** The season-only model's high recall comes with 2.3 to 3.2 false alarms per
  turbine-month on the test turbines, above the budget of 1.
- **The pooled ROC-AUC is biased down** under leave-one-turbine-out: a turbine's own events are missing from its training
  folds. The prevalence constant alone scores 0.42 (A), 0.30 (B), 0.39 (C). The within-turbine ROC-AUC does not have this bias.
- **Event recall flatters on its own.** Normal datasets get an alarm in the same 3-week span about 55% of the time (section 4).

Spread across the three seeds, CatBoost per farm:

| farm | PR-AUC by seed | event recall by seed | false alarms by seed |
|---|---|---|---|
| A | 0.113 / 0.126 / 0.107 | 0.64 / 0.82 / 0.73 | 0.87 / 1.03 / 1.06 |
| B | 0.068 / 0.075 / 0.073 | 0.83 / 0.50 / 0.50 | 1.36 / 1.30 / 1.15 |
| C | 0.129 / 0.093 / 0.100 | 0.85 / 0.81 / 0.78 | 1.12 / 1.01 / 1.19 |

The ensemble's B recall (0.33) is lower than every single seed: the alarm needs a majority of seeds, and the seeds alarm on
different days.

## 4. Checks every new model must also pass

### 4.1 Against the season-only model (paired cluster bootstrap over turbines)

| farm | model | ROC-AUC | season-only ROC-AUC | difference [95% CI] | beats season? |
|---|---|---|---|---|---|
| A | deviation rule | 0.523 | 0.645 | -0.122 [-0.375, +0.114] | not shown |
| A | CatBoost per farm | 0.658 | 0.645 | +0.014 [-0.141, +0.166] | **not shown** |
| A | CatBoost pooled | 0.612 | 0.645 | -0.032 [-0.224, +0.085] | not shown |
| B | deviation rule | 0.527 | 0.287 | +0.240 [+0.124, +0.450] | yes |
| B | CatBoost per farm | 0.403 | 0.287 | +0.116 [+0.046, +0.254] | yes (but both below 0.5) |
| B | CatBoost pooled | 0.436 | 0.287 | +0.149 [+0.019, +0.338] | yes (but both below 0.5) |
| C | deviation rule | 0.577 | 0.447 | +0.130 [+0.032, +0.226] | yes |
| C | CatBoost per farm | 0.714 | 0.447 | +0.267 [+0.132, +0.384] | **yes** |
| C | CatBoost pooled | 0.663 | 0.447 | +0.216 [+0.100, +0.324] | yes |

### 4.2 Same position: anomaly against normal datasets

Positive days sit at the end of anomaly datasets, and every dataset has the same shape, so a model could score by recognising
*where in a dataset* a day is. Fair test: the days from 7 before to 14 after each dataset's own window start, anomaly datasets
against normal ones.
- Dataset AUC = the AUC of each dataset's maximum score in that span.
- p = one-sided permutation p-value, 5000 shuffles.
- The last row of each farm is a deliberate leak, the day's position in its timeline only. It reaches PR-AUC 0.29 / 0.48 /
  0.44 over all days, which shows how much the dataset geometry alone gives.

| farm | model | dataset AUC | p | day AUC | alarm in anomaly datasets | alarm in normal datasets | n anomaly / normal |
|---|---|---|---|---|---|---|---|
| A | deviation rule | 0.645 | 0.134 | 0.626 | 0.82 | 0.45 | 11 / 11 |
| A | season only | 0.694 | 0.066 | 0.679 | 0.91 | 0.73 | 11 / 11 |
| A | **CatBoost per farm** | **0.645** | 0.126 | 0.633 | 0.73 | 0.55 | 11 / 11 |
| A | CatBoost pooled | 0.645 | 0.129 | 0.643 | 0.45 | 0.18 | 11 / 11 |
| A | timeline position (leak) | 0.483 | 0.560 | 0.551 | 1.00 | 1.00 | 11 / 11 |
| B | deviation rule | 0.481 | 0.564 | 0.511 | 0.50 | 0.67 | 6 / 9 |
| B | season only | 0.241 | 0.953 | 0.289 | 0.33 | 0.67 | 6 / 9 |
| B | **CatBoost per farm** | **0.241** | 0.957 | 0.366 | 0.17 | 0.56 | 6 / 9 |
| B | CatBoost pooled | 0.185 | 0.981 | 0.234 | 0.33 | 0.89 | 6 / 9 |
| B | timeline position (leak) | 0.778 | 0.046 | 0.719 | 1.00 | 1.00 | 6 / 9 |
| C | deviation rule | 0.682 | 0.010 | 0.682 | 0.78 | 0.52 | 27 / 31 |
| C | season only | 0.489 | 0.537 | 0.538 | 0.96 | 0.77 | 27 / 31 |
| C | **CatBoost per farm** | **0.689** | **0.008** | 0.643 | 0.85 | 0.55 | 27 / 31 |
| C | CatBoost pooled | 0.593 | 0.113 | 0.594 | 0.74 | 0.61 | 27 / 31 |
| C | timeline position (leak) | 0.548 | 0.265 | 0.582 | 1.00 | 1.00 | 27 / 31 |

### 4.3 Strict target at the same position (early warning)

The 7 days before each dataset's own window start, anomaly against normal datasets, using the k = 7 strict models (seed 0).

| farm | model | dataset AUC (max score) | p | dataset AUC (mean score) |
|---|---|---|---|---|
| A | CatBoost per farm | 0.736 | 0.030 | 0.727 |
| A | CatBoost pooled | 0.686 | 0.071 | 0.719 |
| A | season only | 0.678 | 0.081 | 0.669 |
| B | CatBoost per farm | 0.796 | 0.032 | 0.796 |
| B | CatBoost pooled | 0.463 | 0.627 | 0.370 |
| B | season only | 0.407 | 0.735 | 0.389 |
| C | CatBoost per farm | 0.615 | 0.064 | 0.639 |
| C | CatBoost pooled | 0.638 | 0.039 | 0.634 |
| C | season only | 0.509 | 0.445 | 0.515 |

These are 9 uncorrected tests, and none survives a Bonferroni correction. In A the season-only model gets 0.68 on the same
test, and B's 0.80 contradicts every other B result. Read it as a hint to re-test, not as evidence of a precursor.

### 4.4 Ablations (CatBoost per farm, k = 7)

| farm | features | n | ROC-AUC [95% CI] | event recall [95% CI] | false alarms / turbine-month | same-position dataset AUC |
|---|---|---|---|---|---|---|
| A | full | 347 | 0.658 [0.604, 0.756] | 0.73 [0.60, 0.90] | 0.91 | 0.645 |
| A | no ambient | 346 | 0.681 [0.621, 0.773] | 0.73 [0.61, 0.90] | 0.94 | 0.653 |
| A | no ambient, no temperature | 232 | 0.688 [0.634, 0.786] | 0.73 [0.61, 0.90] | 0.93 | 0.636 |
| B | full | 609 | 0.403 [0.307, 0.500] | 0.33 [0.00, 0.75] | 1.23 | 0.241 |
| B | no ambient | 608 | 0.402 [0.312, 0.486] | 0.33 [0.00, 0.72] | 1.22 | 0.185 |
| B | no ambient, no temperature | 394 | 0.384 [0.320, 0.451] | 0.17 [0.00, 0.50] | 1.22 | 0.148 |
| C | full | 2055 | 0.714 [0.584, 0.813] | 0.85 [0.71, 0.97] | 1.06 | 0.689 |
| C | no ambient | 2054 | 0.737 [0.589, 0.829] | 0.74 [0.50, 0.91] | 1.13 | 0.687 |
| C | no ambient, no temperature | 1424 | 0.733 [0.570, 0.846] | 0.70 [0.48, 0.88] | 1.06 | 0.691 |

The residual models still use ambient as a covariate in every row of this table.

### 4.5 Horizons (day-level ROC-AUC, seed 0)

| farm | target | model | k=1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|---|
| A | main | CatBoost per farm | 0.618 | 0.645 | 0.639 | 0.667 | 0.661 | 0.666 | 0.654 |
| A | main | CatBoost pooled | 0.637 | 0.661 | 0.696 | 0.655 | 0.674 | 0.678 | 0.692 |
| A | main | season only | 0.588 | 0.609 | 0.624 | 0.629 | 0.675 | 0.675 | 0.659 |
| A | strict | CatBoost per farm | 0.713 | 0.736 | 0.739 | 0.781 | 0.787 | 0.764 | 0.735 |
| A | strict | season only | 0.561 | 0.586 | 0.615 | 0.554 | 0.623 | 0.649 | 0.656 |
| B | main | CatBoost per farm | 0.453 | 0.465 | 0.508 | 0.481 | 0.460 | 0.498 | 0.530 |
| B | main | CatBoost pooled | 0.585 | 0.558 | 0.537 | 0.522 | 0.508 | 0.523 | 0.513 |
| B | main | season only | 0.342 | 0.414 | 0.358 | 0.392 | 0.358 | 0.331 | 0.421 |
| B | strict | CatBoost per farm | 0.340 | 0.502 | 0.648 | 0.595 | 0.654 | 0.654 | 0.620 |
| C | main | CatBoost per farm | 0.685 | 0.708 | 0.695 | 0.708 | 0.713 | 0.736 | 0.738 |
| C | main | CatBoost pooled | 0.642 | 0.643 | 0.649 | 0.663 | 0.661 | 0.655 | 0.658 |
| C | main | season only | 0.463 | 0.470 | 0.468 | 0.520 | 0.507 | 0.535 | 0.542 |
| C | strict | CatBoost per farm | 0.592 | 0.630 | 0.678 | 0.671 | 0.684 | 0.652 | 0.687 |
| C | strict | season only | 0.542 | 0.553 | 0.551 | 0.579 | 0.570 | 0.551 | 0.561 |

The strict ROC-AUC compares the days before onset with every other negative day of the year, so it is not position-matched.
Use section 4.3 for that.

## 5. Calibration, importance, deliverables

**Calibration (CatBoost per farm, isotonic on grouped inner CV).**

| farm | Brier calibrated | Brier of a constant | ECE (10 bins) | max risk | days with risk > 20% |
|---|---|---|---|---|---|
| A | 0.0431 | 0.0448 | 0.017 | 43% | 2.1% |
| B | 0.0816 | 0.0807 | 0.072 | 12% | 0% |
| C | 0.0475 | 0.0481 | 0.013 | 91% | 1.2% |

**Importance and correlation.**
- Top features by mean |SHAP| (`importance_<farm>.csv`):
  - A: a speed-group feature and ambient temperature first, then changes in hydraulic oil and transformer temperature;
  - B and C: mostly per-column changes against days t-60 to t-30, such as transformer temperatures in B, and a 24 V power pack
    and pressures in C.
- The pooled model leans on the power, all-sensor and speed group features.
- Season-aware correlation, counting features with |Spearman| >= 0.10 before and after removing season (ambient, day of
  year): A 13 before, 1 after; B 69 before, 61 after; C 86 before, 79 after. The Farm A association with the label is
  almost all season.

**Files** in `dataset/wind_turbine_scada_fault/cache/`:
- `catboost_test_week.parquet`: one week per farm with the daily risk `risk_k1` to `risk_k7` (calibrated %, monotone in k),
  `above_threshold`, `alarm` (2 of 3 days), `deviation_pct` (descriptive percentile against the turbine's own past negative
  days, not a health %), and the truth.
- `catboost_baseline/oof_daily_risk.parquet`: the same columns for every day of every timeline.
- `catboost_baseline/cv_folds.parquet`: the folds; reuse them.
- `catboost_baseline/results_*.csv`, `importance_*.csv`, `season_aware_correlation_*.csv`, `events_detection.csv` and the
  PNG figures.

## 6. What does not work

- **Farm A is not shown to beat season**, and at the same position the season-only model matches it (0.69 against 0.65).
- **Farm B does not work**: 6 events, CatBoost below 0.5, the plain deviation rule is the best model.
- **The pooled model** (44 events, group features only) is worse than the per-farm models.
- **No convincing early warning** (section 4.3). Alarms "before onset" are mostly the base alarm rate.
- **The risk percentage is weak**: Brier is barely below a constant, and above it in B.
- **The threshold transfers badly for slowly varying scores**: the season-only model meets the budget on training turbines
  and breaks it on test turbines.
- **The test week shows misses.** The weeks were chosen by turbine coverage, not by outcome. In A and B the turbine with the
  onset has the lowest (B: tied lowest) risk of its farm; in C three turbines alarm while the one with the converter failure
  does not.
- **No health percentage is possible**: no degradation ground truth and no precursor to interpolate.

## 7. Where the original specification did not hold on the data

1. **Overlaps.** 12 of the 22 overlapping same-turbine dataset pairs carry different data on the same anonymised timestamps.
   Only identical overlaps are merged, so there are 17 / 14 / 54 timelines (A / B / C).
   - Anomaly onsets truly inside another dataset's train part: 2 / 1 / 2, not 8 / 1 / 11.
2. **Baseline window.** The trailing baseline t-365 to t-60 grows with the position in the dataset, and the deviation index
   falls as it grows: baseline under 120 days against over 300 days, Farm B 1.30 against 1.06, Farm C 1.38 against 1.17.
   That leaked the position (the deviation rule fell below 0.5 ROC-AUC). Replaced by the fixed window [t-180, t-60).
3. **Farm A `sensor_44` to `sensor_51`** are energies per 10-minute interval, not cumulative counters. They stay excluded,
   because they split energy by generator state.
4. **Day of year** is a valid season feature: ambient temperature peaks around day 208 to 223 in every dataset.

## 8. How to compare a new model against this baseline

Use the same `cv_folds.parquet`, the same labels (section 4 of the notebook, or join on `segment` and `day`), k = 7 as the
headline, and the same false-alarm budget. A new model counts as better only if all of these hold:

1. **Higher ROC-AUC (pooled and within turbine) and event recall** than CatBoost per farm, per farm, with event recall read
   at at most 1 false alarm per turbine-month on the **test** turbines. Bars to clear:
   - A: 0.658 / 0.695 / 0.73;
   - B: 0.403 / 0.550 / 0.33;
   - C: 0.714 / 0.728 / 0.85.
2. **It beats the season-only model**, with a paired-bootstrap interval of the ROC-AUC difference above zero.
3. **It beats this baseline at the same position** (section 4.2; Farm C dataset AUC 0.689). For an early-warning claim it
   must also clear section 4.3 with a correction for the number of tests.
4. **It stays ahead without ambient and temperatures**, so it is not reading the calendar.
