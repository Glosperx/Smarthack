"""
Compare the models trained by `kelmarsh_energy_forecast.py`, Mamba2 against each of the others.

Reads `forecasts_*.parquet` and `summary_*.json` from a report folder and writes
`comparison.md` and `comparison.png` beside them. Every model must have forecast the same
test windows. Differences are paired by window; their intervals come from a block
bootstrap, a block being one turbine's run of consecutive origins (windows a slot apart
share all but one reading, so they are not independent).

    python -I compare_models.py report_smoke/
"""

import json
from pathlib import Path
import sys
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import polars as pl  # noqa: E402

CANDIDATE = "mamba2"
ORDER = ["mamba2", "lstm", "lstm_attention", "xgboost", "linear"]
LABELS = {
    "mamba2": "Mamba2",
    "lstm": "LSTM",
    "lstm_attention": "LSTM + attention",
    "xgboost": "XGBoost",
    "linear": "Linear",
}
# Categorical slots 1-5 of the reference palette, in order; persistence is neutral grey.
COLORS = {
    "mamba2": "#2a78d6",
    "lstm": "#eb6834",
    "lstm_attention": "#1baf7a",
    "xgboost": "#eda100",
    "linear": "#e87ba4",
    "persistence": "#8a8984",
}
DRAWS, SEED = 2000, 15129


def load(folder: Path) -> tuple[dict[str, pl.DataFrame], dict[str, dict[str, Any]]]:
    """
    Read every model's forecasts and summary, sorted the same way.

    :param folder: The report folder.

    :returns frames, summaries: Model name to its table and to its summary.

    :raises ValueError: If two models did not forecast the same windows.
    """
    frames: dict[str, pl.DataFrame] = {}
    summaries: dict[str, dict[str, Any]] = {}
    for model in ORDER:
        forecasts = list(folder.glob(f"forecasts_{model}_p*.parquet"))
        if forecasts:
            frames[model] = pl.read_parquet(forecasts[0]).sort("Turbine_ID", "origin", "step")
            summaries[model] = json.loads(next(folder.glob(f"summary_{model}_p*.json")).read_text())
    keys = frames[CANDIDATE].select("Turbine_ID", "origin", "step")
    for model, frame in frames.items():
        if not frame.select("Turbine_ID", "origin", "step").equals(keys):
            raise ValueError(f"{model} forecast other windows than {CANDIDATE}.")
    return frames, summaries


def window_errors(frame: pl.DataFrame, column: str, steps: int) -> np.ndarray:
    """
    Reduce a table to the mean absolute error of each window over its steps.

    :param frame: Sorted by turbine, origin and step, every window holding all steps.
    :param column: `prediction` or `persistence`.
    :param steps: Steps per window.

    :returns errors: One value per window, in table order.
    """
    actual = frame.get_column("actual").to_numpy().reshape(-1, steps)
    guess = frame.get_column(column).to_numpy().reshape(-1, steps)
    return np.abs(guess - actual).mean(axis=1)


def blocks(frame: pl.DataFrame, steps: int) -> np.ndarray:
    """
    Number the runs of one turbine's consecutive origins.

    :param frame: Sorted table.
    :param steps: Steps per window.

    :returns blocks: One block number per window.
    """
    keys = frame.gather_every(steps).select("Turbine_ID", "origin")
    turbine, origin = keys.get_column("Turbine_ID"), keys.get_column("origin")
    new = (turbine != turbine.shift(1)) | (origin != origin.shift(1).dt.offset_by("10m"))
    return new.fill_null(True).cast(pl.Int64).cum_sum().to_numpy() - 1


def paired(improvement: np.ndarray, block: np.ndarray) -> dict[str, Any]:
    """
    Mean of a per-window difference with a block-bootstrap 95% interval.

    :param improvement: Rival's error minus Mamba2's, per window.
    :param block: Each window's block.

    :returns result: `mean`, `low`, `high`, `share_above` (resamples above 0), `blocks`.
    """
    _, inverse = np.unique(block, return_inverse=True)
    sums, sizes = np.bincount(inverse, weights=improvement), np.bincount(inverse)
    picks = np.random.default_rng(SEED).integers(0, sums.size, size=(DRAWS, sums.size))
    means = sums[picks].sum(axis=1) / sizes[picks].sum(axis=1)
    low, high = np.percentile(means, [2.5, 97.5])
    return {
        "mean": float(improvement.mean()),
        "low": float(low),
        "high": float(high),
        "share_above": float((means > 0).mean()),
        "blocks": int(sums.size),
    }


