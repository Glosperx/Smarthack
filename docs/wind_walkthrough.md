# Walkthrough: Wind Turbine Power Forecasting Pipeline & Kaggle Notebook

We have significantly improved the models by introducing **Physics & Sequential Feature Engineering V2**, adding **CatBoost**, and building an optimal **Tri-Model Ensemble (LightGBM + XGBoost + CatBoost)**.

---

## 1. Model Improvement Benchmark & Evolution

We benchmarked the improvements across all **175,200 hourly meteorological observations** on the strict 2021 holdout test set (35,040 samples) with **zero location identifiers**:

| Version & Model Family | Test RMSE | Test MAE | Test $R^2$ | 5-Fold Full CV $R^2$ |
| :--- | :---: | :---: | :---: | :---: |
| 🥉 *V1 Universal Baseline (Ridge)* | 0.2188 | 0.1640 | 0.3335 | 0.5820 |
| 🥈 *V1 Universal Ensemble (LGB+XGB)* | 0.2087 | 0.1539 | 0.3937 | 0.6425 |
| 🏆 **V2 Tri-Ensemble (40% LGB + 40% XGB + 20% CatBoost)** | **0.2047** | **0.1495** | **0.4167** | **0.6908** |

### Key Improvements Made:
1. **5-Fold Cross Validation $R^2$ jumped from 0.6425 to 0.6908 (+4.8% absolute variance explained)** across the entire 5-year dataset.
2. **Holdout Test $R^2$ improved from 0.3937 to 0.4167 (+2.3% gain)**.
3. **Holdout Test RMSE dropped to 0.2047** and **MAE dropped to 0.1495**.

---

## 2. What Made the Difference? (The Improvements)

### A. Physics-Informed Operational Regimes
* **Cut-in & Rated Threshold Indicators**: Binary indicators for when wind speed is below mechanical cut-in ($v < 3.0$ m/s), in the cubic ramp ($3.0 \le v < 13.0$ m/s), at rated plateau ($13.0 \le v < 25.0$ m/s), and shut down for safety ($v \ge 25.0$ m/s).
* **Piecewise Physical Cubic Ramp**:
  $$\text{Ramp}_{\text{cubic}} = \left[\text{clip}\left(\frac{v_{100m} - 3.0}{10.0}, 0, 1\right)\right]^3$$
  Injects the theoretical Betz-law power curve directly into the tree leaf splits.

### B. Sequential Temporal Dynamics
* **Lag & Lead Wind Speeds**: Captures atmospheric front inertia ($v_{t-1}$ and $v_{t+1}$).
* **Wind Acceleration**: $\Delta v = v_{100m}(t) - v_{100m}(t-1)$.
* **Rolling Volatility & Turbulence**: 3-hour and 6-hour rolling wind speed means and standard deviations capturing gust fronts.
* **Thermal Shock**: 3-hour temperature gradient ($\Delta T_{3h}$) detecting cold/warm front passages that cause sudden air density shifts.

### C. Tri-Model Gradient Boosting Blend
* Combining **LightGBM** (leaf-wise speed), **XGBoost** (histogram regularization), and **CatBoost** (symmetric oblivious trees) reduces individual model variance and generalizes significantly better across unseen meteorological regimes.

---

## 3. Artifacts & Codebase Created

| File | Purpose |
| :--- | :--- |
| [wind_power_forecasting_xgboost.ipynb](file:///home/stefan/sandbox/wind_power_forecasting_xgboost.ipynb) | Publication-ready Kaggle notebook updated with V2 features, CatBoost, Tri-Ensemble, and live API demo. |
| [predict.py](file:///home/stefan/sandbox/predict.py) | CLI tool that defaults to the winning Tri-Ensemble to generate multi-day hourly kW/MW forecasts for any GPS coordinates. |
| [src/features.py](file:///home/stefan/sandbox/src/features.py) | Complete physics-informed feature pipeline with sequential dynamics (46 features). |
| [src/inference.py](file:///home/stefan/sandbox/src/inference.py) | Inference engine with `load_tri_ensemble()` and Open-Meteo REST API client. |
| [train_benchmark.py](file:///home/stefan/sandbox/train_benchmark.py) | Standalone script benchmarking Ridge, Random Forest, XGBoost, LightGBM, CatBoost, and Tri-Ensemble. |
| [tests/test_pipeline.py](file:///home/stefan/sandbox/tests/test_pipeline.py) | 100% passing automated test suite. |
| [models/](file:///home/stefan/sandbox/models) | Serialized models (`xgboost_wind_power.json`, `lightgbm_wind_power.joblib`, `catboost_wind_power.cbm`). |

---

## 4. Live Verification & Testing

```bash
# Run automated test suite
PYTHONPATH=. pytest tests/
# 4 passed in 2.85s (100% pass rate)

# Run live prediction for any wind site worldwide
python predict.py --lat 54.0 --lon 7.0 --days 3 --capacity-kw 3000
```
