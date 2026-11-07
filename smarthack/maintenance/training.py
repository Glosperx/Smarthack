"""
# Predictive maintenance training pipeline

Training and persistence of early fault detection classifiers from SCADA benchmarks.

The following can be imported from this module:
- `load_event_dataset`
- `resolve_maintenance_data_dir`
- `train_fault_classifier`
"""

import json
import logging
from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, roc_auc_score

from smarthack.maintenance.features import extract_maintenance_features

logger = logging.getLogger(__name__)


def resolve_maintenance_data_dir(data_dir: str | Path | None = None) -> Path:
    """
    Resolve the path to the wind turbine maintenance dataset directory.

    :param data_dir: Optional explicit directory path.

    :returns path: Resolved Path object.
    """
    if data_dir is not None:
        return Path(data_dir)
    return Path("/home/stefan/maintenance/maintenance/Wind Farm A")


def load_event_dataset(
    data_dir: str | Path | None = None,
    max_samples_per_file: int = 50,
) -> tuple[pd.DataFrame, np.ndarray, list[str]]:
    """
    Ingest SCADA event datasets and extract predictive maintenance training features.

    :param data_dir: Root directory of Wind Farm A dataset.
    :param max_samples_per_file: Max intervals to sample from each event episode.

    :returns tuple: Feature DataFrame `X`, binary labels `y`, and component descriptions.
    """
    base_dir = resolve_maintenance_data_dir(data_dir)
    event_info_path = base_dir / "event_info.csv"

    if not event_info_path.is_file():
        raise FileNotFoundError(f"Missing event information file: {event_info_path}")

    event_info = pd.read_csv(event_info_path, sep=";")
    x_records: list[dict[str, Any]] = []
    y_records: list[int] = []
    components: list[str] = []

    for _, row in event_info.iterrows():
        event_id = str(row["event_id"])
        label = row["event_label"]
        csv_file = base_dir / "datasets" / f"{event_id}.csv"
        if not csv_file.is_file():
            continue

        df = pd.read_csv(csv_file, sep=";")
        pred_df = df[df["train_test"] == "prediction"]
        if len(pred_df) == 0:
            pred_df = df.tail(1500)

        feat_df = extract_maintenance_features(pred_df)
        is_anomaly = 1 if label == "anomaly" else 0
        desc = str(row.get("event_description", "Fault")) if is_anomaly else "Normal"

        indices = np.linspace(
            0, len(feat_df) - 1, min(max_samples_per_file, len(feat_df)), dtype=int
        )
        for idx in indices:
            x_records.append(feat_df.iloc[idx].to_dict())
            y_records.append(is_anomaly)
            components.append(desc)

    x_df = pd.DataFrame(x_records)
    y_arr = np.array(y_records, dtype=int)
    return x_df, y_arr, components


def train_fault_classifier(
    data_dir: str | Path | None = None,
    models_dir: str | Path | None = None,
    n_estimators: int = 150,
) -> dict[str, Any]:
    """
    Train and serialize the early fault warning classifier.

    :param data_dir: Directory containing SCADA benchmark files.
    :param models_dir: Directory where trained artifacts will be saved.
    :param n_estimators: Number of boosting trees.

    :returns metrics: Dictionary containing training AUC and F1 scores.
    """
    target_models_dir = (
        Path(models_dir) if models_dir else Path("/home/stefan/Smarthack/models/maintenance")
    )
    target_models_dir.mkdir(parents=True, exist_ok=True)

    x_df, y_arr, _ = load_event_dataset(data_dir=data_dir)
    feature_names = list(x_df.columns)

    model = lgb.LGBMClassifier(
        n_estimators=n_estimators,
        learning_rate=0.05,
        max_depth=5,
        num_leaves=20,
        random_state=42,
        verbose=-1,
    )
    model.fit(x_df, y_arr)

    probs = np.asarray(model.predict_proba(x_df))[:, 1]
    preds = (probs >= 0.5).astype(int)
    auc = float(roc_auc_score(y_arr, probs))
    f1 = float(f1_score(y_arr, preds))

    joblib.dump(model, target_models_dir / "fault_classifier.joblib")
    with open(target_models_dir / "fault_features.json", "w") as f:
        json.dump(feature_names, f, indent=2)

    return {"auc": round(auc, 4), "f1": round(f1, 4), "samples": len(x_df)}


__all__ = [
    "load_event_dataset",
    "resolve_maintenance_data_dir",
    "train_fault_classifier",
]
