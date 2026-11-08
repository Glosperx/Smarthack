from typing import Any

from decision_model.evaluate import RULE, _marks, rule_rows, score_group
from decision_model.scenarios import channel_scenarios, ml2_scenarios


def _rows(model: str, scenarios: list[Any], pick: Any, orders: int) -> list[dict[str, Any]]:
    rows = []
    for s in scenarios:
        for order_index in range(orders):
            rows.append(
                {
                    "model": model,
                    "variant": "fara_politica",
                    "scenario": s.id,
                    "decision": s.decision,
                    "order_index": order_index,
                    "probabilities": pick(s),
                    "latency_s": 0.01,
                }
            )
    return rows


def test_a_model_that_returns_the_labels_scores_perfectly() -> None:
    scenarios = ml2_scenarios()
    by_id = {s.id: s for s in scenarios}

    def pick(s: Any) -> dict[str, float]:
        return {"da": 0.9, "nu": 0.1} if s.label == "da" else {"da": 0.1, "nu": 0.9}

    m = score_group(_rows("m", scenarios, pick, 3), by_id, "ml2")

    assert m["accuracy"] == 1.0
    assert m["auc"] == 1.0
    assert m["accuracy_label_not_rule"] == 1.0
    assert m["consistency_same_choice"] == 1.0
    assert m["latency_median_ms"] == 10.0


def test_rule_baseline_misses_exactly_where_the_label_differs() -> None:
    scenarios = channel_scenarios()
    by_id = {s.id: s for s in scenarios}
    rows = [r for r in rule_rows(scenarios) if r["variant"] == "fara_politica"]

    m = score_group(rows, by_id, "channel")

    differ = sum(s.label != s.rule for s in scenarios)
    assert m["accuracy"] == (len(scenarios) - differ) / len(scenarios)
    assert m["accuracy_label_not_rule"] == 0.0
    assert m["hard_rule_violations"] == 0
    assert m["agrees_with_rule"] == 1.0


def test_hard_rule_violations_and_enforcement() -> None:
    scenarios = channel_scenarios()
    by_id = {s.id: s for s in scenarios}

    def never_call(s: Any) -> dict[str, float]:
        return {"doar_email": 0.8, "email_si_apel": 0.1, "nimic": 0.1}

    m = score_group(_rows("m", scenarios, never_call, 3), by_id, "channel")

    assert m["hard_rule_violations"] == m["critical_cases"] > 0
    assert m["accuracy_with_hard_rule"] > m["accuracy"]


def test_marks_good_and_bad_on_the_first_order_only() -> None:
    scenarios = ml2_scenarios()[:2]
    by_id = {s.id: s for s in scenarios}
    rows = _rows(RULE, scenarios, lambda s: {"da": 0.2, "nu": 0.8}, 3)

    marks = _marks(rows, by_id)

    assert len(marks) == 2
    assert {m["mark"] for m in marks} <= {"buna", "proasta"}
    assert all((m["mark"] == "buna") == (m["choice"] == m["label"]) for m in marks)


def test_best_threshold_separates_and_prefers_cuts_near_one_half() -> None:
    from decision_model.evaluate import best_threshold

    assert best_threshold([0.1, 0.2, 0.8, 0.9], [False, False, True, True]) == 0.5
    assert best_threshold([0.01, 0.02, 0.04, 0.05], [False, False, True, True]) == 0.03
    assert best_threshold([], []) == 0.5


def test_category_table_counts_good_decisions_per_model() -> None:
    from decision_model.evaluate import category_table

    marks = [
        {
            "model": "a",
            "variant": "v",
            "decision": "ml2",
            "category": "x",
            "kind": "clar",
            "mark": "buna",
        },
        {
            "model": "a",
            "variant": "v",
            "decision": "ml2",
            "category": "x",
            "kind": "clar",
            "mark": "proasta",
        },
        {
            "model": "b",
            "variant": "w",
            "decision": "ml2",
            "category": "x",
            "kind": "clar",
            "mark": "buna",
        },
    ]

    table = category_table(marks, "v")

    assert "| x | clar | 1/2 |" in table
    assert "| b" not in table
