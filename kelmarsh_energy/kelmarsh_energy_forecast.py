"""
Forecast the energy a Kelmarsh turbine exports over the next 10 slots (100 minutes).

Trains one model per invocation with the ml_framework time-series pipeline: the
series is `Energy Export (kWh)` per 10-minute slot, six turbines share one model,
a window holds `--lags` past slots, the test period starts at `--cutoff`. The models
are scored against persistence (the last reading repeated).

The framework has no local-file gatherer, so a small one lives here and takes the
place of the `dummy` entry in the registry for this process only; the package is
not touched. It reads `kelmarsh_10min.parquet`, written by `prepare_data.py`.

    python kelmarsh_energy_forecast.py --model xgboost --report report/
    python kelmarsh_energy_forecast.py --model lstm mamba2 linear --report report/

Run one model per process: on an Apple-silicon Mac, torch and XGBoost load two OpenMP runtimes.
"""

import argparse
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Optional

# The registry first: it fixes the order torch, XGBoost and LightGBM load in.
import ml_framework.base_models.configs  # noqa: F401  isort: skip
import numpy as np
import polars as pl

from ml_framework.base_models.configs import BaseModelsEnum
from ml_framework.data import configs as data_configs
from ml_framework.data.configs import DataGatherersEnum, DataSplittersEnum, DataTargetsEnum
from ml_framework.data.gatherers.abstract_gatherer import AbstractGatherer
from ml_framework.data.targets.window_framer import slots_duration
from ml_framework.forecasting_models.configs import ForecastingModelsEnum

ENTITY = "Turbine_ID"
TIME = "Timestamp"
VALUE = "Energy_kWh"
FREQUENCY = "10m"
HORIZON = 10

HERE = Path(__file__).resolve().parent

MODELS: dict[str, tuple[BaseModelsEnum, dict[str, Any]]] = {
    "linear": (BaseModelsEnum.LINEAR_REGRESSION, {}),
    "xgboost": (BaseModelsEnum.XGBOOST_REGRESSOR, {}),
    "lstm": (BaseModelsEnum.LSTM_REGRESSOR, {"device": "mps"}),
    "lstm_attention": (BaseModelsEnum.LSTM_ATTENTION_REGRESSOR, {"device": "mps"}),
    "mamba2": (BaseModelsEnum.MAMBA2_REGRESSOR, {"device": "mps"}),
}


class KelmarshGatherer(AbstractGatherer):
    """
    Read the compact Kelmarsh parquet: turbine, timestamp and the energy of each slot.
    """

    def __init__(self, path: str, start: str, end: str) -> None:
        """
        :param path: The parquet written by `prepare_data.py`.
        :param start: First moment kept, ISO date; slots before it are dropped.
        :param end: First moment not kept, ISO date.
        """
        self.path, self.start, self.end = path, start, end

    def resolved_params(self) -> dict[str, Any]:
        stat = Path(self.path).stat()
        return {"size": stat.st_size, "mtime": int(stat.st_mtime)}

    def gather(self) -> pl.DataFrame:
        """
        :returns df: `Turbine_ID`, `Timestamp`, `Energy_kWh`; a slot with no energy is left out.
        """
        return (
            pl.read_parquet(self.path, columns=[ENTITY, TIME, VALUE])
            .filter(
                (pl.col(TIME) >= pl.lit(self.start).str.to_datetime("%Y-%m-%d"))
                & (pl.col(TIME) < pl.lit(self.end).str.to_datetime("%Y-%m-%d"))
            )
            .drop_nulls(VALUE)
            .sort(ENTITY, TIME)
        )


# This process only: the package is not edited.
data_configs.DATA_GATHERERS[DataGatherersEnum.DUMMY] = KelmarshGatherer


