"""
# Decision 3: which turbine is repaired first

A park with one crew and two to four failing turbines. The request carries the whole timeline:
the wind forecast for each of the next 7 days, each turbine's failure day, its 7-day output from
ML2, its health status and fault probability. The question: which turbine does the crew repair
first?

The label is not hand-written: it is the turbine on the earliest day of the plan the agent's
exact scheduler builds (`decision_model.scheduler`), whose objective the request states in
words. Two baselines: the ranking the agent uses today (`node_rank_and_match_crews`: CRITICAL,
then ML2 output, then the shorter lead time), and "most urgent first" (earliest failure day,
then higher output).

Run from `experiments/decision_model`:

    uv run python -I -m decision_model.priority run jeffan-4b
    uv run python -I -m decision_model.priority report

The following can be imported from this module:
- `PriorityScenario`
- `priority_scenarios`
- `rank_today`
- `most_urgent`
- `VARIANTS`
- `candidate_plans`
- `describe_plan`
- `build_priority_request`
- `score_priority`
- `main`
"""

import argparse
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import random
import statistics
import time
from typing import Any

from decision_model.metrics import argmax, roc_auc
from decision_model.scheduler import RepairRequest, schedule_repairs

OUT = Path(__file__).resolve().parent.parent / "out"
HORIZON = 7
ORDERS = 3

INSTRUCTIONS = (
    "One maintenance crew serves this park and repairs at most one turbine per day. A turbine "
    "with failure_day n must be repaired on day n - 1 at the latest (a turbine with "
    "failure_day 0 only today, day 0). wind_forecast gives the mean wind speed of each day; a "
    "turbine produces nothing on its repair day, so repairing on a calm day loses less output. "
    "projected_mwh_7d is the output ML2 expects from the turbine over the week. Plan one repair "
    "per day so that, in this order of importance: (1) as many turbines as possible are repaired "
    "before they fail; (2) if not all can be, the turbines left out are those with the lowest "
    "projected_mwh_7d; (3) the output lost on repair days, projected_mwh_7d times the wind speed "
    "of the repair day, is as small as possible, so high-output turbines get the calmest days; "
    "(4) earlier days win ties. Which turbine does the crew repair first, on the earliest day "
    "of that plan?"
)


@dataclass(frozen=True)
class PriorityScenario:
    """One park situation and its correct first turbine."""

    id: str
    category: str
    state: dict[str, Any]
    label: str
    today: str
    urgent: str


def _key(turbine_id: int) -> str:
    """Option key of a turbine."""
    return f"T{turbine_id}"


def rank_today(turbines: Sequence[Mapping[str, Any]]) -> str:
    """
    The turbine the agent puts first today: CRITICAL first, then higher ML2 output, then the
    shorter lead time (`node_rank_and_match_crews`).

    :param turbines: Turbine rows of the state.

    :returns option: Option key of the first turbine.
    """

    def key(t: Mapping[str, Any]) -> tuple[int, float, float]:
        critical = 1 if str(t["health_status"]).upper() == "CRITICAL" else 0
        return (critical, float(t["projected_mwh_7d"]), -float(t["failure_day"]))

    return _key(int(max(turbines, key=key)["turbine_id"]))


def most_urgent(turbines: Sequence[Mapping[str, Any]]) -> str:
    """
    Earliest failure day first, then higher output.

    :param turbines: Turbine rows of the state.

    :returns option: Option key of the first turbine.
    """
    first = min(turbines, key=lambda t: (t["failure_day"], -t["projected_mwh_7d"]))
    return _key(int(first["turbine_id"]))


def _plan_first(turbines: Sequence[Mapping[str, Any]], wind: Sequence[float]) -> str | None:
    """Turbine on the earliest day of the exact plan, or None when nothing can be scheduled."""
    requests = [
        RepairRequest(int(t["turbine_id"]), int(t["failure_day"]), float(t["projected_mwh_7d"]))
        for t in turbines
    ]
    plan = schedule_repairs(requests, wind, HORIZON)
    scheduled = [(day, tid) for tid, day in plan.items() if day is not None]
    return _key(min(scheduled)[1]) if scheduled else None


