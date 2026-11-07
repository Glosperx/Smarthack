"""
# Wind forecast background job

CLI entry point and recurring worker refreshing the 7-day hourly wind forecast of every park
in `public.park_wind_forecast`. A standalone process like the maintenance job, for the same
reasons: a scheduler inside the API would run once per Uvicorn worker, and the write key
stays out of the web process.

Run once with `python -m smarthack.jobs.wind_forecast_job` (from cron or a scheduler), or
keep it running with `--every`, which defaults to twice a day at 00:05 and 12:05 local time.

The following can be imported from this module:
- `main`
- `run_once`
- `run_worker`
"""

import argparse
import asyncio
from datetime import datetime, timedelta
import logging
import sys
from zoneinfo import ZoneInfo

import httpx

from smarthack import config
from smarthack.constants import DEFAULT_WIND_FORECAST_OFFSET_MINUTES
from smarthack.services.wind_forecast_service import run_forecast_cycle
from smarthack.utils.dates import seconds_until_next_run
from smarthack.utils.logging_utils import configure_logging

logger = logging.getLogger(__name__)


async def run_once(dry_run: bool = False) -> int:
    """
    Execute a single forecast refresh and return the process exit code.

    :param dry_run: If True, fetches the forecast without writing to Supabase.

    :returns code: Exit code 0 on success, 1 on failure.
    """
    logger.info("Starting wind forecast refresh (dry_run=%s)", dry_run)
    async with httpx.AsyncClient(timeout=config.http_timeout()) as http:
        try:
            summary = await run_forecast_cycle(http, dry_run=dry_run)
        except Exception:
            logger.exception("Wind forecast refresh failed; previous forecast left in place")
            return 1

    logger.info(
        "Refresh completed in %.2fs: parks=%d, rows=%d, written=%d",
        summary.duration_s,
        summary.parks,
        summary.rows,
        summary.written,
    )
    return 0


async def run_worker(interval_min: int, dry_run: bool = False) -> None:
    """
    Refresh the forecast now, then on every aligned slot, until interrupted.

    :param interval_min: Minute interval between aligned refreshes.
    :param dry_run: If True, fetches the forecast without writing to the database.
    """
    logger.info("Starting wind forecast worker: interval=%d min, dry_run=%s", interval_min, dry_run)
    while True:
        try:
            await run_once(dry_run=dry_run)
        except Exception:
            logger.exception("Unexpected error in wind forecast worker cycle")

        now = datetime.now(ZoneInfo(config.timezone()))
        delay = seconds_until_next_run(now, interval_min, DEFAULT_WIND_FORECAST_OFFSET_MINUTES)
        logger.info(
            "Worker sleeping %.1fs until next slot at %s", delay, now + timedelta(seconds=delay)
        )
        await asyncio.sleep(delay)


def main() -> int:
    """
    Parse command-line arguments and run a one-shot or continuous forecast refresh.

    :returns code: Process exit status code.
    """
    configure_logging()
    parser = argparse.ArgumentParser(
        description="Refresh the 7-day hourly wind forecast of every park."
    )
    parser.add_argument(
        "--every",
        type=int,
        nargs="?",
        const=config.wind_forecast_interval_minutes(),
        default=None,
        help="Run continuously every N minutes (default 720, twice a day)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and validate the forecast without writing to the database",
    )
    args = parser.parse_args()

    if args.every is None:
        return asyncio.run(run_once(dry_run=args.dry_run))
    try:
        asyncio.run(run_worker(interval_min=args.every, dry_run=args.dry_run))
    except KeyboardInterrupt:
        logger.info("Wind forecast worker stopped by user (SIGINT)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

__all__ = ["main", "run_once", "run_worker"]
