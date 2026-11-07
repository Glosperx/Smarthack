"""Unit tests for the maintenance background prediction job."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from smarthack.jobs.maintenance_job import run_once, seconds_until_next_run
from smarthack.schemas.maintenance import RunSummary


def test_seconds_until_next_run_before_offset() -> None:
    """Time before the first offset slot calculates exact remaining seconds."""
    # 00:00:00 -> next run at 00:02:00 (120 seconds)
    now = datetime(2026, 11, 7, 0, 0, 0, tzinfo=timezone.utc)
    delay = seconds_until_next_run(now, interval_min=60, offset_min=2)
    assert delay == 120.0


def test_seconds_until_next_run_mid_day() -> None:
    """Time mid-day calculates remaining seconds to next aligned hourly slot."""
    # 14:15:00 -> next run at 15:02:00 (47 minutes = 2820 seconds)
    now = datetime(2026, 11, 7, 14, 15, 0, tzinfo=timezone.utc)
    delay = seconds_until_next_run(now, interval_min=60, offset_min=2)
    assert delay == 47 * 60.0


def test_seconds_until_next_run_spans_midnight() -> None:
    """Late night instant calculates remaining seconds to tomorrow's first offset slot."""
    # 23:50:00 -> next run at 00:02:00 next day (12 minutes = 720 seconds)
    now = datetime(2026, 11, 7, 23, 50, 0, tzinfo=timezone.utc)
    delay = seconds_until_next_run(now, interval_min=60, offset_min=2)
    assert delay == 12 * 60.0


def test_run_once_dry_run_success() -> None:
    """One-shot execution in dry-run mode returns exit code 0."""
    fake_summary = RunSummary(
        day=datetime(2026, 11, 7, tzinfo=timezone.utc).date(), total=5, written=0
    )
    with patch(
        "smarthack.jobs.maintenance_job.run_prediction_cycle",
        new_callable=AsyncMock,
        return_value=fake_summary,
    ):
        exit_code = asyncio.run(run_once(dry_run=True, turbine_ids=[1]))
        assert exit_code == 0


def test_run_once_failure_exit_code() -> None:
    """Cycle exception logs error and returns non-zero exit code 1."""
    with patch(
        "smarthack.jobs.maintenance_job.run_prediction_cycle",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Supabase is unreachable"),
    ):
        exit_code = asyncio.run(run_once(dry_run=False, turbine_ids=[1]))
        assert exit_code == 1
