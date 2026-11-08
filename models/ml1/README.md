# ML1: turbine fault risk, CatBoost + GRU blend

The model the agent uses for ML1. For every turbine and every day it gives the risk that the turbine is inside a fault
(anomaly) window or enters one within the next 7 days, plus alarm flags.

- **Built in:** `notebooks/care_gru.ipynb`, section 18.
- **Results and how it was chosen:** `notebooks/care_gru.md`.
- **Scoring code:** `fault_detection/care_gru.py`, function `ml1_scores`.

## What it is

- **CatBoost per farm.** One model per farm, on the baseline's daily deviation features (A 347, B 609, C 2055). Three
  seeds, probabilities averaged.
- **GRU per farm.** One layer, hidden 16. Its input is a window of the last 30 days of group deviations, 16 principal
  components of every sensor's deviation, and daily wind and power. Six networks, logits averaged.
- **The blend.** 50/50 on standardised logits: `0.5 * z_catboost + 0.5 * z_gru`. Each z uses the mean and standard
  deviation of that model's out-of-fold scores.
- **Training data.** The CARE wind-turbine SCADA collection: farms A, B and C, 36 turbines, 44 anomaly events. Each farm
  has its own models, because the farms have different sensors.

## Cross-validated quality (turbines held out, k = 7)

| farm | ROC-AUC pooled | ROC-AUC within turbine | events |
|---|---|---|---|
| A | 0.735 | 0.763 | 11 |
| B | 0.405 | 0.529 | 6 |
| C | 0.690 | 0.719 | 27 |
| **mean** | **0.610** | **0.670** | 44 |

For comparison, the CatBoost baseline scores a mean of 0.592 / 0.658. Farm B has no usable signal (6 events) with any
model.

## Thresholds (in `ml1_contract.json`)

Every threshold is set on out-of-fold scores. The alarm rate and the false negatives are means over the three farms on
held-out turbines:

| name | alarm rule | false negative days | alarm on normal days |
|---|---|---|---|
| `budget_1` | 2 of the last 3 days at or above the threshold | about 66% | about 17% |
| `recall_80` | any day at or above the threshold | about 18% | about 58% |
| `recall_90` | any day at or above the threshold | about 10% | about 75% |

- Picking one is a business decision: the cost of a missed fault against the cost of a needless inspection.
- With a ROC-AUC around 0.6, few false negatives always come with many alarms. The threshold moves along that trade-off;
  it cannot fix it.

## Inputs it needs

- The daily deviation table built as in `notebooks/care_catboost_baseline.ipynb`, sections 1 to 5:
  - each sensor against its operating-point model (wind, power, ambient) on the trailing window [t-180, t-60);
  - the robust |z| of every 10-minute row, aggregated per day as mean and 95th percentile;
  - group aggregates.
- That table needs **at least 180 days of 10-minute SCADA history per turbine**.
- The sensor names are those of the CARE farms. A new farm needs its own models.

## Limits

- **The output is k = 7 only.** It says "fault now or within 7 days", not the fault day. The agent's `days_to_failure`
  needs models for the horizons k = 1 to 7.
- **Most positive days lie inside an anomaly window.** The model mostly recognises a turbine that already behaves
  abnormally. The baseline found no convincing signal before onset.
- **About half of the Farm A gain is tied to temperature**, which in Farm A goes with season.
- **The application database has no SCADA history yet**, so the model cannot run there until that data exists.
