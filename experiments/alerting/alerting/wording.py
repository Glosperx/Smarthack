"""
# Romanian wording

Turns numbers, times and labels into Romanian text shared by the email and the phone call:
"turbina 7", never "T07"; "aproximativ 18 ore", "20 de ore", "145.000 de lei".

Two rules are easy to forget:
- Romanian puts "de" between a number and its noun when the number's last two digits are 00
  or 20-99 ("20 de ore", "145.000 de lei") but not for 1-19 ("18 ore", "101 ore").
- Time to failure is rounded **down**: the message never promises more time than estimated.

Times are shown in Europe/Bucharest.

The following can be imported from this module:
- `SEVERITY`
- `TIMEZONE`
- `SeverityWords`
- `count`
- `eta_long`
- `eta_short`
- `format_datetime`
- `format_window`
- `integer`
- `needs_de`
- `percent`
- `turbines_phrase`
"""

from dataclasses import dataclass
from datetime import datetime
import math
from zoneinfo import ZoneInfo

__all__ = [
    "SEVERITY",
    "TIMEZONE",
    "SeverityWords",
    "count",
    "eta_long",
    "eta_short",
    "format_datetime",
    "format_window",
    "integer",
    "needs_de",
    "percent",
    "turbines_phrase",
]

TIMEZONE = ZoneInfo("Europe/Bucharest")

_HOURS_BEFORE_DAYS = 48

_WEEKDAYS = ["luni", "marți", "miercuri", "joi", "vineri", "sâmbătă", "duminică"]
_MONTHS = [
    "ianuarie",
    "februarie",
    "martie",
    "aprilie",
    "mai",
    "iunie",
    "iulie",
    "august",
    "septembrie",
    "octombrie",
    "noiembrie",
    "decembrie",
]


@dataclass(frozen=True)
class SeverityWords:
    """How one severity is written: subject tag, adjective after "gravitate", risk phrase."""

    tag: str
    adjective: str
    risk: str
    color: str


SEVERITY: dict[str, SeverityWords] = {
    "scazuta": SeverityWords("SCĂZUT", "scăzută", "risc scăzut", "#15803d"),
    "medie": SeverityWords("MEDIU", "medie", "risc mediu", "#a16207"),
    "ridicata": SeverityWords("RIDICAT", "ridicată", "risc ridicat", "#c2410c"),
    "critica": SeverityWords("CRITIC", "critică", "risc critic", "#b91c1c"),
}


def integer(value: float) -> str:
    """
    Write a whole number with a dot between thousands.

    :param value: The number; it is rounded to the nearest integer.

    :returns: For example "145.000".
    """
    return f"{round(value):,}".replace(",", ".")


def count(value: float, one: str, many: str) -> str:
    """
    Put a number before a noun the Romanian way.

    :param value: The number; it is rounded to the nearest integer.
    :param one: The singular noun, used for 1 ("oră").
    :param many: The plural noun ("ore").

    :returns: "1 oră", "18 ore", "20 de ore", "145.000 de lei".
    """
    number = round(value)
    if number == 1:
        return f"1 {one}"
    return f"{integer(number)} {'de ' if needs_de(number) else ''}{many}"


def needs_de(number: int) -> bool:
    """
    Whether Romanian puts "de" between this number and its noun.

    :param number: A whole number.

    :returns: True when the last two digits are 00 (and the number is not 0) or 20-99.
    """
    last_two = number % 100
    return number != 0 and (last_two == 0 or last_two >= 20)


def eta_short(hours: float) -> str:
    """
    Time to failure for a subject line.

    :param hours: Estimated hours until the failure.

    :returns: "~18h"; "~4 zile" from 48 hours on; "<1h" under an hour.
    """
    if hours < 1:
        return "<1h"
    if hours >= _HOURS_BEFORE_DAYS:
        return f"~{count(math.floor(hours / 24), 'zi', 'zile')}"
    return f"~{math.floor(hours)}h"


def eta_long(hours: float) -> str:
    """
    Time to failure as a phrase, for the email body and the spoken message.

    :param hours: Estimated hours until the failure.

    :returns: "aproximativ 18 ore", "aproximativ o oră", "aproximativ 4 zile" or
        "mai puțin de o oră".
    """
    if hours < 1:
        return "mai puțin de o oră"
    if hours >= _HOURS_BEFORE_DAYS:
        return f"aproximativ {count(math.floor(hours / 24), 'zi', 'zile')}"
    whole = math.floor(hours)
    return "aproximativ o oră" if whole == 1 else f"aproximativ {count(whole, 'oră', 'ore')}"


def turbines_phrase(numbers: list[int]) -> str:
    """
    Name turbines the way they are said.

    :param numbers: Turbine numbers, in the order to say them.

    :returns: "turbina 7", "turbinele 11 și 12", "turbinele 2, 5 și 9".
    """
    if len(numbers) == 1:
        return f"turbina {numbers[0]}"
    head = ", ".join(str(number) for number in numbers[:-1])
    return f"turbinele {head} și {numbers[-1]}"


def percent(probability: float) -> str:
    """
    Write a probability as a whole percentage.

    :param probability: A value between 0 and 1.

    :returns: For example "82%".
    """
    return f"{round(probability * 100)}%"


def _date(moment: datetime, with_year: bool = True) -> str:
    local = moment.astimezone(TIMEZONE)
    year = f" {local.year}" if with_year else ""
    return f"{_WEEKDAYS[local.weekday()]}, {local.day} {_MONTHS[local.month - 1]}{year}"


def format_datetime(moment: datetime) -> str:
    """
    Write a moment in Romanian, in Bucharest time.

    :param moment: A timezone-aware datetime.

    :returns: For example "miercuri, 11 noiembrie 2026, ora 14:05".
    """
    return f"{_date(moment)}, ora {moment.astimezone(TIMEZONE):%H:%M}"


def format_window(start: datetime, end: datetime) -> str:
    """
    Write a time window in Romanian, in Bucharest time.

    :param start: Start of the window, timezone-aware.
    :param end: End of the window, timezone-aware.

    :returns: "joi, 12 noiembrie 2026, între 04:00 și 14:00" on one day; otherwise
        "de joi, 12 noiembrie, ora 08:00, până sâmbătă, 14 noiembrie 2026, ora 20:00".
    """
    first, last = start.astimezone(TIMEZONE), end.astimezone(TIMEZONE)
    if first.date() == last.date():
        return f"{_date(first)}, între {first:%H:%M} și {last:%H:%M}"
    return (
        f"de {_date(first, with_year=first.year != last.year)}, ora {first:%H:%M}, "
        f"până {_date(last)}, ora {last:%H:%M}"
    )
