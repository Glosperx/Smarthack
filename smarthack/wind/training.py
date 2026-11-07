"""
# Wind model training and benchmarking

Dataset ingestion, feature generation, temporal cross-validation, and model persistence.

The following can be imported from this module:
- `evaluate_predictions`
- `load_dataset`
- `resolve_data_dir`
- `train_and_benchmark`
"""

import json
import logging
from pathlib import Path
import time
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from smarthack.config import wind_data_dir
from smarthack.wind.constants import WEIGHT_CATBOOST, WEIGHT_LIGHTGBM, WEIGHT_XGBOOST
from smarthack.wind.features import add_features, get_feature_columns
from smarthack.wind.predictor import resolve_models_dir

logger = logging.getLogger(__name__)


def resolve_data_dir(data_dir: str | Path | None = None) -> Path:
    """
    Resolve the filesystem path where wind training datasets are stored.

    :param data_dir: Explicit path to directory, or None to use configuration.

    :returns path: Resolved Path to datasets directory.
    """
    if data_dir is not None:
        return Path(data_dir)
    return wind_data_dir()


def load_dataset(data_dir: str | Path | None = None) -> pd.DataFrame:
    """
    Load and concatenate wind turbine meteorological observations across all 4 locations.

    :param data_dir: Path to directory containing Location1.csv through Location4.csv.

    :returns combined: Consolidated historical dataframe sorted chronologically.
    :raises FileNotFoundError: If any expected location CSV file is missing.
    """
    path = resolve_data_dir(data_dir)
    dfs: list[pd.DataFrame] = []
    for loc_id in range(1, 5):
        csv_path = path / f"Location{loc_id}.csv"
        if not csv_path.is_file():
            raise FileNotFoundError(f"Missing required dataset: {csv_path}")
        df_loc = pd.read_csv(csv_path)
        df_loc["location_id"] = loc_id
        dfs.append(df_loc)

    combined = pd.concat(dfs, ignore_index=True)
    combined["Time"] = pd.to_datetime(combined["Time"])
    return combined.sort_values(by=["Time", "location_id"]).reset_index(drop=True)


def evaluate_predictions(y_true: Any, y_pred: Any, name: str = "Model") -> dict[str, Any]:
    """
    Compute regression error metrics (RMSE, MAE, R2) for predicted turbine power.

    :param y_true: Ground-truth target values in [0.0, 1.0].
    :param y_pred: Raw predicted values.
    :param name: Label identifying the model.

    :returns metrics: Dictionary with RMSE, MAE, and R2 scores.
    """
    y_pred_clipped = np.clip(y_pred, 0.0, 1.0)
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred_clipped)))
    mae = float(mean_absolute_error(y_true, y_pred_clipped))
    r2 = float(r2_score(y_true, y_pred_clipped))
    return {"Model": name, "RMSE": round(rmse, 4), "MAE": round(mae, 4), "R2": round(r2, 4)}


