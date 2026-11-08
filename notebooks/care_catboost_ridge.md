# CARE: CatBoost + ridge logistic regression, correlation and blend weights

Source: `notebooks/care_catboost_ridge.ipynb`, run from scratch on 2026-11-08 in the conda env `ml_def` with nbconvert,
0 errors. Sections 1 to 7 of the notebook are the baseline's, copied unchanged, and run on the same folds, labels, seeds,
threshold rule and bootstrap as `notebooks/care_catboost_baseline.md`. Outputs are in
`dataset/wind_turbine_scada_fault/cache/catboost_ridge/`.

**Verdict: no model here beats the CatBoost baseline under the baseline rules (section 8 of its .md), in any farm.**
CatBoost per farm stays the baseline and the model to use.

## 1. Setup

- **Ridge model.** A logistic regression with an L2 (ridge) penalty, on the same `full` features as CatBoost per farm
  (A 347, B 609, C 2,055). Plain Ridge on a 0/1 target gives no probabilities, so the logistic form is used.
  - Preprocessing is fitted on the training rows only: winsorising at the 0.5 and 99.5 percentiles, filling missing values
    with the median, and standardising.
  - `C` (the inverse penalty) is picked from 1e-4 to 1 inside every outer fold, on the 3 inner turbine groups.
- **Blend.** `w * z_catboost + (1 - w) * z_ridge`, where each z is a logit standardised on its own inner out-of-fold scores.
  w = 1 is CatBoost alone, w = 0 is ridge alone.
  - `blend 50/50`: w = 0.5, fixed in advance.
  - `blend, nested weight`: w picked inside every outer fold, on the inner out-of-fold ROC-AUC of the training turbines.
- **CatBoost** is refitted with the same seeds and parameters, so its inner out-of-fold scores are available. Its test
  scores equal the saved baseline run exactly: the maximum difference is 0.0 in every farm and seed.

## 2. Headline (k = 7, out-of-fold, three-seed ensemble)

| farm | model | ROC-AUC pooled [95% CI] | ROC-AUC within turbine [95% CI] | event recall [95% CI] | false alarms / turbine-month |
|---|---|---|---|---|---|
| A | season only | 0.645 [0.473, 0.883] | 0.673 [0.518, 0.876] | 0.91 [0.70, 1.00] | 3.21 |
| A | **CatBoost per farm** | **0.658 [0.604, 0.756]** | **0.695 [0.639, 0.767]** | **0.73 [0.60, 0.90]** | 0.91 |
| A | ridge logistic | 0.569 [0.513, 0.728] | 0.598 [0.511, 0.750] | 0.64 [0.36, 0.91] | 0.98 |
| A | blend 50/50 | 0.635 [0.560, 0.751] | 0.658 [0.573, 0.764] | 0.64 [0.45, 0.89] | 0.98 |
| A | blend, nested weight | 0.640 [0.574, 0.739] | 0.660 [0.598, 0.738] | 0.73 [0.60, 0.90] | 0.95 |
| B | season only | 0.287 [0.136, 0.387] | 0.385 [0.210, 0.500] | 0.50 [0.12, 1.00] | 2.26 |
| B | **CatBoost per farm** | **0.403 [0.307, 0.500]** | **0.550 [0.518, 0.599]** | **0.33 [0.00, 0.75]** | 1.23 |
| B | ridge logistic | 0.437 [0.351, 0.524] | 0.569 [0.466, 0.694] | 0.67 [0.25, 1.00] | 1.11 |
| B | blend 50/50 | 0.413 [0.368, 0.478] | 0.542 [0.512, 0.599] | 0.50 [0.00, 1.00] | 1.17 |
| B | blend, nested weight | 0.456 [0.396, 0.529] | 0.570 [0.470, 0.691] | 0.50 [0.00, 0.88] | 1.28 |
| C | season only | 0.447 [0.381, 0.520] | 0.496 [0.437, 0.553] | 0.96 [0.88, 1.00] | 3.20 |
| C | **CatBoost per farm** | **0.714 [0.584, 0.813]** | **0.728 [0.604, 0.820]** | **0.85 [0.71, 0.97]** | 1.06 |
| C | ridge logistic | 0.679 [0.591, 0.760] | 0.715 [0.625, 0.805] | 0.70 [0.52, 0.85] | 0.96 |
| C | blend 50/50 | 0.728 [0.624, 0.816] | 0.753 [0.655, 0.836] | 0.81 [0.65, 0.95] | 1.03 |
| C | blend, nested weight | 0.709 [0.579, 0.815] | 0.738 [0.616, 0.834] | 0.78 [0.62, 0.92] | 1.03 |

The CatBoost rows are identical to the baseline.

**Paired difference against CatBoost per farm** (pooled ROC-AUC, 95% CI from the paired cluster bootstrap over turbines):

| farm | ridge logistic | blend 50/50 | blend, nested weight |
|---|---|---|---|
| A | -0.089 [-0.188, +0.056] | -0.023 [-0.073, +0.066] | -0.018 [-0.061, +0.029] |
| B | +0.034 [-0.064, +0.133] | +0.010 [-0.055, +0.090] | +0.053 [-0.041, +0.152] |
| C | -0.036 [-0.130, +0.061] | +0.013 [-0.035, +0.059] | -0.006 [-0.050, +0.037] |