def per_step(frame: pl.DataFrame, column: str) -> dict[int, float]:
    """
    Mean absolute error at each step.

    :param frame: A forecasts table.
    :param column: `prediction` or `persistence`.

    :returns mae: Step to MAE.
    """
    return {
        step: float(
            np.abs(rows.get_column(column).to_numpy() - rows.get_column("actual").to_numpy()).mean()
        )
        for (step,), rows in frame.group_by("step", maintain_order=True)
    }


def overall(frame: pl.DataFrame, column: str) -> dict[str, float]:
    """
    MSE, RMSE, MAE and R² over every row of a table.

    :param frame: A forecasts table.
    :param column: `prediction` or `persistence`.

    :returns metrics: The four numbers.
    """
    actual = frame.get_column("actual").to_numpy()
    error = frame.get_column(column).to_numpy() - actual
    mse = float((error**2).mean())
    return {
        "MSE": mse,
        "RMSE": mse**0.5,
        "MAE": float(np.abs(error).mean()),
        "R2": 1.0 - float((error**2).sum() / ((actual - actual.mean()) ** 2).sum()),
    }


def draw(steps: list[int], mae: dict[str, dict[int, float]], path: Path) -> None:
    """
    Plot MAE per step, and each rival's MAE minus Mamba2's.

    :param steps: The steps, in order.
    :param mae: Name (a model or `persistence`) to MAE per step.
    :param path: Where to write the PNG.

    :returns: None.
    """
    ink, muted = "#0b0b0b", "#52514e"
    fig, (left, right) = plt.subplots(1, 2, figsize=(12.5, 4.8), facecolor="#fcfcfb")
    minutes = [10 * s for s in steps]
    for model in ["persistence", *ORDER]:
        values = [mae[model][s] for s in steps]
        style = {"color": COLORS[model], "lw": 2.4 if model == CANDIDATE else 1.8}
        if model == "persistence":
            style.update(ls="--", lw=1.6)
        left.plot(minutes, values, label=LABELS.get(model, "Persistence"), **style)
    left.set_title("MAE per forecast step (kWh per 10 min)", loc="left", color=ink, fontsize=11)
    left.set_xlabel("minutes ahead", color=muted)
    left.set_ylabel("MAE, kWh", color=muted)
    for model in ORDER[1:]:
        values = [mae[model][s] - mae[CANDIDATE][s] for s in steps]
        right.plot(minutes, values, label=LABELS[model], color=COLORS[model], lw=1.8)
    right.axhline(0, color=COLORS[CANDIDATE], lw=2.4, label="Mamba2 (zero line)")
    right.set_title("MAE minus Mamba2's (below 0: better than Mamba2)", loc="left", color=ink, fontsize=11)
    right.set_xlabel("minutes ahead", color=muted)
    right.set_ylabel("kWh", color=muted)
    for ax in (left, right):
        ax.set_facecolor("#fcfcfb")
        ax.grid(color="#e4e3df", lw=0.7)
        ax.set_axisbelow(True)
        ax.tick_params(colors=muted)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color("#c9c8c3")
        ax.set_xticks(minutes)
        ax.legend(frameon=False, fontsize=9, labelcolor=muted)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=fig.get_facecolor())


