"""
# Unit tests for repair plans

Covers the scheduler requests, the candidate plans, how a plan is counted and described, the order
it implies and the schedule the graph reads.
"""

from datetime import date
from typing import Any

from smarthack.services.agent.repair_plans import (
    build_requests,
    candidate_plans,
    describe_plan,
    has_output_estimate,
    plan_from_slots,
    plan_order,
    plan_output_lost,
    plan_saved,
    schedule_entries,
)
from smarthack.services.agent.repair_scheduler import RepairRequest, fill_wind, schedule_repairs

WIND = [8.0, 3.0, 9.0, 5.0, 2.0, 7.0, 6.0]


def _item(turbine_id: int, days: float | None, mwh: float | None = None) -> dict[str, Any]:
    """
    Build a failing triage item.

    :param turbine_id: Turbine identifier.
    :param days: Predicted days to failure, or None.
    :param mwh: Projected output, or None when the power model did not run.

    :returns item: Triage dictionary.
    """
    item: dict[str, Any] = {"turbine_id": turbine_id, "days_to_failure": days}
    if mwh is not None:
        item["projected_mwh_7d"] = mwh
    return item


def test_requests_use_the_failure_day_and_the_output() -> None:
    """A request carries the whole failure day and the projected output as its weight."""
    requests = build_requests([_item(1, 4.6, 10.0), _item(2, 0.8, 40.0)])

    assert requests == [RepairRequest(1, 4, 10.0), RepairRequest(2, 0, 40.0)]


def test_a_turbine_with_no_failure_day_may_be_repaired_any_day_of_the_forecast() -> None:
    """Missing, None and 8 days or more all mean the end of the forecast, not a made-up day."""
    requests = build_requests([_item(1, None, 5.0), _item(2, 8.0, 5.0), _item(3, 10.2, 5.0)])

    assert [r.failure_day for r in requests] == [7, 7, 7]


def test_without_an_output_estimate_every_turbine_weighs_the_same() -> None:
    """No power model run, or zero everywhere: the wind forecast alone decides the days."""
    no_estimate = [_item(1, 4.0), _item(2, 4.0)]
    zero = [_item(1, 4.0, 0.0), _item(2, 4.0, 0.0)]

    assert [r.weight for r in build_requests(no_estimate)] == [1.0, 1.0]
    assert [r.weight for r in build_requests(zero)] == [1.0, 1.0]
    assert has_output_estimate(no_estimate) is False
    assert has_output_estimate(zero) is False
    assert has_output_estimate([_item(1, 4.0, 3.0)]) is True


def test_the_optimum_comes_first_and_equals_the_scheduler() -> None:
    """The first candidate is exactly what `schedule_repairs` finds."""
    requests = [RepairRequest(1, 4, 10.0), RepairRequest(2, 4, 40.0)]

    plans = candidate_plans(requests, WIND)

    assert plans[0] == plan_from_slots(schedule_repairs(requests, WIND))
    assert plans[0] == {2: 1, 1: 3}


def test_identical_plans_are_kept_once() -> None:
    """Here all three greedy orders agree, so only one alternative remains."""
    requests = [RepairRequest(1, 4, 10.0), RepairRequest(2, 4, 40.0)]

    assert candidate_plans(requests, WIND) == [{2: 1, 1: 3}, {2: 0, 1: 1}]


def test_one_turbine_has_only_one_plan() -> None:
    """Greedy and optimum agree on a lone turbine only when the earliest day is also the calmest."""
    plans = candidate_plans([RepairRequest(1, 4, 10.0)], [1.0, 5.0, 6.0, 7.0, 8.0, 9.0, 9.0])

    assert plans == [{1: 0}]


def test_alternatives_order_turbines_by_urgency_output_and_distance() -> None:
    """Three turbines with different deadlines and outputs give distinct greedy plans."""
    requests = [RepairRequest(1, 2, 10.0), RepairRequest(2, 5, 90.0), RepairRequest(3, 3, 50.0)]

    plans = candidate_plans(requests, WIND)

    assert plans[0] == plan_from_slots(schedule_repairs(requests, WIND))
    assert {1: 0, 3: 1, 2: 2} in plans
    assert {2: 0, 3: 1, 1: None} in plans
    assert len({tuple(sorted(p.items())) for p in plans}) == len(plans)


def test_saved_and_output_lost_count_the_plan() -> None:
    """Saved turbines are those with a day; the loss is output times the wind of that day."""
    plan = {1: 3, 2: 1, 3: None}
    weights = {1: 10.0, 2: 40.0, 3: 5.0}

    assert plan_saved(plan) == 2
    assert plan_output_lost(plan, weights, WIND) == 40.0 * 3.0 + 10.0 * 5.0


def test_a_plan_is_described_in_words() -> None:
    """Each day's repair, then the turbines left to fail, the count saved and the loss."""
    weights = {1: 10.0, 2: 40.0}

    assert describe_plan({2: 1, 1: 3}, weights, WIND) == (
        "day 1 turbine 2, day 3 turbine 1. Turbines saved: 2 of 2. Output lost: 170."
    )
    assert describe_plan({2: 0, 1: None}, weights, WIND) == (
        "day 0 turbine 2; not repaired in time: turbine 1. Turbines saved: 1 of 2. Output lost: 320."
    )
    assert describe_plan({1: None}, weights, WIND) == (
        "not repaired in time: turbine 1. Turbines saved: 0 of 1. Output lost: 0."
    )


def test_the_order_follows_the_repair_days_with_unsaved_last() -> None:
    """Earliest day first; the unsaved by higher output, then by id."""
    plan = {1: 3, 2: 1, 3: None, 4: None, 5: None}
    weights = {1: 10.0, 2: 40.0, 3: 5.0, 4: 90.0, 5: 5.0}

    assert plan_order(plan, weights) == [2, 1, 4, 3, 5]


def test_the_schedule_carries_day_date_and_wind() -> None:
    """The entries the graph reads: day, ISO date, forecast wind or None."""
    schedule = schedule_entries({2: 1, 1: None}, WIND, date(2026, 11, 8))

    assert schedule == {
        2: {"day": 1, "date": "2026-11-09", "wind_speed": 3.0},
        1: {"day": None, "date": None, "wind_speed": None},
    }


def test_the_schedule_has_no_wind_speed_without_a_forecast() -> None:
    """With no forecast, or a gap on the repair day, the speed is None, not a filled value."""
    assert schedule_entries({1: 2}, [], date(2026, 11, 8))[1]["wind_speed"] is None
    assert schedule_entries({1: 1}, [4.0, None, 5.0], date(2026, 11, 8))[1]["wind_speed"] is None


def test_the_filled_forecast_has_one_value_per_day() -> None:
    """`fill_wind` pads a short forecast with the mean of the known days."""
    assert fill_wind([4.0, None, 8.0], 5) == [4.0, 6.0, 8.0, 6.0, 6.0]
