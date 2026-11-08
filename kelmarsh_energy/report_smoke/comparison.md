# Mamba2 against the other models

Kelmarsh, energy per 10-minute slot (kWh), 10 steps ahead, 78,570 test windows (2023-12-31 to 2024-03-31), one seed. Scaled columns divide by the largest actual value, 412 kWh (MAE by it, MSE by its square).

## All steps

| model | MSE | RMSE | MAE | R² | MSE scaled | MAE scaled | skill | epochs (best) | seconds |
|---|---|---|---|---|---|---|---|---|---|
| persistence | 4009.7 | 63.32 | 41.84 | 0.6775 | 0.02362 | 0.1016 | 0 | – | – |
| Mamba2 | 2633.4 | 51.32 | 33.91 | 0.7882 | 0.01551 | 0.0823 | +0.189 | 45 (35) | 3455 |
| LSTM | 2568.3 | 50.68 | 33.72 | 0.7935 | 0.01513 | 0.0818 | +0.194 | 30 (20) | 451 |
| LSTM + attention | 2577.6 | 50.77 | 33.79 | 0.7927 | 0.01518 | 0.0820 | +0.192 | 36 (26) | 515 |
| XGBoost | 2676.3 | 51.73 | 35.25 | 0.7848 | 0.01577 | 0.0855 | +0.158 | – | 1 |
| Linear | 2634.9 | 51.33 | 34.47 | 0.7881 | 0.01552 | 0.0837 | +0.176 | – | 1 |

## Mamba2 against each model, window by window

Difference of the mean absolute error of a window over its steps, the other model's minus Mamba2's: positive means Mamba2 errs less. Interval: block bootstrap, 2000 resamples.

| other model | difference, kWh | 95% interval | resamples above 0 | blocks | verdict |
|---|---|---|---|---|---|
| LSTM | -0.194 | [-0.252, -0.130] | 0.000 | 6 | Mamba2 worse |
| LSTM + attention | -0.122 | [-0.180, -0.063] | 0.000 | 6 | Mamba2 worse |
| XGBoost | +1.332 | [+1.139, +1.535] | 1.000 | 6 | Mamba2 better |
| Linear | +0.554 | [+0.396, +0.726] | 1.000 | 6 | Mamba2 better |

## MAE per step (kWh)

| step | persistence | Mamba2 | LSTM | LSTM + attention | XGBoost | Linear |
|---|---|---|---|---|---|---|
| 10 min | 33.25 | 18.57 | 18.44 | 18.45 | 19.45 | 20.62 |
| 20 min | 37.97 | 25.10 | 24.93 | 25.00 | 26.00 | 26.13 |
| 30 min | 28.91 | 28.94 | 28.82 | 28.89 | 29.78 | 29.01 |
| 40 min | 43.44 | 32.01 | 31.86 | 31.92 | 33.12 | 32.76 |
| 50 min | 45.37 | 34.42 | 34.21 | 34.28 | 35.64 | 34.92 |
| 60 min | 36.43 | 36.38 | 36.23 | 36.31 | 37.66 | 36.46 |
| 70 min | 48.63 | 38.41 | 38.25 | 38.31 | 39.98 | 38.95 |
| 80 min | 50.01 | 40.19 | 39.94 | 40.00 | 41.96 | 40.52 |
| 90 min | 41.69 | 41.75 | 41.48 | 41.58 | 43.56 | 41.70 |
| 100 min | 52.70 | 43.35 | 43.03 | 43.16 | 45.30 | 43.61 |

## MAE per turbine (kWh, all steps)

| turbine | windows | persistence | Mamba2 | LSTM | LSTM + attention | XGBoost | Linear |
|---|---|---|---|---|---|---|---|
| T01 | 13,095 | 43.49 | 34.70 | 34.62 | 34.67 | 36.21 | 35.21 |
| T02 | 13,095 | 45.85 | 35.63 | 35.43 | 35.50 | 37.27 | 36.50 |
| T03 | 13,095 | 43.59 | 35.81 | 35.60 | 35.78 | 36.82 | 36.29 |
| T04 | 13,095 | 35.60 | 29.90 | 29.64 | 29.70 | 31.52 | 30.65 |
| T05 | 13,095 | 43.97 | 36.17 | 35.88 | 35.96 | 37.26 | 36.40 |
| T06 | 13,095 | 38.54 | 31.27 | 31.16 | 31.13 | 32.39 | 31.75 |
