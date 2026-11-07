"""
# Failure overlap

Tells which turbines of a park are predicted to fail close together in time. When two or more
do, the agent has to choose which to repair first, and that is the one moment the wind power
model is worth calling.

The following can be imported from this module:
- `failure_day`
- `overlapping_failures`
"""

from collections.abc import Mapping


def failure_day(days_to_failure: float) -> int:
    """
    Turn a lead time into the whole day, counted from today, on which the turbine is due to fail.

    :param days_to_failure: Predicted lead time in days; 0.8 means within today.

    :returns day: 0 for today, 1 for tomorrow, and so on; never negative.
    """
    return max(int(days_to_failure), 0)


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


__all__ = ["failure_day", "overlapping_failures"]