def priority_scenarios(n: int = 60, seed: int = 7) -> list[PriorityScenario]:
    """
    Random but reproducible park situations, labelled by the exact scheduler.

    Failure days are drawn from a short range in about half of the cases, so the crew cannot
    reach every turbine on its best day and the timeline matters.

    :param n: Number of scenarios.
    :param seed: Random seed.

    :returns scenarios: `n` scenarios whose plan repairs at least one turbine.
    """
    rng = random.Random(seed)
    out: list[PriorityScenario] = []
    while len(out) < n:
        count = rng.choice([2, 2, 3, 3, 4])
        tight = rng.random() < 0.5
        wind = [round(rng.uniform(3.0, 15.0), 1) for _ in range(HORIZON)]
        ids = rng.sample(range(10, 40), count)
        turbines = [
            {
                "turbine_id": tid,
                "health_status": "CRITICAL" if rng.random() < 0.3 else "WARNING",
                "failure_day": rng.randint(1, 3) if tight else rng.randint(1, 7),
                "fault_probability": round(rng.uniform(0.3, 0.95), 2),
                "projected_mwh_7d": round(rng.uniform(20.0, 200.0), 1),
            }
            for tid in ids
        ]
        label = _plan_first(turbines, wind)
        if label is None:
            continue
        today, urgent = rank_today(turbines), most_urgent(turbines)
        category = (
            f"azi_{'ok' if today == label else 'gresit'}"
            f"__urgent_{'ok' if urgent == label else 'gresit'}"
        )
        state = {
            "park_id": "wind_farm_a",
            "wind_forecast": [{"day": d, "wind_speed_m_s": w} for d, w in enumerate(wind)],
            "turbines": turbines,
        }
        out.append(
            PriorityScenario(f"pr-{len(out) + 1:02d}", category, state, label, today, urgent)
        )
    return out


FEATURE_INSTRUCTIONS = (
    "One maintenance crew serves this park and repairs at most one turbine per day. Each "
    "turbine must be repaired on or before its repair_by_day, or it fails. A turbine produces "
    "nothing on its repair day, so turbines with a high projected_mwh_7d should be repaired on "
    "calm days. Prefer an order that repairs every turbine in time; among those, the one that "
    "puts the highest-output turbines on the calmest days. Which turbine should the crew "
    "repair first?"
)

PLAN_INSTRUCTIONS = (
    "One maintenance crew serves this park and repairs at most one turbine per day. The options "
    "are complete repair plans, worked out from the forecast. Choose the plan that saves the "
    "most turbines; if several save the same number, choose the one with the smallest output "
    "lost on repair days. Which plan should the crew follow?"
)

VARIANTS = ("timeline", "features", "plans")


def _latest_day(failure_day: int) -> int:
    """Last day a turbine failing on `failure_day` can still be repaired."""
    return min(max(failure_day - 1, 0), HORIZON - 1)


def _wind(state: Mapping[str, Any]) -> list[float]:
    """The daily wind of a state, as a list from day 0."""
    return [float(d["wind_speed_m_s"]) for d in state["wind_forecast"]]


def _greedy(turbines: Sequence[Mapping[str, Any]], order: Sequence[int]) -> dict[int, int | None]:
    """Each turbine, in the given order, gets the earliest free day before its deadline."""
    by_id = {int(t["turbine_id"]): t for t in turbines}
    taken: set[int] = set()
    plan: dict[int, int | None] = {}
    for tid in order:
        free = [d for d in range(_latest_day(int(by_id[tid]["failure_day"])) + 1) if d not in taken]
        plan[tid] = free[0] if free else None
        if free:
            taken.add(free[0])
    return plan


def candidate_plans(state: Mapping[str, Any]) -> list[dict[int, int | None]]:
    """
    Distinct plans a dispatcher might weigh: the exact optimum, most urgent first, the agent's
    ranking of today and most distant first (both greedy on the earliest free day).

    :param state: A scenario state.

    :returns plans: Repair day per turbine id for each distinct plan, the optimum first.
    """
    turbines, wind = state["turbines"], _wind(state)
    requests = [
        RepairRequest(int(t["turbine_id"]), int(t["failure_day"]), float(t["projected_mwh_7d"]))
        for t in turbines
    ]
    urgent = sorted(turbines, key=lambda t: (t["failure_day"], -t["projected_mwh_7d"]))
    today = sorted(
        turbines,
        key=lambda t: (
            str(t["health_status"]).upper() == "CRITICAL",
            t["projected_mwh_7d"],
            -t["failure_day"],
        ),
        reverse=True,
    )
    distant = sorted(turbines, key=lambda t: (-t["failure_day"], -t["projected_mwh_7d"]))
    plans = [schedule_repairs(requests, wind, HORIZON)]
    for ordered in (urgent, today, distant):
        plans.append(_greedy(turbines, [int(t["turbine_id"]) for t in ordered]))
    unique: list[dict[int, int | None]] = []
    for plan in plans:
        if plan not in unique:
            unique.append(plan)
    return unique


