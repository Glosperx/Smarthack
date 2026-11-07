"""
# Date and timezone utilities

Calendar date calculations aligned to configured regional timezones.

The following can be imported from this module:
- `today_in_tz`
"""

from datetime import date, datetime
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


__all__ = ["today_in_tz"]
