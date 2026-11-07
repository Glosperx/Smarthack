"""Unit tests for date and timezone utilities."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from smarthack.utils.dates import today_in_tz


def test_today_in_tz_utc() -> None:
    """UTC instant converts to expected calendar date."""
    dt = datetime(2026, 11, 7, 22, 30, tzinfo=timezone.utc)
    assert today_in_tz("UTC", dt).isoformat() == "2026-11-07"


def test_today_in_tz_across_midnight() -> None:
    """Instant before midnight in UTC is next day in Europe/Bucharest (+2/+3)."""
    dt = datetime(2026, 11, 7, 22, 30, tzinfo=timezone.utc)
    # 22:30 UTC is 00:30 on Nov 8 in Bucharest (EET is UTC+2)
    assert today_in_tz("Europe/Bucharest", dt).isoformat() == "2026-11-08"


def test_today_in_tz_default_now() -> None:
    """Calling without explicit instant returns current local date."""
    local_today = today_in_tz("UTC")
    assert local_today == datetime.now(ZoneInfo("UTC")).date()