def _plan_first_key(plan: Mapping[int, int | None]) -> str:
    """Option key of the turbine a plan repairs first."""
    scheduled = [(day, tid) for tid, day in plan.items() if day is not None]
    return _key(min(scheduled)[1]) if scheduled else ""


def describe_plan(plan: Mapping[int, int | None], state: Mapping[str, Any]) -> str:
    """
    One plan in words: the repair of each day, the turbines left to fail, how many are saved
    and the output lost on repair days (output times the day's wind speed).

    :param plan: Repair day per turbine id.
    :param state: The scenario state.

    :returns text: The option description.
    """
    wind = _wind(state)
    weight = {int(t["turbine_id"]): float(t["projected_mwh_7d"]) for t in state["turbines"]}
    days = sorted((day, tid) for tid, day in plan.items() if day is not None)
    lost = sum(weight[tid] * wind[day] for day, tid in days)
    failed = sorted(tid for tid, day in plan.items() if day is None)
    text = ", ".join(f"day {day} turbine {tid}" for day, tid in days)
    if failed:
        text += "; not repaired in time: " + ", ".join(f"turbine {t}" for t in failed)
    return f"{text}. Turbines saved: {len(days)} of {len(plan)}. Output lost: {lost:.0f}."


def _with_features(state: Mapping[str, Any]) -> dict[str, Any]:
    """The state with each turbine's deadline and calmest day before it worked out."""
    wind = _wind(state)
    turbines = []
    for t in state["turbines"]:
        last = _latest_day(int(t["failure_day"]))
        calm = min(range(last + 1), key=lambda d: (wind[d], d))
        turbines.append(
            {
                **t,
                "repair_by_day": last,
                "calmest_day_before_deadline": calm,
                "wind_on_that_day_m_s": wind[calm],
            }
        )
    return {**state, "turbines": turbines}


def build_priority_request(
    scenario: PriorityScenario, order_index: int = 0, variant: str = "timeline"
) -> tuple[dict[str, Any], dict[str, str]]:
    """
    The System One request for one prompt variant, options rotated by `order_index`.

    - `timeline`: the raw state; the model plans on its own (first test).
    - `features`: the code works out each turbine's deadline and calmest day before it.
    - `plans`: the code builds candidate plans; the model picks one.

    :param scenario: The situation.
    :param order_index: Rotation of the option order.
    :param variant: One of `VARIANTS`.

    :returns request: ({"state", "questions"}, option key -> first turbine's option key).
    :raises ValueError: For an unknown variant.
    """
    state: dict[str, Any] = scenario.state
    if variant == "plans":
        plans = candidate_plans(state)
        random.Random(scenario.id).shuffle(plans)
        names = [f"plan_{chr(ord('A') + i)}" for i in range(len(plans))]
        criteria = {n: describe_plan(p, state) for n, p in zip(names, plans)}
        first = {n: _plan_first_key(p) for n, p in zip(names, plans)}
        instructions = PLAN_INSTRUCTIONS
    elif variant in ("timeline", "features"):
        if variant == "features":
            state = _with_features(state)
        turbines = state["turbines"]
        names = [_key(int(t["turbine_id"])) for t in turbines]
        if variant == "features":
            criteria = {
                _key(int(t["turbine_id"])): (
                    f"Turbine {t['turbine_id']}: repair by day {t['repair_by_day']}, calmest day "
                    f"before that is day {t['calmest_day_before_deadline']} "
                    f"({t['wind_on_that_day_m_s']} m/s), {t['projected_mwh_7d']} MWh this week."
                )
                for t in turbines
            }
            instructions = FEATURE_INSTRUCTIONS
        else:
            criteria = {k: f"Repair turbine {k[1:]} first." for k in names}
            instructions = INSTRUCTIONS
        first = {k: k for k in names}
    else:
        raise ValueError(f"unknown variant {variant!r}")
    shift = order_index % len(names)
    names = names[shift:] + names[:shift]
    question = {
        "type": "choice",
        "instructions": instructions,
        "criteria": {n: criteria[n] for n in names},
    }
    return {"state": state, "questions": {"q": question}}, first


