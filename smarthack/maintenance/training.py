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

from smarthack.config import maintenance_data_dir, maintenance_models_dir
from smarthack.maintenance.constants import (
    SCENARIO_BEARING_OVERHEATING,
    SCENARIO_GEARBOX_WEAR,
    SCENARIO_HYDRAULIC_LEAK,
    SCENARIO_NORMAL,
    SCENARIO_TRANSFORMER_OVERHEATING,
)
from smarthack.maintenance.features import extract_maintenance_features
from smarthack.maintenance.simulator import ScadaSimulator

logger = logging.getLogger(__name__)


def resolve_maintenance_data_dir(data_dir: str | Path | None = None) -> Path:
    """
    Resolve the path to the wind turbine maintenance dataset directory.

    :param data_dir: Optional explicit directory path.

    :returns path: Resolved Path object.
    """
    if data_dir is not None:
        return Path(data_dir)
    return maintenance_data_dir()


def _map_subsystem(desc: str) -> str:
    """Map raw event log description into canonical subsystem category."""
    desc_lower = desc.lower()
    if "bearing" in desc_lower and "generator" in desc_lower:
        return "Generator Bearing"
    if "gearbox" in desc_lower:
        return "Gearbox"
    if "hydraulic" in desc_lower:
        return "Hydraulic Group"
    if "transformer" in desc_lower:
        return "Transformer"
    return "Normal"


def load_event_dataset(
    data_dir: str | Path | None = None,
    max_samples_per_file: int = 60,
) -> tuple[pd.DataFrame, np.ndarray, list[str]]:
    """
    Ingest SCADA event datasets and extract predictive maintenance training features.

    :param data_dir: Root directory of Wind Farm A dataset.
    :param max_samples_per_file: Max intervals to sample from each event episode.

    :returns tuple: Feature DataFrame `X`, binary labels `y`, and subsystem labels.
    """
    base_dir = resolve_maintenance_data_dir(data_dir)
    event_info_path = base_dir / "event_info.csv"

    x_records: list[dict[str, Any]] = []
    y_binary: list[int] = []
    y_subsystems: list[str] = []

    if event_info_path.is_file():
        event_info = pd.read_csv(event_info_path, sep=";")
        for _, row in event_info.iterrows():
            event_id = str(row["event_id"])
            label = row["event_label"]
            raw_desc = str(row.get("event_description", "Normal"))
            subsys = _map_subsystem(raw_desc) if label == "anomaly" else "Normal"

            csv_file = base_dir / "datasets" / f"{event_id}.csv"
            if not csv_file.is_file():
                continue

            df = pd.read_csv(csv_file, sep=";")
            if label == "anomaly":
                start_id = int(row.get("event_start_id", 0))
                end_id = int(row.get("event_end_id", len(df)))
                slice_df = df[(df["id"] >= max(0, start_id - 288)) & (df["id"] <= end_id)]
            else:
                slice_df = df[df["train_test"] == "prediction"]
                if len(slice_df) == 0:
                    slice_df = df.tail(1500)

            feat_df = extract_maintenance_features(slice_df)
            is_anomaly = 1 if label == "anomaly" else 0
            indices = np.linspace(
                0, len(feat_df) - 1, min(max_samples_per_file, len(feat_df)), dtype=int
            )
            for idx in indices:
                x_records.append(feat_df.iloc[idx].to_dict())
                y_binary.append(is_anomaly)
                y_subsystems.append(subsys)

    # Augment with simulated scenarios to guarantee dense balance across all subsystems
    sim = ScadaSimulator(seed=101)
    scenario_map = [
        (SCENARIO_NORMAL, 0, "Normal"),
        (SCENARIO_BEARING_OVERHEATING, 1, "Generator Bearing"),
        (SCENARIO_GEARBOX_WEAR, 1, "Gearbox"),
        (SCENARIO_HYDRAULIC_LEAK, 1, "Hydraulic Group"),
        (SCENARIO_TRANSFORMER_OVERHEATING, 1, "Transformer"),
    ]
    for scn, is_ano, sub_name in scenario_map:
        for seed_offset in (10, 20, 30):
            df_sim = sim.generate_stream(asset_id=seed_offset, duration_hours=48, scenario=scn)
            feat_sim = extract_maintenance_features(df_sim)
            # Sample active failure points from the latter half of the window
            start_pos = len(feat_sim) // 2 if is_ano else 0
            indices = np.linspace(start_pos, len(feat_sim) - 1, 25, dtype=int)
            for idx in indices:
                x_records.append(feat_sim.iloc[idx].to_dict())
                y_binary.append(is_ano)
                y_subsystems.append(sub_name)

    x_df = pd.DataFrame(x_records)
    y_arr = np.array(y_binary, dtype=int)
    return x_df, y_arr, y_subsystems


def train_fault_classifier(
    data_dir: str | Path | None = None,
    models_dir: str | Path | None = None,
    n_estimators: int = 200,
) -> dict[str, Any]:
    """
    Train and serialize the binary early fault warning and subsystem classifiers.

    :param data_dir: Directory containing SCADA benchmark files.
    :param models_dir: Directory where trained artifacts will be saved.
    :param n_estimators: Number of boosting trees.

    :returns metrics: Dictionary containing training AUC and F1 scores.
    """
    target_models_dir = Path(models_dir) if models_dir else maintenance_models_dir()
    target_models_dir.mkdir(parents=True, exist_ok=True)

    x_df, y_arr, y_subsystems = load_event_dataset(data_dir=data_dir)
    feature_names = list(x_df.columns)

    # 1. Binary Early Warning Classifier
    bin_model = lgb.LGBMClassifier(
        n_estimators=n_estimators,
        learning_rate=0.04,
        max_depth=6,
        num_leaves=31,
        random_state=42,
        verbose=-1,
    )
    bin_model.fit(x_df, y_arr)

    probs = np.asarray(bin_model.predict_proba(x_df))[:, 1]
    preds = (probs >= 0.5).astype(int)
    auc = float(roc_auc_score(y_arr, probs))
    f1 = float(f1_score(y_arr, preds))

    # 2. Multi-class Subsystem Attribution Classifier
    subsys_model = lgb.LGBMClassifier(
        n_estimators=n_estimators,
        learning_rate=0.04,
        max_depth=6,
        num_leaves=31,
        random_state=42,
        verbose=-1,
    )
    subsys_model.fit(x_df, y_subsystems)

    joblib.dump(bin_model, target_models_dir / "fault_classifier.joblib")
    joblib.dump(subsys_model, target_models_dir / "subsystem_classifier.joblib")
    with open(target_models_dir / "fault_features.json", "w") as f:
        json.dump(feature_names, f, indent=2)

    return {
        "auc": round(auc, 4),
        "f1": round(f1, 4),
        "samples": len(x_df),
        "num_features": len(feature_names),
        "subsystems": list(subsys_model.classes_),
    }


__all__ = [
    "load_event_dataset",
    "resolve_maintenance_data_dir",
    "train_fault_classifier",
]
