"""
# Date and timezone utilities

Calendar date calculations aligned to configured regional timezones.

The following can be imported from this module:
- `seconds_until_next_run`
- `today_in_tz`
"""

from datetime import date, datetime, timedelta
import math
from zoneinfo import ZoneInfo


def today_in_tz(tz_name: str, now: datetime | None = None) -> date:
    """
    Return the calendar date in the specified IANA timezone.

    :param tz_name: IANA timezone name, e.g. "Europe/Bucharest" or "UTC".
    :param now: Optional explicit instant to convert (for tests). Defaults to current time.

    :returns today: The local calendar date.
    """
    tz = ZoneInfo(tz_name)
    instant = now if now is not None else datetime.now(tz)
    return instant.astimezone(tz).date()


def seconds_until_next_run(now: datetime, interval_min: int, offset_min: int = 0) -> float:
    """
    Calculate seconds until the next slot aligned to local midnight + offset.

    Slots fall at `offset_min + k * interval_min` minutes after midnight; the last slot of
    a day is followed by the first slot of the next.

    :param now: Current timezone-aware datetime.
    :param interval_min: Interval in minutes between execution slots.
    :param offset_min: Minute offset after each slot boundary. Defaults to 0.

    :returns seconds: Float seconds until next scheduled slot.
    """
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed_min = (now - midnight).total_seconds() / 60.0
    k = max(math.floor((elapsed_min - offset_min) / interval_min) + 1, 0)
    next_min = offset_min + k * interval_min
    if next_min >= 24 * 60:
        next_run = midnight + timedelta(days=1, minutes=offset_min)
    else:
        next_run = midnight + timedelta(minutes=next_min)
    return max((next_run - now).total_seconds(), 0.0)


__all__ = ["seconds_until_next_run", "today_in_tz"]
