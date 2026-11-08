from typing import Any

from decision_model.priority import (
    build_priority_request,
    candidate_plans,
    describe_plan,
    most_urgent,
    priority_scenarios,
    rank_today,
    score_priority,
)
from decision_model.scheduler import RepairRequest, schedule_repairs


def _t(tid: int, day: int, mwh: float, status: str = "WARNING") -> dict[str, Any]:
    return {
        "turbine_id": tid,
        "health_status": status,
        "failure_day": day,
        "fault_probability": 0.5,
        "projected_mwh_7d": mwh,
    }


def test_scheduler_sends_the_big_turbine_to_the_calm_day() -> None:
    plan = schedule_repairs(
        [RepairRequest(1, 5, 100.0), RepairRequest(2, 5, 10.0)], [9.0, 9.0, 3.0, 9.0, 9.0]
    )

    assert plan == {1: 2, 2: 0}


def test_scheduler_saves_the_most_turbines_first() -> None:
    plan = schedule_repairs([RepairRequest(1, 1, 100.0), RepairRequest(2, 2, 10.0)], [9.0, 1.0])

    assert plan == {1: 0, 2: 1}


def test_scheduler_gives_up_the_smaller_turbine_when_both_fail_today() -> None:
    plan = schedule_repairs([RepairRequest(1, 0, 10.0), RepairRequest(2, 0, 100.0)], [5.0])

    assert plan == {2: 0, 1: None}


def test_baselines() -> None:
    turbines = [_t(1, 1, 50.0), _t(2, 4, 150.0), _t(3, 6, 90.0, "CRITICAL")]

    assert rank_today(turbines) == "T3"
    assert most_urgent(turbines) == "T1"


def test_scenarios_are_reproducible_and_labelled_by_the_plan() -> None:
    first = priority_scenarios(10)
    again = priority_scenarios(10)

    assert first == again
    assert len(first) == 10
    for s in first:
        keys = {f"T{t['turbine_id']}" for t in s.state["turbines"]}
        assert s.label in keys
        assert len(s.state["wind_forecast"]) == 7


def test_request_rotates_the_options_but_keeps_the_state() -> None:
    s = priority_scenarios(1)[0]

    a = build_priority_request(s, 0)[0]["questions"]["q"]["criteria"]
    b = build_priority_request(s, 1)[0]["questions"]["q"]["criteria"]

    assert set(a) == set(b)
    assert list(a)[1:] + list(a)[:1] == list(b)


def test_score_priority_counts_the_right_turbine() -> None:
    scenarios = priority_scenarios(4)
    by_id = {s.id: s for s in scenarios}
    rows = []
    for s in scenarios:
        keys = [f"T{t['turbine_id']}" for t in s.state["turbines"]]
        probs = {k: (0.9 if k == s.label else 0.1 / (len(keys) - 1)) for k in keys}
        rows += [
            {"scenario": s.id, "order_index": o, "probabilities": probs, "latency_s": 0.1}
            for o in range(3)
        ]

    m = score_priority(rows, by_id)

    assert m["accuracy"] == 1.0
    assert m["auc_pooled"] == 1.0
    assert m["same_choice_all_orders"] == 1.0
    assert set(m["marks"].values()) == {"buna"}


def test_plans_variant_offers_the_optimum_among_distinct_plans() -> None:
    for s in priority_scenarios(15):
        plans = candidate_plans(s.state)
        assert len({tuple(sorted(p.items())) for p in plans}) == len(plans)
        request, first = build_priority_request(s, 0, "plans")
        options = request["questions"]["q"]["criteria"]
        assert set(options) == set(first)
        assert s.label in first.values()


def test_describe_plan_counts_saved_turbines_and_lost_output() -> None:
    state = {
        "wind_forecast": [{"day": 0, "wind_speed_m_s": 2.0}, {"day": 1, "wind_speed_m_s": 5.0}],
        "turbines": [_t(1, 1, 10.0), _t(2, 2, 20.0)],
    }

    text = describe_plan({1: 0, 2: 1}, state)

    assert text == "day 0 turbine 1, day 1 turbine 2. Turbines saved: 2 of 2. Output lost: 120."


def test_features_variant_adds_deadline_and_calmest_day() -> None:
    s = priority_scenarios(1)[0]

    request, first = build_priority_request(s, 0, "features")

    turbine = request["state"]["turbines"][0]
    assert turbine["repair_by_day"] == max(turbine["failure_day"] - 1, 0)
    assert turbine["calmest_day_before_deadline"] <= turbine["repair_by_day"]
    assert all(k == v for k, v in first.items())