def _run_name(model: str, variant: str, seed: int) -> str:
    """File stem of one run; the first test (timeline, seed 7) keeps the bare model name."""
    return model if (variant, seed) == ("timeline", 7) else f"{model}__{variant}__s{seed}"


def run(model: str, device: str, out: Path, variant: str = "timeline", seed: int = 7) -> Path:
    """
    Send every scenario, in three option orders, to one model.

    :param model: Short name from `decision_model.adapters.MODELS`.
    :param device: Torch device.
    :param out: Output directory; writes `out/priority/<run name>.jsonl`.
    :param variant: Prompt variant, one of `VARIANTS`.
    :param seed: Scenario seed.

    :returns path: The file written. Rows hold the probability of each turbine being repaired
        first; for `plans`, a plan's probability goes to the turbine it repairs first, and the
        plan probabilities are kept as `plan_probabilities`.
    """
    from decision_model.adapters import load_adapter
    from decision_model.evaluate import _mps_gb, _sync

    folder = out / "priority"
    folder.mkdir(parents=True, exist_ok=True)
    name = _run_name(model, variant, seed)
    path = folder / f"{name}.jsonl"
    t0 = time.perf_counter()
    adapter = load_adapter(model, device)
    load_s = time.perf_counter() - t0
    scenarios = priority_scenarios(seed=seed)
    adapter.choice(build_priority_request(scenarios[0], 0, variant)[0])
    peak = _mps_gb(device)
    with path.open("w", encoding="utf-8") as fh:
        for s in scenarios:
            for order_index in range(ORDERS):
                request, first = build_priority_request(s, order_index, variant)
                t = time.perf_counter()
                raw = adapter.choice(request)
                _sync(device)
                latency = time.perf_counter() - t
                peak = max(peak, _mps_gb(device))
                turbine_probs = {_key(int(x["turbine_id"])): 0.0 for x in s.state["turbines"]}
                for option, p in raw.items():
                    if first[option]:
                        turbine_probs[first[option]] += p
                row: dict[str, Any] = {
                    "model": model,
                    "variant": variant,
                    "seed": seed,
                    "scenario": s.id,
                    "order_index": order_index,
                    "probabilities": turbine_probs,
                    "latency_s": round(latency, 4),
                }
                if variant == "plans":
                    row["plan_probabilities"] = raw
                    row["options"] = len(raw)
                fh.write(json.dumps(row) + "\n")
    meta = {"model": model, "load_s": round(load_s, 2), "mps_peak_gb": round(peak, 2)}
    (folder / f"{name}.meta.json").write_text(json.dumps(meta) + "\n", encoding="utf-8")
    print(json.dumps(meta), flush=True)
    return path


def score_priority(
    rows: Sequence[Mapping[str, Any]], scenarios: Mapping[str, PriorityScenario]
) -> dict[str, Any]:
    """
    Score one model on decision 3.

    :param rows: Its rows, every scenario in every option order.
    :param scenarios: Scenario by id.

    :returns metrics: Accuracy (first order), mean probability of the right turbine, ROC AUC
        pooled over every (scenario, turbine) pair, agreement over the option orders,
        accuracy by category and number of turbines, latency.
    """
    by_case: dict[str, dict[int, Mapping[str, float]]] = defaultdict(dict)
    for r in rows:
        by_case[r["scenario"]][int(r["order_index"])] = r["probabilities"]
    ids = sorted(by_case)
    first = {i: by_case[i][0] for i in ids}
    correct = {i: argmax(first[i]) == scenarios[i].label for i in ids}
    scores, positive = [], []
    for i in ids:
        for k, p in first[i].items():
            scores.append(p)
            positive.append(k == scenarios[i].label)
    by_cat: dict[str, list[bool]] = defaultdict(list)
    by_n: dict[int, list[bool]] = defaultdict(list)
    for i in ids:
        by_cat[scenarios[i].category].append(correct[i])
        by_n[len(scenarios[i].state["turbines"])].append(correct[i])
    latencies = sorted(float(r["latency_s"]) for r in rows)
    return {
        "n": len(ids),
        "accuracy": sum(correct.values()) / len(ids),
        "mean_p_correct": statistics.fmean(first[i][scenarios[i].label] for i in ids),
        "auc_pooled": roc_auc(scores, positive),
        "same_choice_all_orders": sum(
            len({argmax(p) for p in by_case[i].values()}) == 1 for i in ids
        )
        / len(ids),
        "by_category": {c: [sum(v), len(v)] for c, v in sorted(by_cat.items())},
        "by_turbines": {str(k): [sum(v), len(v)] for k, v in sorted(by_n.items())},
        "latency_median_ms": 1000 * statistics.median(latencies) if latencies else 0.0,
        "marks": {i: "buna" if correct[i] else "proasta" for i in ids},
    }


