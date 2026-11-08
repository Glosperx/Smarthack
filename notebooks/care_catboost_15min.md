# CARE ML1: CatBoost on the 15-minute grid and NVIDIA Kumo Tabular

**Status: compared against the baseline, no improvement.** The daily CatBoost baseline (`notebooks/care_catboost_baseline.md`,
branch `feature/catboost_failure-baseline`) stays the reference for ML1. Source: `notebooks/care_catboost_15min.ipynb`
(reads cached results, trains nothing) and `fault_detection/care_catboost_15min.py`, `care_kumo_tabular.py`,
`build_kumo_kernel.py`. Run on 2026-11-08 in conda env `ml_def` (catboost 1.2.10) and on a Kaggle 2x Tesla T4 kernel
(`structured-data-models` 0.2.1, torch 2.11). Every number below was measured in those runs unless it says "estimated".

## 1. Setup

- **Question**: will the turbine be inside, or enter, an anomaly window within 7 days? Same labels, folds
  (`cv_folds.parquet`, scheme `per_farm`), threshold rule (at most 1 false alarm per turbine-month on the training
  turbines' inner out-of-fold scores), isotonic calibration, metrics and checks as the baseline.
- **Inputs**: `care_fault_forecast.py prepare` (15-minute time-weighted means of the `_avg` columns, sin/cos for angles,
  differences for counters, a missing flag, z-scored on each dataset's train part). `status_type_id` is never read.
- **Anchors**: `make_anchors` unchanged (48 h lookback, stride 1 with an onset within 7 days, stride 4 otherwise, anchors
  from the onset on dropped, windows over 50% missing dropped). Scoring also covers the stride-4 anchors after an onset,
  so every baseline day gets a score.
- **Features** per channel over 48 h: last, mean, std, min, max, slope, last 6 h minus the 42 h before. A 352, B 464,
  C 1,752.
- **Target**: censored, onset within k days (k = 7 headline; k = 1..6 for the timing).
- **Daily score**: maximum of the day's stride-4 anchor scores (stride-1 positives would inflate the maximum).
- **Fixes found on the way**:
  - `care_fault_forecast.dataset_path` read the `;` CSVs with the comma event table; it now prefers the comma CSV.
  - 5 timelines (A 2, B 1, C 2) hold another dataset's onset inside a dataset's train part on identical rows, so
    `make_anchors` labelled the same window "fails" in one dataset and "does not fail" in the other. `segment_targets`
    makes the target use every onset of the timeline.
- **Folds**: the LSTM's `fold_split` (5 folds over all farms, seed 42) is a different partition from `cv_folds.parquet`,
  and the cached LSTM results already used `cv_folds.parquet`; the owner chose `cv_folds.parquet` for every model.

## 2. Headline (k = 7, out of fold, main target)

95% intervals: cluster bootstrap over turbines, 1000 resamples. Event recall at the threshold from the training
turbines; false alarms are what it produced on the test turbines.

| farm | model | ROC-AUC pooled [95% CI] | within turbine | event recall | false alarms / turbine-month |
|---|---|---|---|---|---|
| A | season only | 0.645 [0.473, 0.883] | 0.673 | 0.91 | 3.21 |
| A | CatBoost daily (baseline) | 0.658 [0.604, 0.756] | 0.695 | 0.73 | 0.91 |
| A | LSTM-attention (all channels) | 0.596 [0.509, 0.771] | 0.616 | 0.64 | 0.75 |
| A | CatBoost 15 min (3 seeds) | 0.680 [0.541, 0.895] | 0.715 | 0.91 | 1.46 |
| A | CatBoost 15 min, shortlist (3 seeds) | 0.594 [0.551, 0.687] | 0.645 | 0.82 | 1.06 |
| A | Kumo Tabular, shortlist (seed 0 folds) | 0.574 [0.524, 0.686] | 0.630 | 0.55 | 0.64 |
| B | season only | 0.287 [0.136, 0.387] | 0.385 | 0.50 | 2.26 |
| B | CatBoost daily (baseline) | 0.403 [0.307, 0.500] | 0.550 | 0.33 | 1.23 |
| B | LSTM-attention (all channels) | 0.467 [0.343, 0.604] | 0.450 | 0.50 | 0.37 |
| B | CatBoost 15 min | 0.478 [0.401, 0.593] | 0.559 | 1.00 | 1.91 |
| B | CatBoost 15 min, shortlist | 0.321 [0.215, 0.422] | 0.507 | 0.50 | 1.11 |
| B | Kumo Tabular, shortlist | 0.455 [0.312, 0.583] | 0.575 | 0.50 | 0.69 |
| C | season only | 0.447 [0.381, 0.520] | 0.496 | 0.96 | 3.20 |
| C | CatBoost daily (baseline) | **0.714 [0.584, 0.813]** | **0.728** | **0.85** | 1.06 |
| C | LSTM-attention (all channels) | 0.596 [0.474, 0.715] | 0.591 | 0.41 | 0.69 |
| C | CatBoost 15 min | 0.636 [0.512, 0.737] | 0.648 | 0.56 | 1.07 |
| C | CatBoost 15 min, shortlist | 0.626 [0.484, 0.747] | 0.642 | 0.67 | 1.00 |
| C | Kumo Tabular, shortlist | 0.571 [0.479, 0.679] | 0.604 | 0.33 | 0.48 |

The strict target (days before onset only) and the LSTM q672 runs are in `results_headline.csv`.

## 3. Checks (paired cluster bootstrap; same position)

| farm | model | vs season only | vs CatBoost daily | same-position dataset AUC (p) |
|---|---|---|---|---|
| A | CatBoost 15 min | +0.035 [-0.024, +0.118] | +0.022 [-0.095, +0.149] | 0.678 (0.081) |
| A | Kumo Tabular | -0.071 [-0.237, +0.054] | -0.084 [-0.129, +0.040] | 0.653 (0.120) |
| B | CatBoost 15 min | +0.191 [+0.091, +0.362] | +0.075 [-0.030, +0.219] | 0.278 (0.924) |
| B | Kumo Tabular | +0.168 [+0.061, +0.352] | +0.052 [-0.027, +0.131] | 0.389 (0.768) |
| C | CatBoost 15 min | +0.189 [+0.032, +0.330] | -0.078 [-0.238, +0.080] | **0.480 (0.603)** |
| C | Kumo Tabular | +0.124 [+0.004, +0.253] | **-0.143 [-0.273, -0.011]** | 0.524 (0.372) |
| C | CatBoost daily (baseline) | +0.267 [+0.132, +0.384] | | 0.689 (0.008) |

Strict target, C: CatBoost 15 min -0.165 [-0.304, -0.048], Kumo -0.150 [-0.266, -0.034] against the baseline.

## 4. Feature selection (SHAP)

Mean |SHAP| on 3,000 test anchors per fold (seed 0); stable = top 150 in at least 80% of folds. Filters: position (normal
datasets, 14 days around the train end against days 300 to 60 before it, |AUC - 0.5| >= 0.15), season (two-harmonic
day-of-year removal explains over half the signal), class overlap >= 0.98, `status_type_id` asserted absent.

| farm | stable | removed: position | removed: season | shortlist |
|---|---|---|---|---|
| A | 124 | 1 | 27 | 96 |
| B | 119 | 19 | 16 | 89 |
| C | 70 | 0 | 0 | 70 |

The shortlist is chosen once per farm from all folds, and two filters use labels, so the shortlist rows are slightly
optimistic; they are still below the full CatBoost 15 min in A and B.

## 5. Kumo Tabular

- **Limits checked first** (docs.nvidia.com/sdgm, Hugging Face model card and blog, the API reference): no hard inference
  limit is documented; training tables had up to 60,000 rows and 100 columns and accuracy may degrade far outside them;
  default recipe `SelectColumns(max_columns=500)`; at most 10 classes per pass; numerical inputs only.
- **Run**: private Kaggle kernel `teodorapanait/care-kumo-tabular-15min`, 2x T4 (C on one GPU, A then B on the other),
  rebuilding the arrays and features from the public CARE dataset with the same code (same anchor counts as locally).
  Large model, context 10,240 rows (positives up to 25%), 3 inner fits plus the final fit per fold, seed 0 folds.
- **Speed**: smoke test with 4 estimators 192 rows/s; full run with 1 estimator 803 to 852 rows/s; about 60 minutes for
  4.9 million queries plus permutation importance (1,000 anchors per fold, 6 of B's 9 test folds hold a positive).
- **API notes**: `TableTensor.from_pandas(df=, stypes=sdm.infer_stypes(df, overrides=...))` (force features to
  `numerical`); output is a `TableTensor` with one probability column per class; `fit` and `predict` must run under the
  same autocast dtype; query batches of 4,096 fit a T4 with a 10,240-row context (20,000 ran out of memory).

## 6. Timing error (k = 1..7 models, seed 0)

| farm | anchors (events) | median abs error (h) | uniform curve (h) | right day | 80% interval coverage / width (h) |
|---|---|---|---|---|---|
| A | 1,440 (10) | 32.8 | 36.0 | 0.21 | 0.77 / 106 |
| B | 144 (1) | 41.1 | 36.0 | 0.21 | 0.75 / 113 |
| C | 2,160 (15) | 35.3 | 36.0 | 0.17 | 0.75 / 116 |

No timing skill beyond a uniform guess over the week (the LSTM session found the same). Farm B and about half of C log
onsets at 00:00, so finer timing cannot be validated.

## 7. Run time (measured)

- `prepare` 29 s locally (113 to 119 s on Kaggle), `features` about 30 s.
- CatBoost, one fold at k = 7: A 6 s, C 90 s (8 GB resident); trees stop at 30 to 45. k = 7 with 3 seeds about 25 minutes,
  k = 1..6 with seed 0 about an hour. The pre-run guess of 15 to 25 hours was not needed.

## 8. Files

Versioned copy of the results in `notebooks/results/care_catboost_15min/`: `results_headline.csv` and `results_checks.csv`
(every model, main and strict target, including Kumo), `results_timing.csv`, `kumo_timing.csv` (every Kumo fit: context,
queries, seconds), `kumo_permutation_importance.csv`, `feature_screen_<farm>.csv` (SHAP, filters, shortlist flag per
feature), `shortlist.json`. The full outputs (feature matrices, anchor scores, runs, Kumo scores from Kaggle) stay in the
local cache `dataset/wind_turbine_scada_fault/cache/catboost_15min/` (not in git; `kumo_full/kumo/` holds the Kaggle output).

## 9. Conclusion

No 15-minute model beats the daily baseline in any farm; Kumo Tabular is worse in C with an interval below zero. A 48 h
window without a long reference sees operating point and weather, not degradation; the baseline's residual against a
fixed 120-day window is what carries its C result. Keep the daily CatBoost baseline for ML1.
