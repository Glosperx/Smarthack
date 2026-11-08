"""
# Repair plans

Everything about a repair plan that is plain arithmetic, so a model never has to do it: the
requests the scheduler takes, the candidate plans a dispatcher would weigh, how many turbines a
plan saves and how much output it loses, the plan in words, and the order of turbines it implies.

A plan maps each turbine id to the day it is repaired, counted from today, or to None when no day
is left before the turbine fails. The exact optimum from `repair_scheduler` always comes first;
beside it come three greedy plans, each putting the turbines in a different order and giving each
the earliest free day before its failure day:

- most urgent first (earliest failure day, then higher output);
- highest output first;
- most distant first (latest failure day, then higher output).

Identical plans are kept once.

The following can be imported from this module:
- `Plan`
- `build_requests`
- `candidate_plans`
- `describe_plan`
- `has_output_estimate`
- `plan_from_slots`
- `plan_order`
- `plan_output_lost`
- `plan_saved`
- `schedule_entries`
"""

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from smarthack.constants import WIND_FORECAST_DAYS
from smarthack.services.agent.failure_overlap import item_failure_day
from smarthack.services.agent.repair_scheduler import RepairRequest, RepairSlot, schedule_repairs

#: Repair day of each turbine id, counted from today; None when no day is left before failure.
Plan = dict[int, int | None]


def has_output_estimate(turbines: Sequence[Mapping[str, Any]]) -> bool:
    """
    Tell whether any turbine carries a usable output estimate.

    :param turbines: Failing turbines, `projected_mwh_7d` set by the power model or absent.

    :returns known: True when at least one has `projected_mwh_7d` above zero.
    """
    return any(float(t.get("projected_mwh_7d") or 0.0) > 0 for t in turbines)


def build_requests(turbines: Sequence[Mapping[str, Any]]) -> list[RepairRequest]:
    """
    Turn the failing turbines into the requests the scheduler takes.

    A turbine with no failure day (ML1 expects it to last the week) may be repaired any day of
    the forecast. Without a usable output estimate anywhere (power model not run, or zero
    everywhere) every turbine weighs the same, so the wind forecast still decides the day.

    :param turbines: Failing turbines with `turbine_id`, `days_to_failure` and, when the power
        model ran, `projected_mwh_7d`.

    :returns requests: One request per turbine, in the given order.
    """
    known = has_output_estimate(turbines)
    requests = []
    for t in turbines:
        day = item_failure_day(t)
        estimate = t.get("projected_mwh_7d")
        weight = float(estimate) if known and estimate is not None else 1.0
        requests.append(
            RepairRequest(
                turbine_id=int(t["turbine_id"]),
                failure_day=WIND_FORECAST_DAYS if day is None else day,
                weight=weight,
            )
        )
    return requests


def plan_from_slots(slots: Mapping[int, RepairSlot]) -> Plan:
    """
    Reduce the scheduler's answer to a plan.

    :param slots: One slot per turbine id, as `schedule_repairs` returns.

    :returns plan: Repair day per turbine id.
    """
    return {turbine_id: slot.day for turbine_id, slot in slots.items()}


def _greedy(
    requests: Sequence[RepairRequest], order: Sequence[RepairRequest], horizon: int
) -> Plan:
    """
    Give each request, in `order`, the earliest free day before its failure day.

    :param requests: All requests, to name every turbine in the plan.
    :param order: The requests in the order they pick a day.
    :param horizon: Days a repair can be planned in.

    :returns plan: Repair day per turbine id; None for a turbine with no free day left.
    """
    taken: set[int] = set()
    plan: Plan = {r.turbine_id: None for r in requests}
    for req in order:
        last_day = min(max(req.failure_day - 1, 0), horizon - 1)
        free = [d for d in range(last_day + 1) if d not in taken]
        if free:
            plan[req.turbine_id] = free[0]
            taken.add(free[0])
    return plan


