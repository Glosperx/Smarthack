# CARE: a small GRU on daily deviation sequences, blends with CatBoost, and score centring

Source: `notebooks/care_gru.ipynb`, run from scratch on 2026-11-08 in the conda env `ml_def` (torch 2.13, CPU) with
nbconvert, 0 errors. The network code is in `fault_detection/care_gru.py`. Outputs and caches are in
`dataset/wind_turbine_scada_fault/cache/gru/`. Sections 1 to 7 of the notebook are the baseline's, copied unchanged: same
labels (k = 7), folds, fold seeds, threshold rule, isotonic calibration and bootstrap as `notebooks/care_catboost_baseline.md`.

**Verdict.**
- **Farm A:** the GRU on groups + PCA is the first model that beats the CatBoost baseline significantly. Pooled ROC-AUC is
  0.756 against 0.658, +0.098 [+0.030, +0.218]. It also holds without temperatures.
- **Farm C:** CatBoost stays best.
- **Farm B:** no model works.
- **Best mean over the three farms:** the 50/50 blend CatBoost + GRU (groups + PCA), pooled ROC-AUC 0.610 against 0.592
  for CatBoost.
- **Centring the scores** on each turbine's own past does not help on average, so it is not used.

## 1. Setup

- **Input**, one vector per day over a window of the last 30 days, built from the baseline's daily deviation |rz| (each
  sensor against its own operating-point model on the trailing baseline [t-180, t-60)). Ambient temperature never enters.
  - **`GRU, SHAP top 20`**: the 20 sources (sensor columns or sensor groups) with the largest CatBoost |SHAP|, summed over a
    source's derived features. The ranking is recomputed inside every fit, from the CatBoost trained on that fit's training
    turbines only. A column enters as daily `__m` and `__q`, a group as daily mean, max and 95th percentile. Plus `ctx_ws`
    and `ctx_p`. That gives A 49-50, B 45-50 and C 43-47 inputs per day.
  - **`GRU, groups + PCA 16`**: every group's daily mean, max and 95th percentile (A 24, B 27, C 30), 16 principal
    components of the daily |rz| of every column (fitted on the negative days of the fit's training turbines), and
    `ctx_ws`, `ctx_p`. That gives A 42, B 45 and C 48 inputs per day.
- **Network**, fixed in advance and not tuned on the results:
  - one-layer GRU, hidden 16, dropout 0.4;
  - AdamW, lr 1e-3, weight decay 1e-2, batch 128, input noise 0.1;
  - 15 epochs of next-day self-supervised pretraining on negative days;
  - fine-tuning with event-balanced weights plus 0.1 x the next-day loss, at most 30 epochs, early stopping on the inner
    held-out turbines;
  - two networks per fit, three fold seeds.
- **Blends**: 50/50 on standardised logits, each model standardised on its own inner out-of-fold scores.
- **CatBoost** is refitted with the baseline seeds and parameters, to get its inner out-of-fold scores and inner models. Its
  test scores equal the baseline run.

## 2. Headline (k = 7, out-of-fold, three-seed ensemble)

| farm | model | ROC-AUC pooled [95% CI] | ROC-AUC within turbine [95% CI] | event recall [95% CI] | false alarms / turbine-month |
|---|---|---|---|---|---|
| A | season only | 0.645 [0.473, 0.883] | 0.673 [0.518, 0.876] | 0.91 [0.70, 1.00] | 3.21 |
| A | CatBoost per farm (baseline) | 0.658 [0.604, 0.756] | 0.695 [0.639, 0.767] | 0.73 [0.60, 0.90] | 0.91 |
| A | GRU, SHAP top 20 | 0.716 [0.649, 0.802] | 0.710 [0.652, 0.784] | 0.64 [0.38, 0.82] | 0.87 |
| A | **GRU, groups + PCA 16** | **0.756 [0.677, 0.876]** | **0.787 [0.719, 0.882]** | **0.82 [0.69, 1.00]** | **0.72** |
| A | CatBoost + GRU (SHAP top 20) 50/50 | 0.696 [0.635, 0.787] | 0.709 [0.647, 0.786] | 0.73 [0.60, 0.90] | 0.95 |
| A | CatBoost + GRU (groups + PCA 16) 50/50 | 0.735 [0.660, 0.833] | 0.763 [0.684, 0.854] | 0.82 [0.69, 1.00] | 0.90 |
| B | season only | 0.287 [0.136, 0.387] | 0.385 [0.210, 0.500] | 0.50 [0.12, 1.00] | 2.26 |
| B | CatBoost per farm (baseline) | 0.403 [0.307, 0.500] | 0.550 [0.518, 0.599] | 0.33 [0.00, 0.75] | 1.23 |
| B | GRU, SHAP top 20 | 0.285 [0.202, 0.380] | 0.328 [0.256, 0.429] | 0.17 [0.00, 0.50] | 0.58 |
| B | GRU, groups + PCA 16 | 0.351 [0.292, 0.436] | 0.412 [0.340, 0.530] | 0.00 [0.00, 0.00] | 0.87 |
| B | CatBoost + GRU (SHAP top 20) 50/50 | 0.387 [0.320, 0.487] | 0.554 [0.532, 0.573] | 0.33 [0.00, 0.75] | 1.02 |
| B | CatBoost + GRU (groups + PCA 16) 50/50 | 0.405 [0.347, 0.495] | 0.529 [0.487, 0.598] | 0.17 [0.00, 0.50] | 1.01 |
| C | season only | 0.447 [0.381, 0.520] | 0.496 [0.437, 0.553] | 0.96 [0.88, 1.00] | 3.20 |
| C | **CatBoost per farm (baseline)** | **0.714 [0.584, 0.813]** | 0.728 [0.604, 0.820] | **0.85 [0.71, 0.97]** | 1.06 |
| C | GRU, SHAP top 20 | 0.686 [0.617, 0.762] | 0.724 [0.627, 0.813] | 0.56 [0.32, 0.78] | 0.89 |
| C | GRU, groups + PCA 16 | 0.618 [0.529, 0.708] | 0.660 [0.568, 0.743] | 0.44 [0.25, 0.67] | 0.72 |
| C | CatBoost + GRU (SHAP top 20) 50/50 | 0.724 [0.606, 0.823] | 0.745 [0.624, 0.844] | 0.70 [0.50, 0.88] | 0.91 |
| C | CatBoost + GRU (groups + PCA 16) 50/50 | 0.690 [0.561, 0.792] | 0.719 [0.592, 0.817] | 0.67 [0.52, 0.83] | 0.75 |

**Paired difference against CatBoost**, pooled ROC-AUC with its 95% interval. Significant results are in bold.

| farm | GRU SHAP 20 | GRU groups + PCA | blend CB + SHAP 20 | blend CB + PCA |
|---|---|---|---|---|
| A | **+0.057 [+0.015, +0.070]** | **+0.098 [+0.030, +0.218]** | **+0.038 [+0.016, +0.044]** | **+0.077 [+0.026, +0.166]** |
| B | -0.119 [-0.216, -0.023] (worse) | -0.052 [-0.133, +0.085] | -0.016 [-0.049, +0.027] | +0.002 [-0.043, +0.062] |
| C | -0.029 [-0.115, +0.062] | -0.096 [-0.181, -0.004] (worse) | +0.009 [-0.036, +0.055] | -0.024 [-0.070, +0.017] |

In Farm A, GRU groups + PCA is also significantly better within turbine: +0.093 [+0.037, +0.195].

**Same position** (anomaly against normal datasets, days -7 to +14 around each dataset's own window start, dataset AUC of the
maximum score):
- A: CatBoost 0.645 (p 0.13); **GRU groups + PCA 0.785 (p 0.011)**; GRU SHAP 20 0.785 (p 0.010).
- B: every model below 0.4.
- C: CatBoost 0.689 (p 0.008); blend CB + SHAP 20 0.695 (p 0.005); GRU groups + PCA 0.481.

## 3. Farm A without temperatures (baseline rule 4)

| model | ROC-AUC pooled [95% CI] | within turbine | event recall | false alarms |
|---|---|---|---|---|
| CatBoost, all features | 0.658 [0.604, 0.756] | 0.695 | 0.73 | 0.91 |
| CatBoost, no ambient, no temperature | 0.688 [0.637, 0.786] | 0.728 | 0.73 | 0.93 |
| GRU groups + PCA, all features | 0.756 [0.677, 0.876] | 0.787 | 0.82 | 0.72 |
| GRU groups + PCA, no temperature | 0.716 [0.658, 0.809] | 0.745 | 0.73 | 0.85 |

- Without temperatures the GRU stays above CatBoost with all features, +0.057 [+0.021, +0.121], so rule 4 holds. Its
  same-position dataset AUC is 0.736.
- Against CatBoost also without temperatures, the gap shrinks to +0.027 [-0.015, +0.088], which is not significant.
- So about half of the Farm A gain is tied to temperature, which in Farm A goes with season.

## 4. Verdict against the baseline rules (section 8 of the baseline .md)

GRU groups + PCA in Farm A:
- **Rule 1 holds:** pooled ROC-AUC, within-turbine ROC-AUC and event recall are all above CatBoost, at 0.72 false alarms
  per turbine-month.
- **Rule 3 holds:** same-position dataset AUC 0.785 against 0.645.
- **Rule 4 holds:** without temperatures it is still above CatBoost.
- **Rule 2 is not shown:** against season only, +0.111 [-0.053, +0.223]. In Farm A no model clears this rule, the baseline
  included, because the season-only model has a very wide interval there.

No model passes rules 1 to 3 in B or C.

Caveats:
- Farm A has 5 turbines, so a cluster bootstrap over 5 clusters gives intervals that are too narrow.
- Two input variants were tried, and the better one is reported, a small multiple-comparison effect.

## 5. Overfitting

- Training ROC-AUC reaches 0.99 to 1.0 in every farm.
- **Farm A:** the inner validation ROC-AUC rises steadily (groups + PCA: 0.62 at epoch 1, 0.80 at epoch 12, 0.81 at
  epoch 30). The median number of epochs used is 7.
- **Farms B and C:** validation peaks at epoch 1 to 3. For C groups + PCA it falls from 0.66 to 0.49 by epoch 20, so early
  stopping keeps 2 epochs and the network is essentially the pretrained encoder.
- The earlier LSTM (hidden 128, raw 15-minute channels) was worse on every count. The smaller network on deviation inputs
  removes part of the overfitting, not all of it.

## 6. Correlation with CatBoost

| farm | GRU | Spearman, all days | positive days | events: both / CatBoost only / GRU only / neither |
|---|---|---|---|---|
| A | SHAP top 20 | 0.59 | 0.76 | 7 / 1 / 0 / 3 |
| A | groups + PCA | 0.48 | 0.58 | 8 / 0 / 1 / 2 |
| B | SHAP top 20 | 0.42 | 0.33 | 0 / 2 / 1 / 3 |
| B | groups + PCA | 0.53 | 0.21 | 0 / 2 / 0 / 4 |
| C | SHAP top 20 | 0.41 | 0.40 | 14 / 9 / 1 / 3 |
| C | groups + PCA | 0.33 | 0.46 | 12 / 11 / 0 / 4 |

Weight curve: pooled ROC-AUC by CatBoost share w, seed-mean raw scores. It is descriptive only: its maximum is tuned on the
test turbines.

| farm, GRU | best w | ROC-AUC at best | GRU alone | CatBoost alone |
|---|---|---|---|---|
| A, groups + PCA | 0 (GRU alone) | 0.776 | 0.776 | 0.685 |
| C, SHAP top 20 | 0.7 | 0.764 | 0.707 | 0.749 |
| C, groups + PCA | 0.9 | 0.748 | 0.620 | 0.749 |

## 7. Centring the scores on each turbine's own past

From each day's score (logit) the median score of the same timeline over days [t-120, t-60) is subtracted. Thresholds and
calibration are refitted on the inner scores centred the same way. The window was set before seeing any result.

| farm | model | pooled, raw | pooled, centred | centred minus raw [95% CI] |
|---|---|---|---|---|
| A | CatBoost | 0.658 | 0.598 | -0.060 [-0.137, -0.033] |
| A | GRU groups + PCA | 0.756 | 0.789 | +0.033 [-0.083, +0.096] |
| B | CatBoost | 0.403 | 0.291 | -0.112 [-0.219, -0.011] |
| B | GRU SHAP top 20 | 0.285 | 0.393 | +0.109 [-0.004, +0.240] |
| B | GRU groups + PCA | 0.351 | 0.453 | +0.102 [-0.052, +0.237] |
| C | CatBoost | 0.714 | 0.504 | -0.211 [-0.289, -0.144] |
| C | blend CB + SHAP 20 | 0.724 | 0.572 | -0.152 [-0.204, -0.098] |

- Centring hurts CatBoost and both blends in every farm, and the within-turbine ROC-AUC drops as well (CatBoost C 0.728 to
  0.533).
- The level of a turbine's score over months is itself signal: faults last weeks (median event 8 / 37.5 / 15 days), and
  CatBoost's month-over-month change features already compare against the past, so subtracting the past a second time
  removes signal.
- Centring only helps the GRU in A and B, and not significantly.

## 8. Mean over the three farms

Simple mean of the farm values. Farm B, with every model below 0.5, pulls every mean down.

| model | pooled A / B / C | **mean pooled ROC-AUC** | mean within-turbine | mean event recall | mean false alarms |
|---|---|---|---|---|---|
| **CatBoost + GRU (groups + PCA 16) 50/50** | 0.735 / 0.405 / 0.690 | **0.610** | **0.670** | 0.55 | 0.88 |
| GRU groups + PCA 16, centred | 0.789 / 0.453 / 0.569 | 0.604 | 0.653 | 0.60 | 1.01 |
| CatBoost + GRU (SHAP top 20) 50/50 | 0.696 / 0.387 / 0.724 | 0.602 | 0.669 | 0.59 | 0.96 |
| CatBoost per farm (baseline) | 0.658 / 0.403 / 0.714 | 0.592 | 0.658 | 0.64 | 1.07 |
| GRU groups + PCA 16 | 0.756 / 0.351 / 0.618 | 0.575 | 0.620 | 0.42 | 0.77 |
| GRU SHAP top 20 | 0.716 / 0.285 / 0.686 | 0.562 | 0.587 | 0.45 | 0.78 |
| CatBoost, centred | 0.598 / 0.291 / 0.504 | 0.464 | 0.523 | 0.40 | 0.99 |

The ridge notebook (`notebooks/care_catboost_ridge.md`) gives a mean of 0.592 for its 50/50 blend, a tie with CatBoost.

## 9. Recall against the false-alarm budget (section 15 of the notebook)

The ROC-AUC does not depend on the threshold; moving the threshold only trades recall for false alarms. The threshold is
chosen on the training turbines' inner out-of-fold scores, for each budget B of false alarms per turbine-month. The alarm
rule is unchanged. Mean over the three farms, read on the test turbines:

| model | budget | event recall | recall before onset | day recall | false alarms / turbine-month (realised) | median lead (days) |
|---|---|---|---|---|---|---|
| CatBoost | 0.5 | 0.40 | 0.35 | 0.23 | 0.46 | 6.0 |
| CatBoost | 1 | 0.64 | 0.48 | 0.35 | 1.07 | 3.2 |
| **CatBoost** | **2** | **0.97** | **0.86** | 0.68 | **2.44** | 6.2 |
| CatBoost | 3+ | 1.00 | 0.94 | 0.81 | 3.10 | 7.0 |
| blend CB + GRU PCA | 0.5 | 0.34 | 0.31 | 0.22 | 0.47 | 6.5 |
| blend CB + GRU PCA | 1 | 0.55 | 0.46 | 0.34 | 0.88 | 7.0 |
| blend CB + GRU PCA | 2 | 0.81 | 0.66 | 0.49 | 1.70 | 6.5 |
| blend CB + GRU PCA | 3+ | 0.95 | 0.74 | 0.60 | 2.17 | 5.0 |
| GRU PCA | 2 | 0.74 | 0.56 | 0.36 | 1.39 | 6.7 |
| GRU PCA | 3+ | 0.76 | 0.59 | 0.42 | 1.70 | 6.7 |

Per farm at budget 2:
- CatBoost: event recall A 0.91, B 1.00, C 1.00, with false alarms 2.35 / 2.59 / 2.39.
- Blend: event recall A 0.91, B 0.67, C 0.85, with false alarms 1.42 / 1.98 / 1.70.

How to read it:
- **Above a budget of 3, nothing changes.** The threshold grid starts at the median score of the negative days, so it cannot
  alarm more often. The GRU spreads its scores less and saturates earliest, at about 1.7 false alarms.
- **Recall at a high budget is partly cheap.** The season-only model reaches a mean event recall of 0.79 at 2.9 false alarms
  per turbine-month. The baseline also showed that normal datasets get an alarm in the same 3-week span 55% of the time at a
  budget of 1.
- An event counts as caught if an alarm falls anywhere from 7 days before onset to the end of the window. Median lead times
  are capped at 7 days by that definition.
- **To maximise recall, CatBoost alone at a budget of 2 is the best trade:** 97% of events caught and 86% caught before the
  logged onset, at about 2.4 false notifications per turbine-month (about 24 per month for a 10-turbine park). The blend is
  better at a budget of 1 or below, the GRU is not useful in this regime, and the ROC-AUC is unchanged by any of these
  choices.

## 10. Day-level confusion matrices (section 16 of the notebook)

Test turbines, labelled usable days, k = 7. Predicted class = alarm day (2 of the last 3 days above the threshold). Figure:
`dataset/wind_turbine_scada_fault/cache/gru/confusion_matrices.png`.

| set-up | farm | TN | FP | FN | TP | day recall | precision | specificity |
|---|---|---|---|---|---|---|---|---|
| CatBoost, budget 2 | A | 2,434 | 1,685 | 69 | 134 | 0.66 | 0.07 | 0.59 |
| CatBoost, budget 2 | B | 1,406 | 1,519 | 120 | 164 | 0.58 | 0.10 | 0.48 |
| CatBoost, budget 2 | C | 6,303 | 5,364 | 130 | 492 | 0.79 | 0.08 | 0.54 |
| CatBoost, budget 2 | all | 10,143 | 8,568 | 319 | 790 | 0.71 | 0.08 | 0.54 |
| blend CB + GRU PCA, budget 1 | A | 3,399 | 720 | 88 | 115 | 0.57 | 0.14 | 0.83 |
| blend CB + GRU PCA, budget 1 | B | 2,380 | 545 | 283 | 1 | 0.00 | 0.00 | 0.81 |
| blend CB + GRU PCA, budget 1 | C | 9,980 | 1,687 | 348 | 274 | 0.44 | 0.14 | 0.86 |
| blend CB + GRU PCA, budget 1 | all | 15,759 | 2,952 | 719 | 390 | 0.35 | 0.12 | 0.84 |

- **The recall-first set-up alarms on 46% of the normal days.** The budget counts notifications, which are re-sent every
  7 days during a continuing alarm, not alarm days. So "2.4 false alarms per turbine-month" means alarms that stay on for
  long stretches.
- Precision is 8%: about 1 alarm day in 12 is a real positive day.
- That is why its event recall (0.97) is high, and why it is not much better than alarming often at random (season only:
  0.79).
- The blend at a budget of 1 is on for 16% of normal days with 12% precision, but it misses B completely (1 positive day
  of 284).
- With a k = 7 positive rate of 5% to 9% and a ROC-AUC around 0.6 to 0.7, high recall forces low precision. This is the
  practical limit of the current models, not of the threshold.

## 11. Minimising false negatives: threshold for a target day recall (section 17 of the notebook)

In each outer fold the threshold is the score that reaches the target day recall on the training turbines' inner scores.
A day alarms as soon as its score reaches it, with no 2-of-3 persistence, and a majority of the three fold seeds is needed.
Also tested: CatBoost without ambient and temperature features, alone and blended 50/50 with the GRU (groups + PCA). Its
test scores equal the baseline ablation run. Mean over the three farms, test turbines:

| target | model | false negative days | alarm on normal days | precision | events missed (of 44) |
|---|---|---|---|---|---|
| 80% | CatBoost | 8.3% | 77.1% | 7.3% | 0 |
| 80% | CatBoost, no temperature | 9.4% | 77.9% | 7.2% | 0 |
| 80% | blend CB + GRU | 18.3% | 57.6% | 8.5% | 1 |
| 80% | blend CB no temperature + GRU | 23.2% | 58.3% | 7.9% | 1 |
| 80% | GRU | 39.0% | 45.4% | 8.9% | 3 |
| 90% | CatBoost | 2.9% | 87.7% | 6.8% | 0 |
| 90% | blend CB + GRU | 10.2% | 75.1% | 7.3% | 0 |
| 90% | blend CB no temperature + GRU | 12.7% | 75.8% | 7.0% | 0 |
| 90% | GRU | 25.1% | 57.3% | 8.6% | 0 |
| 95% | CatBoost | 2.1% | 91.7% | 6.6% | 0 |
| 95% | blend CB + GRU | 9.0% | 82.5% | 6.8% | 0 |

Every operating point measured on the test turbines (mean over farms), from fewest alarms to fewest false negatives:

| set-up | alarm on normal days | false negative days |
|---|---|---|
| blend, budget 1, 2-of-3 rule (section 10) | 17% | 66% |
| CatBoost, budget 2, 2-of-3 rule (section 10) | 46% | 32% |
| blend, 80% target | 58% | 18% |
| blend, 90% target | 75% | 10% |
| CatBoost, 80% target | 77% | 8% |
| CatBoost, 90% target | 88% | 3% |

- **Getting false negatives below about 20% means alarming on more than half of the normal days, with every model.** Precision
  stays at 6% to 9%, barely above the positive rate. The models' ranking (ROC-AUC 0.6 to 0.7) is too weak to have both
  few false negatives and few alarms. No threshold fixes that.
- At equal false negatives, CatBoost and the blend lie on almost the same trade-off curve: CatBoost 80% (8% FN, 77% alarms)
  against blend 90% (10% FN, 75% alarms).
- **The blend with CatBoost without temperatures does not help:** it is slightly worse than the blend with full CatBoost
  at every target.
- Every event is caught at these targets, but only because the alarm is on most of the time.
- The thresholds transfer imperfectly. They are set on the training turbines and give different realised rates on the
  test turbines, for example 8% FN instead of 20% for CatBoost at the 80% target.
- The ROC-AUC column in the notebook's mean table is computed on raw seed-mean scores. It differs slightly from the
  headline, which is computed on calibrated risks.

## 12. Production model (section 18 of the notebook)

The ML1 model is the 50/50 blend CatBoost + GRU (groups + PCA 16), chosen by the project owner on 2026-11-08.

**How it was refitted**, on all turbines of each farm:

| farm | CatBoost | GRU | thresholds: budget_1 / recall_80 / recall_90 |
|---|---|---|---|
| A | 49 trees x 3 seeds | 7 epochs x 6 networks | 0.619 / -0.283 / -0.786 |
| B | 30 trees x 3 seeds | 2 epochs x 6 networks | 0.959 / -0.578 / -0.718 |
| C | 68 trees x 3 seeds | 2 epochs x 6 networks | 0.615 / -0.206 / -0.570 |

- The numbers of trees and epochs are the cross-validation medians.
- The blend standardisation, the isotonic calibration and the thresholds come from the out-of-fold scores.

**Files** in `models/ml1/`, each under 110 KB, see `models/ml1/README.md`:
- `catboost_<farm>_seed<s>.cbm`;
- `gru_<farm>.pt`;
- `gru_preprocess_<farm>.npz`;
- `ml1_contract.json`.

**Scoring:** `care_gru.ml1_scores` reproduces the notebook's direct scores exactly (maximum difference 0.0).

**Quality to quote:** use the cross-validated ROC-AUC (A 0.735, B 0.405, C 0.690). The in-sample ROC-AUC on the training
data is 0.96 to 0.98, which only shows that the models fit their training data; it is not a result.

## 13. What to use

- **One model for every farm:** the 50/50 blend CatBoost + GRU (groups + PCA 16).
  - Mean pooled ROC-AUC 0.610 and within-turbine 0.670, the best of everything tried.
  - Large gain in A (0.735), tie in B (0.405), small loss in C (0.690 against 0.714). The loss in C is not significant.
  - Its event recall is lower than CatBoost's (mean 0.55 against 0.64), at fewer false alarms (0.88 against 1.07).
- **A model per farm**, chosen on these results, so slightly optimistic: GRU groups + PCA in A, CatBoost or the blend
  CatBoost + GRU SHAP 20 in C, and nothing reliable in B.
- **Not useful:** score centring, and ridge regression (see the ridge notebook).