def main(folder: Path) -> None:
    """
    Write the comparison table and plot of a report folder.

    :param folder: The report folder.

    :returns: None.
    """
    frames, summaries = load(folder)
    models = [m for m in ORDER if m in frames]
    steps = sorted(frames[CANDIDATE].get_column("step").unique().to_list())
    n = len(steps)
    block = blocks(frames[CANDIDATE], n)
    errors = {m: window_errors(frames[m], "prediction", n) for m in models}
    persistence = window_errors(frames[CANDIDATE], "persistence", n)
    windows = errors[CANDIDATE].size
    rng = float(frames[CANDIDATE].get_column("actual").max())
    scores = {m: overall(frames[m], "prediction") for m in models}
    scores["persistence"] = overall(frames[CANDIDATE], "persistence")
    mae = {m: per_step(frames[m], "prediction") for m in models}
    mae["persistence"] = per_step(frames[CANDIDATE], "persistence")

    lines = [
        "# Mamba2 against the other models",
        "",
        f"Kelmarsh, energy per 10-minute slot (kWh), {n} steps ahead, {windows:,} test windows "
        f"({frames[CANDIDATE].get_column('origin').min():%Y-%m-%d} to "
        f"{frames[CANDIDATE].get_column('origin').max():%Y-%m-%d}), one seed. "
        f"Scaled columns divide by the largest actual value, {rng:.0f} kWh "
        "(MAE by it, MSE by its square).",
        "",
        "## All steps",
        "",
        "| model | MSE | RMSE | MAE | R² | MSE scaled | MAE scaled | skill | epochs (best) | seconds |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    p = scores["persistence"]
    lines.append(
        f"| persistence | {p['MSE']:.1f} | {p['RMSE']:.2f} | {p['MAE']:.2f} | {p['R2']:.4f} | "
        f"{p['MSE'] / rng**2:.5f} | {p['MAE'] / rng:.4f} | 0 | – | – |"
    )
    for m in models:
        s, r = scores[m], summaries[m]
        epochs = f"{r['epochs_run']} ({r['best_epoch']})" if r["epochs_run"] else "–"
        lines.append(
            f"| {LABELS[m]} | {s['MSE']:.1f} | {s['RMSE']:.2f} | {s['MAE']:.2f} | {s['R2']:.4f} | "
            f"{s['MSE'] / rng**2:.5f} | {s['MAE'] / rng:.4f} | {1 - s['MAE'] / p['MAE']:+.3f} | "
            f"{epochs} | {r['seconds_total']:.0f} |"
        )

    lines += [
        "",
        "## Mamba2 against each model, window by window",
        "",
        "Difference of the mean absolute error of a window over its steps, the other model's "
        "minus Mamba2's: positive means Mamba2 errs less. Interval: block bootstrap, "
        f"{DRAWS} resamples.",
        "",
        "| other model | difference, kWh | 95% interval | resamples above 0 | blocks | verdict |",
        "|---|---|---|---|---|---|",
    ]
    for m in models[1:]:
        c = paired(errors[m] - errors[CANDIDATE], block)
        verdict = (
            "Mamba2 better" if c["low"] > 0 else "Mamba2 worse" if c["high"] < 0 else "no clear difference"
        )
        lines.append(
            f"| {LABELS[m]} | {c['mean']:+.3f} | [{c['low']:+.3f}, {c['high']:+.3f}] | "
            f"{c['share_above']:.3f} | {c['blocks']} | {verdict} |"
        )

    lines += ["", "## MAE per step (kWh)", ""]
    lines.append("| step | persistence | " + " | ".join(LABELS[m] for m in models) + " |")
    lines.append("|---|---|" + "---|" * len(models))
    for s in steps:
        cells = " | ".join(f"{mae[m][s]:.2f}" for m in models)
        lines.append(f"| {10 * s} min | {mae['persistence'][s]:.2f} | {cells} |")

    lines += ["", "## MAE per turbine (kWh, all steps)", ""]
    lines.append("| turbine | windows | persistence | " + " | ".join(LABELS[m] for m in models) + " |")
    lines.append("|---|---|---|" + "---|" * len(models))
    turbines = frames[CANDIDATE].gather_every(n).get_column("Turbine_ID").to_numpy()
    for turbine in sorted(set(turbines)):
        mask = turbines == turbine
        cells = " | ".join(f"{errors[m][mask].mean():.2f}" for m in models)
        lines.append(f"| {turbine} | {int(mask.sum()):,} | {persistence[mask].mean():.2f} | {cells} |")

    (folder / "comparison.md").write_text("\n".join(lines) + "\n")
    draw(steps, mae, folder / "comparison.png")
    print("\n".join(lines))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
