"""
# Unit tests for the failure overlap check

Covers the lead-time to failure-day conversion and the rule that two turbines predicted to fail
within the window of each other make a conflict.
"""

import pytest

from smarthack.services.agent.failure_overlap import (
    failure_day,
    item_failure_day,
    lead_time_days,
    overlapping_failures,
)


@pytest.mark.parametrize(
    ("days_to_failure", "expected"),
    [(0.0, 0), (0.8, 0), (1.0, 1), (1.9, 1), (4.0, 4), (-2.0, 0)],
)
def test_failure_day(days_to_failure: float, expected: int) -> None:
    """The lead time is cut to a whole day, never below today."""
    assert failure_day(days_to_failure) == expected


def test_same_day_overlaps() -> None:
    """Two turbines due on the same day overlap."""
    assert overlapping_failures({1: 4, 2: 4}, window_days=1) == {1, 2}


def test_next_day_overlaps_with_window_of_one() -> None:
    """One day apart is still the same interval when the window is one day."""
    assert overlapping_failures({1: 4, 2: 5}, window_days=1) == {1, 2}


def test_two_days_apart_does_not_overlap() -> None:
    """Further apart than the window means no conflict."""
    assert overlapping_failures({1: 2, 2: 4}, window_days=1) == set()


def test_window_of_zero_needs_the_same_day() -> None:
    """A zero window only counts turbines due on exactly the same day."""
    assert overlapping_failures({1: 4, 2: 5}, window_days=0) == set()
    assert overlapping_failures({1: 4, 2: 4}, window_days=0) == {1, 2}


def test_only_the_close_turbines_are_reported() -> None:
    """A far-off third turbine is not part of the conflict."""
    assert overlapping_failures({1: 1, 2: 2, 3: 6}, window_days=1) == {1, 2}


def test_chain_of_close_turbines_all_overlap() -> None:
    """Each turbine is close to a neighbour, so the whole chain overlaps."""
    assert overlapping_failures({1: 1, 2: 2, 3: 3}, window_days=1) == {1, 2, 3}


@pytest.mark.parametrize("failure_days", [{}, {1: 3}])
def test_fewer_than_two_turbines_never_overlap(failure_days: dict[int, int]) -> None:
    """A lone turbine has nothing to compete with."""
    assert overlapping_failures(failure_days, window_days=1) == set()


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        ({"days_to_failure": 4.7}, 4),
        ({"days_to_failure": 0.3}, 0),
        ({"days_to_failure": 7.9}, 7),
        ({"days_to_failure": 8.0}, None),
        ({"days_to_failure": 10.2}, None),
        ({"days_to_failure": None}, None),
        ({}, None),
        ({"days_to_failure": float("nan")}, None),
        ({"days_to_failure": "soon"}, None),
    ],
)
def test_a_lead_time_of_eight_days_or_none_is_no_failure_day(
    item: dict[str, object], expected: int | None
) -> None:
    """ML1 expects such a turbine to last the week: it has no day to overlap on."""
    assert item_failure_day(item) == expected


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        ({"days_to_failure": 4.7}, 4.7),
        ({"days_to_failure": 10.2}, 10.2),
        ({"days_to_failure": None}, 8.0),
        ({}, 8.0),
        ({"days_to_failure": float("inf")}, 8.0),
    ],
)
def test_a_missing_lead_time_reads_as_no_failure_predicted(
    item: dict[str, object], expected: float
) -> None:
    """Missing or unusable is the "no failure predicted" value, never a crash."""
    assert lead_time_days(item) == expected
