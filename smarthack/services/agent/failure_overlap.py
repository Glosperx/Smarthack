"""
# Failure overlap

Tells which turbines of a park are predicted to fail close together in time. When two or more
do, the agent has to choose which to repair first, and that is the one moment the wind power
model is worth calling.

ML1 gives a lead time of up to about 10 days, or none for a turbine it expects to last. A lead
time of `NO_FAILURE_DAYS` or more, or a missing one, is no failure day at all: such a turbine
cannot overlap with another and is not counted as failing on some made-up day.

The following can be imported from this module:
- `failure_day`
- `item_failure_day`
- `lead_time_days`
- `overlapping_failures`
"""

from collections.abc import Mapping
import math
from typing import Any

from smarthack.constants import NO_FAILURE_DAYS


def failure_day(days_to_failure: float) -> int:
    """
    Turn a lead time into the whole day, counted from today, on which the turbine is due to fail.

    :param days_to_failure: Predicted lead time in days; 0.8 means within today.

    :returns day: 0 for today, 1 for tomorrow, and so on; never negative.
    """
    return max(int(days_to_failure), 0)


def lead_time_days(item: Mapping[str, Any]) -> float:
    """
    Read a triage item's lead time, with the "no failure predicted" value for a missing one.

    :param item: A triage item; `days_to_failure` may be absent, None or not a number.

    :returns days: The lead time in days, or `NO_FAILURE_DAYS` when there is none.
    """
    raw = item.get("days_to_failure")
    try:
        days = float(raw) if raw is not None else math.nan
    except (TypeError, ValueError):
        days = math.nan
    return days if math.isfinite(days) else float(NO_FAILURE_DAYS)


def item_failure_day(item: Mapping[str, Any]) -> int | None:
    """
    Turn a triage item into the day it is due to fail, if ML1 predicts a failure at all.

    :param item: A triage item with `days_to_failure`, which may be absent or None.

    :returns day: The failure day as `failure_day` gives it, or None when the lead time is
        missing or at least `NO_FAILURE_DAYS`.
    """
    days = lead_time_days(item)
    return None if days >= NO_FAILURE_DAYS else failure_day(days)


def overlapping_failures(failure_days: Mapping[int, int], window_days: int) -> set[int]:
    """
    Find the turbines whose failure day is within `window_days` of another turbine's.

    Sorting is enough: a turbine has a close neighbour exactly when the turbine just before or
    just after it in time is close.

    :param failure_days: Failure day of each turbine, keyed by turbine id.
    :param window_days: Largest gap in days that still counts as the same interval.

    :returns turbine_ids: Ids of the turbines that overlap with at least one other; empty when
        fewer than two turbines are given or all are further apart than the window.
    """
    ordered = sorted(failure_days.items(), key=lambda item: (item[1], item[0]))
    overlapping: set[int] = set()
    for (id_a, day_a), (id_b, day_b) in zip(ordered, ordered[1:], strict=False):
        if day_b - day_a <= window_days:
            overlapping.update((id_a, id_b))
    return overlapping


__all__ = ["failure_day", "item_failure_day", "lead_time_days", "overlapping_failures"]
