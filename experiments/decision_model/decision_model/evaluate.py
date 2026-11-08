"""
# Evaluation

Two steps, run from `experiments/decision_model`:

    uv run python -I -m decision_model.evaluate run knowline-4b
    uv run python -I -m decision_model.evaluate report

`run` loads one model and sends every scenario of both decisions, in both prompt variants and
in the three option orders, writing one JSON line per decision to `out/runs/<model>.jsonl` and
the load time and peak memory to `out/runs/<model>.meta.json`. One model per process, so the
memory figures belong to that model alone.

`report` scores every run against the labels, adds the rule of today as the baseline, marks each
decision good or bad, and writes `out/metrics.json`, `out/decisions_marked.csv` and
`out/report_tables.md`.

The following can be imported from this module:
- `best_threshold`
- `category_table`
- `score_group`
- `rule_rows`
- `main`
"""

import argparse
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
import csv
import json
from pathlib import Path
import resource
import statistics
import time
from typing import Any

from decision_model.metrics import (
    argmax,
    brier,
    confusion,
    consistency,
    ece,
    macro_auc,
    paired_bootstrap,
    roc_auc,
)
from decision_model.requests import ORDERS, VARIANTS, build_request
from decision_model.scenarios import Scenario, all_scenarios

OUT = Path(__file__).resolve().parent.parent / "out"
CLASSES = {"ml2": ["da", "nu"], "channel": ["doar_email", "email_si_apel", "nimic"]}
CALL = "email_si_apel"
RULE = "regula-de-azi"