def _baseline_rows(scenarios: Sequence[PriorityScenario], pick: str) -> list[dict[str, Any]]:
    """A baseline as one-hot rows, for scoring like a model."""
    rows = []
    for s in scenarios:
        choice = s.today if pick == "today" else s.urgent
        keys = [_key(int(t["turbine_id"])) for t in s.state["turbines"]]
        for order_index in range(ORDERS):
            rows.append(
                {
                    "scenario": s.id,
                    "order_index": order_index,
                    "probabilities": {k: 1.0 if k == choice else 0.0 for k in keys},
                    "latency_s": 0.0,
                }
            )
    return rows


def _parse_name(stem: str) -> tuple[str, str, int]:
    """(model, variant, seed) from a run file stem."""
    if "__" not in stem:
        return stem, "timeline", 7
    model, variant, seed = stem.split("__")
    return model, variant, int(seed.lstrip("s"))


def report(out: Path) -> dict[str, Any]:
    """
    Score every run and both baselines on the scenario set of each seed; write
    `out/priority_metrics.json` and `out/priority_tables.md`.

    :param out: Output directory of `run`.

    :returns metrics: Keyed "name::variant::seed".
    """
    runs: dict[str, tuple[str, str, int, list[dict[str, Any]]]] = {}
    for path in sorted((out / "priority").glob("*.jsonl")):
        model, variant, seed = _parse_name(path.stem)
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        runs[path.stem] = (model, variant, seed, rows)
    seeds = sorted({seed for _, _, seed, _ in runs.values()} | {7})
    results: dict[str, Any] = {}
    lines = [
        "| cine alege | varianta | seed | acc | P medie pe turbina corecta | AUC | "
        "aceeasi alegere in 3 ordini | latenta ms |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for seed in seeds:
        scenarios = priority_scenarios(seed=seed)
        by_id = {s.id: s for s in scenarios}
        entries = [
            ("ordinea-de-azi", "-", score_priority(_baseline_rows(scenarios, "today"), by_id)),
            ("cel-mai-urgent", "-", score_priority(_baseline_rows(scenarios, "urgent"), by_id)),
        ]
        for model, variant, run_seed, rows in runs.values():
            if run_seed == seed:
                entries.append((model, variant, score_priority(rows, by_id)))
        for name, variant, m in entries:
            results[f"{name}::{variant}::{seed}"] = m
            lines.append(
                f"| {name} | {variant} | {seed} | {m['accuracy']:.3f} | "
                f"{m['mean_p_correct']:.3f} | {m['auc_pooled']:.3f} | "
                f"{m['same_choice_all_orders']:.3f} | {m['latency_median_ms']:.0f} |"
            )
    (out / "priority_metrics.json").write_text(json.dumps(results, indent=1) + "\n", "utf-8")
    (out / "priority_tables.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return results


def main(argv: list[str] | None = None) -> int:
    """
    Command line: `run <model> [--variant V] [--seed S]` or `report`.

    :param argv: Arguments; None reads `sys.argv`.

    :returns status: 0 on success.
    """
    parser = argparse.ArgumentParser(description="Decision 3: which turbine is repaired first.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("model")
    p_run.add_argument("--device", default="mps", choices=["mps", "cpu"])
    p_run.add_argument("--variant", default="timeline", choices=list(VARIANTS))
    p_run.add_argument("--seed", type=int, default=7)
    p_run.add_argument("--out", type=Path, default=OUT)
    p_rep = sub.add_parser("report")
    p_rep.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    if args.command == "run":
        run(args.model, args.device, args.out, args.variant, args.seed)
    else:
        report(args.out)
        print((args.out / "priority_tables.md").read_text(encoding="utf-8"))
    return 0


__all__ = [
    "PriorityScenario",
    "VARIANTS",
    "candidate_plans",
    "describe_plan",
    "priority_scenarios",
    "rank_today",
    "most_urgent",
    "build_priority_request",
    "score_priority",
    "main",
]

if __name__ == "__main__":
    raise SystemExit(main())