def train_and_benchmark(
    data_dir: str | Path | None = None,
    models_dir: str | Path | None = None,
    train_until: str = "2021-01-01",
    fast_mode: bool = False,
) -> dict[str, Any]:
    """
    Train and benchmark the full suite of regression models, saving best artifacts.

    Trains Ridge baseline, Random Forest, XGBoost, LightGBM, CatBoost, and the
    Tri-Ensemble blend on historical observations before train_until, and evaluates
    on the holdout test set.

    :param data_dir: Directory containing Location1.csv to Location4.csv.
    :param models_dir: Target directory where serialized models are stored.
    :param train_until: Date threshold dividing training and evaluation sets.
    :param fast_mode: Whether to run minimal iterations for fast testing.

    :returns results: Leaderboard dictionary with test metrics and per-model scores.
    """
    target_dir = resolve_models_dir(models_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    df_raw = load_dataset(data_dir)
    logger.info("Loaded wind dataset from %s", resolve_data_dir(data_dir))

    logger.info("Computing physics-informed features on %d raw rows", len(df_raw))
    df = add_features(df_raw, is_training=True)
    feature_cols = get_feature_columns(df)

    train_mask = df["Time"] < train_until
    test_mask = df["Time"] >= train_until

    x_train = df.loc[train_mask, feature_cols]
    y_train = df.loc[train_mask, "Power"]
    x_test = df.loc[test_mask, feature_cols]
    y_test = df.loc[test_mask, "Power"]

    # Heavy libraries imported inside training function
    from catboost import CatBoostRegressor
    import joblib
    import lightgbm as lgb
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    import xgboost as xgb

    leaderboard: list[dict[str, Any]] = []

    # 1. Ridge Baseline
    t0 = time.time()
    ridge = Pipeline([("scaler", StandardScaler()), ("ridge", Ridge(alpha=10.0))])
    ridge.fit(x_train, y_train)
    res_ridge = evaluate_predictions(y_test, ridge.predict(x_test), "Ridge Baseline")
    res_ridge["Train Time (s)"] = round(time.time() - t0, 2)
    leaderboard.append(res_ridge)

    # 2. Random Forest
    t0 = time.time()
    rf = RandomForestRegressor(
        n_estimators=2 if fast_mode else 100,
        max_depth=3 if fast_mode else 16,
        min_samples_leaf=1 if fast_mode else 10,
        n_jobs=-1,
        random_state=42,
    )
    rf.fit(x_train, y_train)
    res_rf = evaluate_predictions(y_test, rf.predict(x_test), "Random Forest")
    res_rf["Train Time (s)"] = round(time.time() - t0, 2)
    leaderboard.append(res_rf)

    # 3. XGBoost
    t0 = time.time()
    xgb_model = xgb.XGBRegressor(
        n_estimators=2 if fast_mode else 400,
        learning_rate=0.06,
        max_depth=3 if fast_mode else 8,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=1.0,
        tree_method="hist",
        random_state=42,
        n_jobs=-1,
    )
    xgb_model.fit(x_train, y_train)
    t_xgb = time.time() - t0
    y_pred_xgb = xgb_model.predict(x_test)
    res_xgb = evaluate_predictions(y_test, y_pred_xgb, "XGBoost Regressor")
    res_xgb["Train Time (s)"] = round(t_xgb, 2)
    leaderboard.append(res_xgb)

    # 4. LightGBM
    t0 = time.time()
    lgb_model = lgb.LGBMRegressor(
        n_estimators=2 if fast_mode else 500,
        learning_rate=0.05,
        num_leaves=7 if fast_mode else 95,
        max_depth=3 if fast_mode else 9,
        subsample=0.85,
        colsample_bytree=0.8,
        min_child_samples=1 if fast_mode else 30,
        reg_alpha=0.2,
        reg_lambda=1.5,
        random_state=42,
        n_jobs=-1,
        verbose=-1,
    )
    lgb_model.fit(x_train, y_train)
    t_lgb = time.time() - t0
    y_pred_lgb = lgb_model.predict(x_test)
    res_lgb = evaluate_predictions(y_test, y_pred_lgb, "LightGBM Regressor")
    res_lgb["Train Time (s)"] = round(t_lgb, 2)
    leaderboard.append(res_lgb)

    # 5. CatBoost
    t0 = time.time()
    cb_model = CatBoostRegressor(
        iterations=2 if fast_mode else 500,
        learning_rate=0.06,
        depth=3 if fast_mode else 7,
        l2_leaf_reg=3.0,
        random_seed=42,
        verbose=0,
        thread_count=-1,
    )
    cb_model.fit(x_train, y_train)
    t_cb = time.time() - t0
    y_pred_cb = cb_model.predict(x_test)
    res_cb = evaluate_predictions(y_test, y_pred_cb, "CatBoost Regressor")
    res_cb["Train Time (s)"] = round(t_cb, 2)
    leaderboard.append(res_cb)

    # 6. Tri-Model Ensemble
    y_pred_blend = (
        WEIGHT_LIGHTGBM * np.asarray(y_pred_lgb)
        + WEIGHT_XGBOOST * np.asarray(y_pred_xgb)
        + WEIGHT_CATBOOST * np.asarray(y_pred_cb)
    )
    res_blend = evaluate_predictions(y_test, y_pred_blend, "Tri-Ensemble (LGB+XGB+CB)")
    res_blend["Train Time (s)"] = round(t_xgb + t_lgb + t_cb, 2)
    leaderboard.append(res_blend)

    # Save artifacts
    xgb_model.save_model(str(target_dir / "xgboost_wind_power.json"))
    joblib.dump(lgb_model, str(target_dir / "lightgbm_wind_power.joblib"))
    cb_model.save_model(str(target_dir / "catboost_wind_power.cbm"))

    (target_dir / "feature_columns.json").write_text(
        json.dumps(feature_cols, indent=2), encoding="utf-8"
    )

    df_results = pd.DataFrame(leaderboard).sort_values(by="RMSE")
    df_results.to_csv(target_dir / "benchmark_results.csv", index=False)
    logger.info("Saved models and benchmark results to %s", target_dir)

    return {
        "leaderboard": df_results.to_dict(orient="records"),
        "best_model": df_results.iloc[0]["Model"],
        "best_rmse": float(df_results.iloc[0]["RMSE"]),
        "best_r2": float(df_results.iloc[0]["R2"]),
    }


__all__ = ["evaluate_predictions", "load_dataset", "resolve_data_dir", "train_and_benchmark"]

if __name__ == "__main__":
    train_and_benchmark()