Every interval contains zero. The within-turbine differences behave the same way; the best is the C blend 50/50 at
+0.024 [-0.030, +0.077].

**Same position** (anomaly against normal datasets, days -7 to +14 around each dataset's own window start, dataset AUC of the
maximum score, permutation p):
- A: CatBoost 0.645 (p 0.13); ridge 0.446; blend 50/50 0.587.
- B: CatBoost 0.241; ridge 0.463; blend 50/50 0.278. Every value is near or below 0.5.
- C: CatBoost 0.689 (p 0.008); ridge 0.649 (p 0.027); **blend 50/50 0.718 (p 0.002)**; nested blend 0.688.

## 3. How correlated the two models are

| farm | Spearman, all days | positive days | negative days | within turbine (mean) |
|---|---|---|---|---|
| A | 0.31 | 0.47 | 0.30 | 0.42 |
| B | 0.33 | -0.04 | 0.35 | 0.32 |
| C | 0.24 | 0.49 | 0.22 | 0.39 |

Events caught with an alarm, at the threshold set on the training turbines:

| farm | events | both | CatBoost only | ridge only | neither |
|---|---|---|---|---|---|
| A | 11 | 6 | 2 | 1 | 2 |
| B | 6 | 2 | 0 | 2 | 2 |
| C | 27 | 18 | 5 | 1 | 3 |

- The two models rank days quite differently (Spearman 0.24 to 0.33), so a blend has room to help.
- The difference is mostly ridge noise. Ridge alone is weaker in A and C, and it catches only 1 event that CatBoost misses
  in each of those farms.
- The notebook also reports the correlation of the errors `y - p`. It comes out at 0.98 to 0.99 because, at a 5% to 9%
  positive rate, y dominates the errors, so it says nothing about the models. Read the Spearman values instead.

## 4. Which weight

Pooled ROC-AUC on the test turbines for each weight w (seed-mean raw scores, so slightly above the calibrated headline).
Picking the best w from this table would tune on the test data.

| w | 0 (ridge) | 0.2 | 0.4 | 0.5 | 0.6 | 0.7 | 0.8 | 1 (CatBoost) |
|---|---|---|---|---|---|---|---|---|
| A | 0.603 | 0.628 | 0.649 | 0.657 | 0.663 | 0.668 | 0.674 | **0.685** |
| B | 0.547 | 0.554 | **0.559** | 0.558 | 0.554 | 0.546 | 0.532 | 0.504 |
| C | 0.711 | 0.731 | 0.748 | 0.754 | 0.758 | **0.759** | **0.759** | 0.749 |

- **A:** CatBoost alone is best, and the curve rises all the way to w = 1.
- **B:** flat around 0.55, so there is no signal to weigh.
- **C:** a broad maximum at w = 0.6 to 0.8, only +0.01 over CatBoost alone, well inside the noise.
- **The nested weight is unstable**, because the inner turbine groups carry few events. Chosen w over 15 / 27 / 15 folds:
  - A: from 0.1 to 1, with 1 in 7 folds;
  - B: 0 in 16 of 27 folds;
  - C: from 0.1 to 1, median 0.6.

  This is why the nested blend scores below the fixed 50/50 blend in C.
- **Regularisation chosen:**
  - C: strong, with `C` from 1e-4 to 1e-3 in 11 of 15 folds; the inner ROC-AUC peaks at 1e-3.
  - A and B: weak, with `C` from 0.1 to 1. The inner ROC-AUC still rises at `C` = 1, so a strong penalty only hurts
    there (A 0.45 at 1e-4 against 0.62 at 1).

## 5. Without ambient and temperatures (baseline rule 4)

Pooled ROC-AUC, `no_ambient_no_temp` features:

| farm | CatBoost | ridge | blend 50/50 | blend, nested weight |
|---|---|---|---|---|
| A | 0.688 | 0.486 | 0.567 | 0.669 |
| B | 0.384 | 0.272 | 0.263 | 0.305 |
| C | 0.733 | 0.677 | 0.732 | 0.731 |

- Without temperatures, ridge collapses in A (0.49) and in B. Its A signal was largely ambient and temperature, which is
  season (see the baseline's season-aware correlation).
- In C, the blend and CatBoost tie.

## 6. Verdict against the baseline rules

| farm | best new model | 1 metrics above CatBoost | 2 beats season | 3 same position | 4 without temperatures | better than baseline |
|---|---|---|---|---|---|---|
| A | blend, nested weight | no | no | no | yes | **no** |
| B | blend, nested weight | no | yes (all below 0.5) | yes (all below 0.5) | no | **no** |
| C | blend 50/50 | no: AUC higher, event recall 0.81 < 0.85 | yes | yes | yes | **no** |

- **Farm C** is the only place the blend looks promising.
  - Gains: +0.013 pooled and +0.024 within-turbine ROC-AUC, and a better same-position AUC (0.718, p 0.002).
  - Loss: one event fewer (22 of 27 against 23), and no difference is significant.
  - A per-farm switch to the 50/50 blend in C would be a judgement call, not a demonstrated improvement.
- **Farm A:** adding ridge only hurts. CatBoost alone is the best weight.
- **Farm B:** still no usable model, with every pooled ROC-AUC below 0.5.

**Conclusion:** keep CatBoost per farm. A strongly regularised linear model does not add a reliable signal here. On the 44
events, the two models differ mainly where ridge is wrong.