def config(
    model: str,
    lags: int,
    start: str,
    cutoff: str,
    end: str,
    seed: Optional[int],
    data: Path = HERE / "kelmarsh_10min.parquet",
    overrides: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """
    Build the arguments of `run_time_series_training()`.

    :param model: A key of `MODELS`.
    :param lags: Slots of history per window.
    :param start: First moment of data.
    :param cutoff: First moment of the test period.
    :param end: First moment after the data.
    :param seed: Training seed, or None for the model's own.
    :param data: The parquet written by `prepare_data.py`.
    :param overrides: Parameters over the model's entry in `MODELS`, such as `device`.

    :returns config: The keyword arguments.
    """
    base_model, own = MODELS[model]
    chosen = {**own, **(overrides or {})}
    if seed is not None and model in ("xgboost", "lstm", "lstm_attention", "mamba2"):
        chosen["seed"] = seed
    return {
        "dataset_name": "kelmarsh_energy",
        "run_name": f"{model}-p{lags}",
        "cache_dataset": False,
        "gatherers": [
            {
                "gatherer": DataGatherersEnum.DUMMY,
                "params": {
                    "path": str(data),
                    "start": start,
                    "end": end,
                },
            },
            {
                "target": DataTargetsEnum.SLIDING_WINDOW,
                "params": {
                    "time_column": TIME,
                    "value_column": VALUE,
                    "entity_column": ENTITY,
                    "frequency": FREQUENCY,
                    "lags": lags,
                    "horizon": HORIZON,
                },
            },
        ],
        "split": {
            "splitter": DataSplittersEnum.CHRONOLOGICAL,
            "params": {
                "time_column": TIME,
                "entity_column": ENTITY,
                "cutoff": cutoff,
                "gap": slots_duration(FREQUENCY, lags),
            },
        },
        "model": {
            "type": ForecastingModelsEnum.AUTOREGRESSIVE,
            "params": {"base_model": base_model, "params": chosen},
        },
    }


def measure(forecasts: pl.DataFrame) -> dict[str, float]:
    """
    Score a forecasts table per step, for the model and for persistence.

    :param forecasts: One row per window and step: `step`, `actual`, `prediction`, `persistence`.

    :returns metrics: `MAE_h<k>`, `R2_h<k>`, `WAPE_h<k>`, their means over the steps, the
        same with `persistence_`, and `skill_MAE_mean` (one minus the MAE over persistence's).
    """
    metrics: dict[str, float] = {}
    steps = sorted(forecasts.get_column("step").unique().to_list())
    for source, prefix in (("prediction", ""), ("persistence", "persistence_")):
        for step in steps:
            rows = forecasts.filter(pl.col("step") == step)
            actual = rows.get_column("actual").to_numpy().astype(np.float64)
            error = rows.get_column(source).to_numpy().astype(np.float64) - actual
            metrics[f"{prefix}MAE_h{step}"] = float(np.abs(error).mean())
            spread = float(((actual - actual.mean()) ** 2).sum())
            metrics[f"{prefix}R2_h{step}"] = 1.0 - float((error**2).sum()) / spread
            metrics[f"{prefix}WAPE_h{step}"] = float(np.abs(error).sum() / np.abs(actual).sum())
        for name in ("MAE", "R2", "WAPE"):
            values = [metrics[f"{prefix}{name}_h{step}"] for step in steps]
            metrics[f"{prefix}{name}_mean"] = float(np.mean(values))
    metrics["skill_MAE_mean"] = 1.0 - metrics["MAE_mean"] / metrics["persistence_MAE_mean"]
    return metrics


def run_one(
    model: str,
    lags: int,
    start: str,
    cutoff: str,
    end: str,
    seed: Optional[int],
    folder: Path,
    data: Path = HERE / "kelmarsh_10min.parquet",
    overrides: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """
    Train and measure one model, write its forecasts and its summary.

    :param model: A key of `MODELS`.
    :param lags: Slots of history per window.
    :param start: First moment of data.
    :param cutoff: First moment of the test period.
    :param end: First moment after the data.
    :param seed: Training seed, or None.
    :param folder: Where the files go.
    :param data: The parquet written by `prepare_data.py`.
    :param overrides: Parameters over the model's entry in `MODELS`, such as `device`.

    :returns record: What was trained and how it scored.
    """
    from ml_framework.pipelines.time_series_regression.run_training import (
        run_time_series_training,
    )

    began = time.perf_counter()
    result = run_time_series_training(
        **config(model, lags, start, cutoff, end, seed, data, overrides)
    )
    seconds = time.perf_counter() - began
    name = f"{model}_p{lags}" + (f"_s{seed}" if seed is not None else "")
    forecasts = result["forecasts"]
    forecasts.write_parquet(folder / f"forecasts_{name}.parquet")
    base = result["model"].base_models[0]
    history = getattr(base, "loss_history", None)
    metrics = measure(forecasts)
    record = {
        "model": model,
        "lags": lags,
        "seed": seed,
        "overrides": dict(overrides or {}),
        "start": start,
        "cutoff": cutoff,
        "end": end,
        "run_id": result["run_id"],
        "tracking_uri": result["tracking_uri"],
        "epochs_run": len(history) if history else None,
        "best_epoch": getattr(base, "best_epoch", None),
        "seconds_total": seconds,
        "windows": int(forecasts.select(ENTITY, "origin").unique().height),
        "metrics": metrics,
        "entity_metrics": result["entity_metrics"],
    }
    (folder / f"summary_{name}.json").write_text(json.dumps(record, indent=2, default=str))
    print(
        f"{name}: windows {record['windows']}, MAE {metrics['MAE_mean']:.2f} kWh "
        f"(persistence {metrics['persistence_MAE_mean']:.2f}), skill {metrics['skill_MAE_mean']:+.3f}, "
        f"R2 {metrics['R2_mean']:.4f}, {seconds:.0f} s",
        flush=True,
    )
    return record


def main(argv: list[str]) -> int:
    """
    Train the chosen models, one after the other, in this process.

    :param argv: Command-line arguments, without the program name.

    :returns status: 0 on success.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", nargs="+", choices=sorted(MODELS), required=True)
    parser.add_argument("--lags", type=int, default=36)
    parser.add_argument("--start", default="2016-01-01", help="first date of data")
    parser.add_argument("--cutoff", default="2023-01-01", help="first date of the test period")
    parser.add_argument("--end", default="2025-01-01", help="first date after the data")
    parser.add_argument("--seed", type=int, default=15129)
    parser.add_argument("--report", type=Path, default=HERE / "report")
    parser.add_argument(
        "--data", type=Path, default=HERE / "kelmarsh_10min.parquet", help="the compact parquet"
    )
    parser.add_argument("--device", choices=["cpu", "mps", "cuda"], default=None)
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="a parameter over the model's own (int, float or text), e.g. batch_size=1024",
    )
    args = parser.parse_args(argv)
    args.report.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    overrides: dict[str, Any] = {}
    for item in args.param:
        name, _, text = item.partition("=")
        overrides[name] = json.loads(text) if text[:1] in "0123456789-." else text
    if args.device:
        overrides["device"] = args.device
    for model in args.model:
        networks = ("lstm", "lstm_attention", "mamba2")
        own = {k: v for k, v in overrides.items() if k != "device" or model in networks}
        run_one(
            model, args.lags, args.start, args.cutoff, args.end, args.seed, args.report,
            args.data, own,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