# ------------------------------------------------------------------ run
def _peak_rss_gb() -> float:
    """Peak resident memory of this process; macOS reports ru_maxrss in bytes."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9


def _mps_gb(device: str) -> float:
    """Memory the Metal driver holds for this process (0 off MPS)."""
    if device != "mps":
        return 0.0
    import torch

    return float(torch.mps.driver_allocated_memory()) / 1e9


def _sync(device: str) -> None:
    """Wait for queued GPU work, so a wall time covers the whole decision."""
    if device == "mps":
        import torch

        torch.mps.synchronize()


def run(model: str, device: str, out: Path, limit: int | None = None) -> Path:
    """
    Send every scenario to one model and record its probabilities and latency.

    :param model: Short name from `decision_model.adapters.MODELS`.
    :param device: Torch device ("mps" or "cpu").
    :param out: Output directory; files go to `out/runs/`.
    :param limit: Only the first `limit` scenarios of each decision (for a quick check).

    :returns path: The JSON-lines file written.
    """
    from decision_model.adapters import load_adapter

    scenarios = all_scenarios()
    if limit is not None:
        by: dict[str, list[Scenario]] = defaultdict(list)
        for s in scenarios:
            by[s.decision].append(s)
        scenarios = [s for group in by.values() for s in group[:limit]]
    runs = out / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    path = runs / f"{model}.jsonl"
    t0 = time.perf_counter()
    adapter = load_adapter(model, device)
    _sync(device)
    load_s = time.perf_counter() - t0
    mps_peak = _mps_gb(device)
    for s in scenarios[:2]:
        adapter.choice(build_request(s.decision, s.state))
    total = len(scenarios) * len(VARIANTS) * 3
    done = 0
    t_start = time.perf_counter()
    with path.open("w", encoding="utf-8") as fh:
        for variant in VARIANTS:
            for s in scenarios:
                for order_index in range(len(ORDERS[s.decision])):
                    request = build_request(s.decision, s.state, variant, order_index)
                    t = time.perf_counter()
                    probs = adapter.choice(request)
                    _sync(device)
                    latency = time.perf_counter() - t
                    mps_peak = max(mps_peak, _mps_gb(device))
                    row = {
                        "model": model,
                        "variant": variant,
                        "scenario": s.id,
                        "decision": s.decision,
                        "order_index": order_index,
                        "probabilities": probs,
                        "latency_s": round(latency, 4),
                    }
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    done += 1
                    if done % 100 == 0:
                        fh.flush()
                        rate = (time.perf_counter() - t_start) / done
                        print(f"{model}: {done}/{total}, {rate:.2f} s/decision", flush=True)
    meta = {
        "model": model,
        "device": device,
        "load_s": round(load_s, 2),
        "peak_rss_gb": round(_peak_rss_gb(), 2),
        "mps_peak_gb": round(mps_peak, 2),
        "decisions": done,
        "wall_s": round(time.perf_counter() - t_start, 1),
    }
    (runs / f"{model}.meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta), flush=True)
    return path


# ------------------------------------------------------------------ report
def rule_rows(scenarios: Iterable[Scenario]) -> list[dict[str, Any]]:
    """
    The rule of today as if it were a model: a probability of 1 for its option, in every
    variant and order, with no latency.

    :param scenarios: The scenarios to answer.

    :returns rows: Rows in the format `run` writes.
    """
    rows = []
    for variant in VARIANTS:
        for s in scenarios:
            for order_index in range(len(ORDERS[s.decision])):
                probs = {c: 1.0 if c == s.rule else 0.0 for c in CLASSES[s.decision]}
                rows.append(
                    {
                        "model": RULE,
                        "variant": variant,
                        "scenario": s.id,
                        "decision": s.decision,
                        "order_index": order_index,
                        "probabilities": probs,
                        "latency_s": 0.0,
                    }
                )
    return rows


def _accuracy(pairs: Sequence[tuple[str, str]]) -> float | None:
    """Share of (predicted, label) pairs that match; None for no pairs."""
    return sum(p == lab for p, lab in pairs) / len(pairs) if pairs else None


def best_threshold(scores: Sequence[float], positive: Sequence[bool]) -> float:
    """
    The cut on a score that classifies the given cases best (score >= cut means positive).
    Used to pick a threshold on the clear cases only and test it on the border cases.

    :param scores: One score per case.
    :param positive: Whether each case is positive.

    :returns cut: Midpoint between neighbouring scores; 0.5 when there are no cases.
    """
    if not scores:
        return 0.5
    values = sorted(set(scores))
    candidates = [values[0] - 1e-9] + [(a + b) / 2 for a, b in zip(values, values[1:])]
    candidates.append(values[-1] + 1e-9)

    def correct(cut: float) -> int:
        return sum((s >= cut) == p for s, p in zip(scores, positive))

    # Most correct; among ties, the cut closest to 0.5, the uncalibrated default.
    return max(candidates, key=lambda c: (correct(c), -abs(c - 0.5)))


def _is_critical(s: Scenario) -> bool:
    """The hard rule applies: health status CRITICAL, in any letter case."""
    return str(s.state.get("health_status", "")).upper() == "CRITICAL"


def score_group(
    rows: Sequence[Mapping[str, Any]], scenarios: Mapping[str, Scenario], decision: str
) -> dict[str, Any]:
    """
    Score one model in one prompt variant on one decision.

    :param rows: Its rows: every scenario of the decision in every option order.
    :param scenarios: Scenario by id.
    :param decision: "ml2" or "channel".

    :returns metrics: Accuracy (all, clear, border, where the label differs from the rule),
        ROC AUC, confusion matrix, calibration, consistency, hard-rule violations, latency.
    """
    classes = CLASSES[decision]
    by_case: dict[str, dict[int, Mapping[str, float]]] = defaultdict(dict)
    for r in rows:
        by_case[r["scenario"]][int(r["order_index"])] = r["probabilities"]
    ids = sorted(by_case)
    cases = [scenarios[i] for i in ids]
    first = [by_case[i][0] for i in ids]
    mean = [{c: statistics.fmean(p[c] for p in by_case[i].values()) for c in classes} for i in ids]
    labels = [s.label for s in cases]
    pred = [argmax(p) for p in first]
    pairs = list(zip(pred, labels))

    def subset(keep: Any) -> float | None:
        return _accuracy([pr for pr, s in zip(pairs, cases) if keep(s)])

    metrics: dict[str, Any] = {
        "n": len(ids),
        "accuracy": _accuracy(pairs),
        "accuracy_clear": subset(lambda s: s.kind == "clar"),
        "accuracy_border": subset(lambda s: s.kind == "granita"),
        "accuracy_label_not_rule": subset(lambda s: s.label != s.rule),
        "agrees_with_rule": _accuracy([(p, s.rule) for p, s in zip(pred, cases)]),
        "confusion": confusion(labels, pred, classes),
        "ece": ece([p[argmax(p)] for p in first], [p == lab for p, lab in pairs]),
        "brier": brier(first, labels, classes),
    }
    # The yes/no question that matters most for each decision: call ML2, place a phone call.
    positive = "da" if decision == "ml2" else CALL
    scores = [p[positive] for p in first]
    is_pos = [lab == positive for lab in labels]
    clear = [i for i, s in enumerate(cases) if s.kind == "clar"]
    border = [i for i, s in enumerate(cases) if s.kind == "granita"]
    cut = best_threshold([scores[i] for i in clear], [is_pos[i] for i in clear])
    metrics["positive"] = positive
    metrics["auc_positive"] = roc_auc(scores, is_pos)
    metrics["auc_positive_border"] = roc_auc(
        [scores[i] for i in border], [is_pos[i] for i in border]
    )
    metrics["threshold_from_clear"] = cut
    metrics["accuracy_positive_border_at_threshold"] = (
        sum((scores[i] >= cut) == is_pos[i] for i in border) / len(border) if border else None
    )
    metrics["accuracy_positive_border_argmax"] = (
        sum((pred[i] == positive) == is_pos[i] for i in border) / len(border) if border else None
    )
    metrics["vs_rule_95ci"] = paired_bootstrap(
        [p == lab for p, lab in pairs],
        [s.rule == s.label for s in cases],
        scores,
        [1.0 if s.rule == positive else 0.0 for s in cases],
        is_pos,
    )
    if decision == "ml2":
        metrics["auc"] = metrics["auc_positive"]
        metrics["auc_mean_orders"] = roc_auc(
            [p["da"] for p in mean], [lab == "da" for lab in labels]
        )
    else:
        auc, per = macro_auc(first, labels, classes)
        metrics["auc"] = auc
        metrics["auc_per_class"] = per
        metrics["auc_mean_orders"] = macro_auc(mean, labels, classes)[0]
        critical = [i for i, s in enumerate(cases) if _is_critical(s)]
        metrics["critical_cases"] = len(critical)
        metrics["hard_rule_violations"] = sum(pred[i] != CALL for i in critical)
        metrics["hard_rule_violations_any_order"] = sum(
            any(argmax(p) != CALL for p in by_case[ids[i]].values()) for i in critical
        )
        enforced = [CALL if _is_critical(s) else p for p, s in zip(pred, cases)]
        metrics["accuracy_with_hard_rule"] = _accuracy(list(zip(enforced, labels)))
    same, spread = consistency([list(by_case[i].values()) for i in ids])
    metrics["consistency_same_choice"] = same
    metrics["consistency_mean_max_dp"] = spread
    latencies = sorted(float(r["latency_s"]) for r in rows)
    metrics["latency_median_ms"] = 1000 * statistics.median(latencies)
    metrics["latency_p95_ms"] = (
        1000 * latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))]
    )
    return metrics


def _marks(
    rows: Sequence[Mapping[str, Any]], scenarios: Mapping[str, Scenario]
) -> list[dict[str, Any]]:
    """Each first-order decision marked good ("buna") or bad ("proasta") against the label."""
    out = []
    for r in rows:
        if int(r["order_index"]) != 0:
            continue
        s = scenarios[r["scenario"]]
        choice = argmax(r["probabilities"])
        out.append(
            {
                "model": r["model"],
                "variant": r["variant"],
                "scenario": s.id,
                "decision": s.decision,
                "kind": s.kind,
                "category": s.category,
                "choice": choice,
                "probability": round(float(r["probabilities"][choice]), 4),
                "label": s.label,
                "rule": s.rule,
                "mark": "buna" if choice == s.label else "proasta",
            }
        )
    return out


def _fmt(x: Any, digits: int = 3) -> str:
    """A table cell."""
    if x is None:
        return "-"
    if isinstance(x, float):
        return f"{x:.{digits}f}"
    return str(x)


def _tables(metrics: Mapping[str, Any], meta: Mapping[str, Any]) -> str:
    """Markdown tables of the main figures, one block per decision."""
    lines = []
    for decision in ("ml2", "channel"):
        lines.append(f"### {decision}\n")
        head = (
            "| model | varianta | acc | acc clar | acc granita | acc unde eticheta != regula | "
            "AUC | AUC medie ordini | ECE | Brier | aceeasi alegere in 3 ordini |"
        )
        extra = " incalcari regula dura | acc cu regula dura |" if decision == "channel" else ""
        lines.append(head + extra)
        lines.append("|" + "---|" * (head.count("|") - 1 + extra.count("|")))
        for key, m in sorted(metrics.items()):
            model, variant, dec = key.split("::")
            if dec != decision:
                continue
            cells = [
                model,
                variant,
                _fmt(m["accuracy"]),
                _fmt(m["accuracy_clear"]),
                _fmt(m["accuracy_border"]),
                _fmt(m["accuracy_label_not_rule"]),
                _fmt(m["auc"]),
                _fmt(m["auc_mean_orders"]),
                _fmt(m["ece"]),
                _fmt(m["brier"]),
                _fmt(m["consistency_same_choice"]),
            ]
            if decision == "channel":
                cells += [
                    f"{m['hard_rule_violations']}/{m['critical_cases']}",
                    _fmt(m["accuracy_with_hard_rule"]),
                ]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    lines.append("### intrebarea da/nu: ML2 = da, canal = apel\n")
    lines.append(
        "| model | varianta | decizie | AUC | AUC granita | prag din clar | "
        "acc granita la prag | acc granita argmax |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for key, m in sorted(metrics.items()):
        model, variant, dec = key.split("::")
        lines.append(
            f"| {model} | {variant} | {dec} | {_fmt(m['auc_positive'])} | "
            f"{_fmt(m['auc_positive_border'])} | {_fmt(m['threshold_from_clear'])} | "
            f"{_fmt(m['accuracy_positive_border_at_threshold'])} | "
            f"{_fmt(m['accuracy_positive_border_argmax'])} |"
        )
    lines.append("")
    lines.append("### resurse\n")
    lines.append(
        "| model | incarcare s | memorie Metal GB | RSS GB | latenta mediana ms | p95 ms |"
    )
    lines.append("|---|---|---|---|---|---|")
    for model, m in sorted(meta.items()):
        lines.append(
            f"| {model} | {_fmt(m.get('load_s'), 1)} | {_fmt(m.get('mps_peak_gb'), 2)} | "
            f"{_fmt(m.get('peak_rss_gb'), 2)} | {_fmt(m.get('latency_median_ms'), 0)} | "
            f"{_fmt(m.get('latency_p95_ms'), 0)} |"
        )
    return "\n".join(lines) + "\n"


def category_table(marks: Sequence[Mapping[str, Any]], variant: str) -> str:
    """
    Good decisions out of all, per scenario category and model, for one prompt variant.

    :param marks: Output of `_marks`.
    :param variant: Which prompt variant to show.

    :returns table: Markdown, one block per decision; rows are categories, columns models.
    """
    count: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0])
    kinds: dict[tuple[str, str], str] = {}
    for m in marks:
        if m["variant"] != variant:
            continue
        cell = count[(m["decision"], m["category"], m["model"])]
        cell[0] += m["mark"] == "buna"
        cell[1] += 1
        kinds[(m["decision"], m["category"])] = m["kind"]
    models = sorted({m["model"] for m in marks if m["variant"] == variant})
    lines = [f"### decizii bune pe categorii ({variant})\n"]
    for decision in ("ml2", "channel"):
        lines.append(f"{decision}:\n")
        lines.append("| categorie | tip | " + " | ".join(models) + " |")
        lines.append("|---|---|" + "---|" * len(models))
        cats = sorted(c for d, c in kinds if d == decision)
        cats.sort(key=lambda c: kinds[(decision, c)])
        for cat in cats:
            cells = []
            for model in models:
                good, total = count.get((decision, cat, model), [0, 0])
                cells.append(f"{good}/{total}" if total else "-")
            lines.append(f"| {cat} | {kinds[(decision, cat)]} | " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines) + "\n"


def report(out: Path) -> dict[str, Any]:
    """
    Score every run in `out/runs` and the rule of today.

    :param out: Output directory of `run`.

    :returns metrics: Keyed "model::variant::decision".
    """
    scenarios = {s.id: s for s in all_scenarios()}
    rows: list[dict[str, Any]] = rule_rows(scenarios.values())
    meta: dict[str, dict[str, Any]] = {}
    for path in sorted((out / "runs").glob("*.jsonl")):
        model_rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows += model_rows
        meta_path = path.with_suffix(".meta.json")
        info = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        lat = sorted(float(r["latency_s"]) for r in model_rows)
        if lat:
            info["latency_median_ms"] = 1000 * statistics.median(lat)
            info["latency_p95_ms"] = 1000 * lat[min(len(lat) - 1, int(0.95 * len(lat)))]
        meta[path.stem] = info
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[f"{r['model']}::{r['variant']}::{r['decision']}"].append(r)
    metrics = {key: score_group(g, scenarios, key.split("::")[2]) for key, g in groups.items()}
    (out / "metrics.json").write_text(
        json.dumps({"metrics": metrics, "meta": meta}, indent=1) + "\n", encoding="utf-8"
    )
    marks = _marks(rows, scenarios)
    with (out / "decisions_marked.csv").open("w", encoding="utf-8", newline="") as fh:
        columns = ["model", "variant", "scenario", "category", "choice", "probability"]
        columns += ["label", "rule", "mark"]
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(marks)
    tables = _tables(metrics, meta) + "\n" + category_table(marks, "cu_politica")
    (out / "report_tables.md").write_text(tables, encoding="utf-8")
    return metrics


def main(argv: list[str] | None = None) -> int:
    """
    Command line: `run <model>` or `report`.

    :param argv: Arguments; None reads `sys.argv`.

    :returns status: 0 on success.
    """
    parser = argparse.ArgumentParser(description="Evaluate local decision models.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run", help="Run one model on every scenario.")
    p_run.add_argument("model")
    p_run.add_argument("--device", default="mps", choices=["mps", "cpu"])
    p_run.add_argument("--limit", type=int, default=None)
    p_run.add_argument("--out", type=Path, default=OUT)
    p_rep = sub.add_parser("report", help="Score every run.")
    p_rep.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    if args.command == "run":
        run(args.model, args.device, args.out, args.limit)
    else:
        report(args.out)
        print((args.out / "report_tables.md").read_text(encoding="utf-8"))
    return 0


__all__ = ["best_threshold", "category_table", "score_group", "rule_rows", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