def candidate_plans(
    requests: Sequence[RepairRequest],
    daily_wind: Sequence[float | None],
    horizon_days: int = WIND_FORECAST_DAYS,
) -> list[Plan]:
    """
    Build the plans a dispatcher might weigh, the exact optimum first.

    :param requests: Turbines to repair.
    :param daily_wind: Forecast wind speed per day from today, None where unknown.
    :param horizon_days: Days a repair can be planned in.

    :returns plans: Distinct plans; the first is the optimum `schedule_repairs` finds.
    """
    optimum = plan_from_slots(schedule_repairs(list(requests), daily_wind, horizon_days))
    orders = (
        sorted(requests, key=lambda r: (r.failure_day, -r.weight, r.turbine_id)),
        sorted(requests, key=lambda r: (-r.weight, r.failure_day, r.turbine_id)),
        sorted(requests, key=lambda r: (-r.failure_day, -r.weight, r.turbine_id)),
    )
    plans = [optimum]
    for order in orders:
        plan = _greedy(requests, order, horizon_days)
        if plan not in plans:
            plans.append(plan)
    return plans


def plan_saved(plan: Mapping[int, int | None]) -> int:
    """
    Count the turbines a plan repairs before they fail.

    :param plan: Repair day per turbine id.

    :returns saved: Turbines with a repair day.
    """
    return sum(day is not None for day in plan.values())


def plan_output_lost(
    plan: Mapping[int, int | None], weights: Mapping[int, float], wind: Sequence[float]
) -> float:
    """
    Add up the output lost on repair days: each repaired turbine's output times the day's wind.

    :param plan: Repair day per turbine id.
    :param weights: Expected output per turbine id.
    :param wind: Wind speed per day from today, no gaps (see `fill_wind`).

    :returns lost: Output lost in the unit of `weights` times m/s.
    """
    return sum(weights[tid] * wind[day] for tid, day in plan.items() if day is not None)


def describe_plan(
    plan: Mapping[int, int | None], weights: Mapping[int, float], wind: Sequence[float]
) -> str:
    """
    Write a plan in words: the repair of each day, the turbines left to fail, how many are saved
    and the output lost on repair days.

    :param plan: Repair day per turbine id.
    :param weights: Expected output per turbine id.
    :param wind: Wind speed per day from today, no gaps (see `fill_wind`).

    :returns text: The description of the option a decision model reads.
    """
    days = sorted((day, tid) for tid, day in plan.items() if day is not None)
    failed = sorted(tid for tid, day in plan.items() if day is None)
    parts = [", ".join(f"day {day} turbine {tid}" for day, tid in days)] if days else []
    if failed:
        parts.append("not repaired in time: " + ", ".join(f"turbine {t}" for t in failed))
    text = "; ".join(parts)
    lost = plan_output_lost(plan, weights, wind)
    return f"{text}. Turbines saved: {len(days)} of {len(plan)}. Output lost: {lost:.0f}."


def plan_order(plan: Mapping[int, int | None], weights: Mapping[int, float]) -> list[int]:
    """
    Order the turbines the way the plan repairs them.

    :param plan: Repair day per turbine id.
    :param weights: Expected output per turbine id.

    :returns turbine_ids: Earliest repair day first; turbines left unsaved last, the one with the
        higher output first, then by id.
    """
    saved = sorted((day, tid) for tid, day in plan.items() if day is not None)
    unsaved = sorted(
        (tid for tid, day in plan.items() if day is None), key=lambda t: (-weights[t], t)
    )
    return [tid for _, tid in saved] + unsaved


def schedule_entries(
    plan: Mapping[int, int | None], daily_wind: Sequence[float | None], today: date
) -> dict[int, dict[str, Any]]:
    """
    Turn a plan into the `repair_schedule` the rest of the graph reads.

    :param plan: Repair day per turbine id.
    :param daily_wind: Forecast wind speed per day from today, None where unknown; may be empty.
    :param today: The calendar day at index 0, in the application timezone.

    :returns schedule: Per turbine id: `day`, `date` (ISO) and `wind_speed`, the forecast wind of
        the repair day or None when it is not known; `day` and `date` are None when no day was left.
    """
    schedule: dict[int, dict[str, Any]] = {}
    for turbine_id, day in plan.items():
        known = day is not None and day < len(daily_wind) and daily_wind[day] is not None
        schedule[turbine_id] = {
            "day": day,
            "date": None if day is None else (today + timedelta(days=day)).isoformat(),
            "wind_speed": daily_wind[day] if known and day is not None else None,
        }
    return schedule


__all__ = [
    "Plan",
    "build_requests",
    "candidate_plans",
    "describe_plan",
    "has_output_estimate",
    "plan_from_slots",
    "plan_order",
    "plan_output_lost",
    "plan_saved",
    "schedule_entries",
]
