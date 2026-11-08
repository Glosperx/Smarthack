"""
# Unit tests for the failure overlap check

Covers the lead-time to failure-day conversion and the rule that two turbines predicted to fail
within the window of each other make a conflict.
"""

import pytest

from smarthack.services.agent.failure_overlap import failure_day, overlapping_failures


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
