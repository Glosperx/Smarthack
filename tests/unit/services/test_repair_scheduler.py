"""
# Unit tests for the single-crew repair scheduler

Covers the day choice, the one-repair-per-day limit, the deadline, the missing forecast and an
exhaustive cross-check of the dynamic program against brute force.
"""

from itertools import product
import random

import pytest

from smarthack.services.agent.repair_scheduler import (
    MAX_HORIZON_DAYS,
    RepairRequest,
    schedule_repairs,
)

WIND = [8.0, 3.0, 9.0, 5.0, 2.0, 7.0, 6.0]


def test_single_turbine_takes_calmest_day_before_failure() -> None:
    """The repair lands on the lowest-wind day strictly before the failure day."""
    slots = schedule_repairs([RepairRequest(1, failure_day=4)], WIND)
    assert slots[1].day == 1
    assert slots[1].wind_speed == 3.0


def test_failure_day_itself_is_not_allowed() -> None:
    """Day 4 is calmer (2.0) but it is the failure day, so the repair cannot use it."""
    slots = schedule_repairs([RepairRequest(1, failure_day=4)], WIND)
    assert slots[1].day != 4


def test_highest_weight_gets_calmest_day() -> None:
    """Two turbines get different days and the higher-output one gets the calmer day."""
    slots = schedule_repairs(
        [
            RepairRequest(1, failure_day=4, weight=10.0),
            RepairRequest(2, failure_day=4, weight=40.0),
        ],
        WIND,
    )
    assert slots[2].day == 1
    assert slots[1].day == 3
    assert slots[1].day != slots[2].day


def test_never_two_repairs_on_one_day() -> None:
    """With more turbines than calm days, no day is used twice."""
    requests = [RepairRequest(i, failure_day=7, weight=float(i + 1)) for i in range(5)]
    days = [s.day for s in schedule_repairs(requests, WIND).values()]
    assert None not in days
    assert len(set(days)) == len(days)


def test_infeasible_gives_up_the_lowest_output_turbine() -> None:
    """Two turbines that must be repaired today: one slot, so the weaker one is left out."""
    slots = schedule_repairs(
        [RepairRequest(1, failure_day=0, weight=5.0), RepairRequest(2, failure_day=1, weight=50.0)],
        WIND,
    )
    assert slots[2].day == 0
    assert slots[1].day is None
    assert slots[1].wind_speed is None


def test_failure_today_can_only_be_repaired_today() -> None:
    """A turbine due to fail today gets day 0, the only day it can still have."""
    assert schedule_repairs([RepairRequest(1, failure_day=0)], WIND)[1].day == 0


def test_saves_more_turbines_before_taking_calm_days() -> None:
    """A heavy turbine must not take the only day a light one can still use, even if calmest."""
    slots = schedule_repairs(
        [RepairRequest(1, failure_day=3, weight=9.0), RepairRequest(2, failure_day=1, weight=1.0)],
        [1.0, 5.0, 5.0],
    )
    assert slots[2].day == 0
    assert slots[1].day == 1


def test_failure_beyond_horizon_is_capped() -> None:
    """A failure further away than the forecast still schedules inside the horizon."""
    slot = schedule_repairs([RepairRequest(1, failure_day=30)], WIND)[1]
    assert slot.day == 4


def test_no_forecast_picks_earliest_days() -> None:
    """Without wind data every day is equal, so repairs go to the earliest free days."""
    slots = schedule_repairs(
        [RepairRequest(1, failure_day=5), RepairRequest(2, failure_day=5)], daily_wind=[]
    )
    assert sorted(s.day for s in slots.values() if s.day is not None) == [0, 1]
    assert all(s.wind_speed is None for s in slots.values())


def test_unknown_days_do_not_look_calmer_than_known_ones() -> None:
    """A day with no forecast is treated as average, not as zero wind."""
    slot = schedule_repairs([RepairRequest(1, failure_day=3)], [10.0, None, 5.0])[1]
    assert slot.day == 2


def test_empty_requests() -> None:
    """No turbines means an empty schedule."""
    assert schedule_repairs([], WIND) == {}


@pytest.mark.parametrize(
    "requests",
    [
        [RepairRequest(1, 3), RepairRequest(1, 4)],
        [RepairRequest(1, 3, weight=-1.0)],
    ],
)
def test_invalid_requests_raise(requests: list[RepairRequest]) -> None:
    """Repeated ids and negative weights are rejected."""
    with pytest.raises(ValueError):
        schedule_repairs(requests, WIND)


@pytest.mark.parametrize("horizon", [0, MAX_HORIZON_DAYS + 1])
def test_invalid_horizon_raises(horizon: int) -> None:
    """A horizon with no day, or one so long the search would blow up, is rejected."""
    with pytest.raises(ValueError):
        schedule_repairs([RepairRequest(1, 3)], WIND, horizon_days=horizon)


def test_longest_horizon_is_still_instant() -> None:
    """Sixteen days and several turbines finish at once, thanks to the bit-set search."""
    requests = [RepairRequest(i, failure_day=16, weight=float(i + 1)) for i in range(8)]
    wind: list[float | None] = [float(d % 5 + 1) for d in range(MAX_HORIZON_DAYS)]
    slots = schedule_repairs(requests, wind, horizon_days=MAX_HORIZON_DAYS)
    assert all(s.day is not None for s in slots.values())


def _brute_force_score(
    requests: list[RepairRequest], wind: list[float], horizon: int
) -> tuple[int, float, float, int]:
    """
    Find the best plan by trying every assignment of days.

    :param requests: Turbines to repair.
    :param wind: Wind per day.
    :param horizon: Days available.

    :returns score: `(left out, weight left out, output lost, sum of days)` of the best plan.
    """
    best: tuple[int, float, float, int] | None = None
    choices = [[None, *range(min(max(r.failure_day - 1, 0), horizon - 1) + 1)] for r in requests]
    for plan in product(*choices):
        days = [d for d in plan if d is not None]
        if len(set(days)) != len(days):
            continue
        left = [r for r, d in zip(requests, plan, strict=True) if d is None]
        loss = sum(r.weight * wind[d] for r, d in zip(requests, plan, strict=True) if d is not None)
        score = (len(left), sum(r.weight for r in left), loss, sum(days))
        if best is None or score < best:
            best = score
    assert best is not None
    return best


def test_matches_brute_force_on_random_cases() -> None:
    """The dynamic program finds exactly the optimum an exhaustive search finds."""
    rng = random.Random(7)
    for _ in range(60):
        count = rng.randint(1, 4)
        requests = [
            RepairRequest(i, failure_day=rng.randint(0, 9), weight=float(rng.randint(0, 6)))
            for i in range(count)
        ]
        wind = [float(rng.randint(1, 12)) for _ in range(7)]
        slots = schedule_repairs(requests, list(wind))
        by_id = {r.turbine_id: r for r in requests}
        days = [s.day for s in slots.values()]
        left = [by_id[t] for t, s in slots.items() if s.day is None]
        score = (
            len(left),
            sum(r.weight for r in left),
            sum(by_id[t].weight * wind[s.day] for t, s in slots.items() if s.day is not None),
            sum(d for d in days if d is not None),
        )
        expected = _brute_force_score(requests, wind, 7)
        assert score[0] == expected[0]
        assert score[1] == pytest.approx(expected[1])
        assert score[2] == pytest.approx(expected[2])
        assert score[3] == expected[3]
