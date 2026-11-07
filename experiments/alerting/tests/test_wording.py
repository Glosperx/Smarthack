"""Tests for the Romanian wording shared by the email and the call."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from alerting.wording import (
    count,
    eta_long,
    eta_short,
    format_datetime,
    format_window,
    integer,
    percent,
    turbines_phrase,
)

BUCHAREST = ZoneInfo("Europe/Bucharest")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, "1 oră"),
        (2, "2 ore"),
        (18, "18 ore"),
        (19, "19 ore"),
        (20, "20 de ore"),
        (36, "36 de ore"),
        (100, "100 de ore"),
        (101, "101 ore"),
        (119, "119 ore"),
        (120, "120 de ore"),
        (0, "0 ore"),
    ],
)
def test_count_puts_de_where_romanian_needs_it(value: int, expected: str) -> None:
    assert count(value, "oră", "ore") == expected


def test_count_groups_thousands_with_a_dot() -> None:
    assert count(145000, "leu", "lei") == "145.000 de lei"
    assert count(4200, "leu", "lei") == "4.200 de lei"
    assert integer(1234567) == "1.234.567"


@pytest.mark.parametrize(
    ("hours", "short", "long"),
    [
        (18, "~18h", "aproximativ 18 ore"),
        (6.5, "~6h", "aproximativ 6 ore"),
        (1.9, "~1h", "aproximativ o oră"),
        (0.4, "<1h", "mai puțin de o oră"),
        (23, "~23h", "aproximativ 23 de ore"),
        (47.9, "~47h", "aproximativ 47 de ore"),
        (52, "~2 zile", "aproximativ 2 zile"),
        (96, "~4 zile", "aproximativ 4 zile"),
    ],
)
def test_eta_rounds_down_and_switches_to_days_at_48h(hours: float, short: str, long: str) -> None:
    assert eta_short(hours) == short
    assert eta_long(hours) == long


@pytest.mark.parametrize(
    ("numbers", "expected"),
    [
        ([7], "turbina 7"),
        ([11, 12], "turbinele 11 și 12"),
        ([2, 5, 9], "turbinele 2, 5 și 9"),
    ],
)
def test_turbines_are_named_as_spoken(numbers: list[int], expected: str) -> None:
    assert turbines_phrase(numbers) == expected


def test_percent_rounds_to_whole_numbers() -> None:
    assert percent(0.824) == "82%"
    assert percent(0.01) == "1%"


def test_dates_are_romanian_and_in_bucharest_time() -> None:
    utc = datetime(2026, 11, 13, 19, 40, tzinfo=ZoneInfo("UTC"))
    assert format_datetime(utc) == "vineri, 13 noiembrie 2026, ora 21:40"


def test_window_on_one_day() -> None:
    start = datetime(2026, 11, 12, 4, tzinfo=BUCHAREST)
    end = datetime(2026, 11, 12, 14, tzinfo=BUCHAREST)
    assert format_window(start, end) == "joi, 12 noiembrie 2026, între 04:00 și 14:00"


def test_window_over_several_days() -> None:
    start = datetime(2026, 11, 12, 8, tzinfo=BUCHAREST)
    end = datetime(2026, 11, 14, 20, tzinfo=BUCHAREST)
    assert format_window(start, end) == (
        "de joi, 12 noiembrie, ora 08:00, până sâmbătă, 14 noiembrie 2026, ora 20:00"
    )
