"""
Unit tests for model training and benchmark helpers.
"""

from pathlib import Path

import numpy as np
import pytest

from smarthack.wind.features import RAW_WEATHER_COLUMNS
from smarthack.wind.training import evaluate_predictions, load_dataset, train_and_benchmark
from tests.conftest import skip_module_without_extra

skip_module_without_extra("wind")


def test_evaluate_predictions_computes_standard_metrics() -> None:
    """evaluate_predictions computes expected RMSE, MAE, and R2."""
    y_true = np.array([0.1, 0.5, 0.8, 1.0])
    y_pred = np.array([0.15, 0.45, 0.85, 0.95])

    metrics = evaluate_predictions(y_true, y_pred, name="TestModel")
    assert metrics["Model"] == "TestModel"
    assert "RMSE" in metrics
    assert "MAE" in metrics
    assert "R2" in metrics
    assert metrics["RMSE"] > 0.0
    assert metrics["R2"] > 0.9


def test_load_dataset_missing_file_raises_error(tmp_path: Path) -> None:
    """load_dataset raises FileNotFoundError if any location CSV is missing."""
    with pytest.raises(FileNotFoundError, match="Missing required dataset"):
        load_dataset(tmp_path)


def test_load_dataset_reads_four_locations() -> None:
    """load_dataset ingests all 4 location files into a unified dataframe."""
    repo_data = Path(__file__).resolve().parent.parent.parent.parent / "data" / "wind"
    if not (repo_data / "Location1.csv").is_file():
        pytest.skip("Training data CSV files not present in data/wind directory")

    df = load_dataset()
    assert "location_id" in df.columns
    assert set(df["location_id"].unique()) == {1, 2, 3, 4}
    assert "Time" in df.columns
    assert len(df) > 1000


def test_train_and_benchmark_fast_pipeline(tmp_path: Path) -> None:
    """train_and_benchmark executes end-to-end on synthetic data with fast_mode."""
    import pandas as pd

    data_dir = tmp_path / "data"
    models_dir = tmp_path / "models"
    data_dir.mkdir()

    dates = pd.date_range("2020-12-30", periods=20, freq="6h")
    for loc_id in range(1, 5):
        df_dummy = pd.DataFrame(
            {
                "Time": dates,
                "Power": np.linspace(0.1, 0.9, 20),
                **{col: np.linspace(10.0, 50.0, 20) for col in RAW_WEATHER_COLUMNS},
            }
        )
        df_dummy.to_csv(data_dir / f"Location{loc_id}.csv", index=False)

    results = train_and_benchmark(
        data_dir=data_dir,
        models_dir=models_dir,
        train_until="2021-01-01",
        fast_mode=True,
    )

    assert "leaderboard" in results
    assert len(results["leaderboard"]) == 6
    assert (models_dir / "xgboost_wind_power.json").is_file()
    assert (models_dir / "lightgbm_wind_power.joblib").is_file()
    assert (models_dir / "catboost_wind_power.cbm").is_file()
    assert (models_dir / "feature_columns.json").is_file()
    assert (models_dir / "benchmark_results.csv").is_file()
