"""
# Maintenance prediction background job

CLI entry point and recurring worker scheduling fleet-wide maintenance health forecasts.

The following can be imported from this module:
- `main`
- `run_once`
- `run_worker`
- `seconds_until_next_run`
"""

import argparse
import asyncio
from datetime import datetime, timedelta
import logging
import sys
from zoneinfo import ZoneInfo

import httpx

from smarthack import config
from smarthack.constants import DEFAULT_MAINTENANCE_OFFSET_MINUTES
from smarthack.services.maintenance_service import run_prediction_cycle
from smarthack.utils.dates import seconds_until_next_run, today_in_tz
from smarthack.utils.logging_utils import configure_logging

logger = logging.getLogger(__name__)


async def run_once(dry_run: bool = False, turbine_ids: list[int] | None = None) -> int:
    """
    Execute a single prediction cycle and return process exit code.

    :param dry_run: If True, evaluates predictions without writing to Supabase.
    :param turbine_ids: Optional explicit turbine IDs to evaluate.

    :returns code: Exit code 0 on success, 1 on failure.
    """
    tz_name = config.timezone()
    day = today_in_tz(tz_name)
    logger.info("Starting maintenance prediction cycle for date=%s (dry_run=%s)", day, dry_run)

    async with httpx.AsyncClient(timeout=config.http_timeout()) as http:
        try:
            summary = await run_prediction_cycle(
                http,
                day=day,
                turbine_ids=turbine_ids,
                dry_run=dry_run,
            )
        except Exception:
            logger.exception("Maintenance prediction cycle failed unrecoverably")
            return 1

    logger.info(
        "Cycle completed in %.2fs: total=%d, written=%d, failed=%d, no_data=%d, by_status=%s",
        summary.duration_s,
        summary.total,
        summary.written,
        summary.failed,
        summary.no_data,
        summary.by_status,
    )
    if summary.written == 0 and not dry_run and summary.total > 0:
        return 1
    return 0


async def run_worker(
    interval_min: int,
    dry_run: bool = False,
    turbine_ids: list[int] | None = None,
) -> None:
    """
    Run continuous scheduled prediction worker loop until interrupted.

    :param interval_min: Minute interval between aligned runs.
    :param dry_run: If True, computes predictions without writing to database.
    :param turbine_ids: Optional explicit turbine IDs to evaluate.
    """
    logger.info(
        "Starting maintenance worker loop: interval=%d min, dry_run=%s",
        interval_min,
        dry_run,
    )

    while True:
        try:
            await run_once(dry_run=dry_run, turbine_ids=turbine_ids)
        except Exception:
            logger.exception("Unexpected error in worker execution cycle")

        tz_name = config.timezone()
        now = datetime.now(ZoneInfo(tz_name))
        delay = seconds_until_next_run(now, interval_min, DEFAULT_MAINTENANCE_OFFSET_MINUTES)
        logger.info(
            "Worker sleeping %.1fs until next slot at %s", delay, now + timedelta(seconds=delay)
        )
        await asyncio.sleep(delay)


def main() -> int:
    """
    Parse command-line arguments and run one-shot or continuous maintenance predictions.

    :returns code: Process exit status code.
    """
    configure_logging()
    parser = argparse.ArgumentParser(
        description="Run scheduled fleet-wide turbine predictive maintenance evaluations."
    )
    parser.add_argument(
        "--every",
        type=int,
        nargs="?",
        const=config.maintenance_interval_minutes(),
        default=None,
        help="Run continuously every N minutes (default 60)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate models and log results without writing to database",
    )
    parser.add_argument(
        "--turbine-id",
        type=int,
        action="append",
        dest="turbine_ids",
        help="Limit execution to specific turbine ID (can be repeated)",
    )

    args = parser.parse_args()

    if args.every is not None:
        try:
            asyncio.run(
                run_worker(
                    interval_min=args.every,
                    dry_run=args.dry_run,
                    turbine_ids=args.turbine_ids,
                )
            )
            return 0
        except KeyboardInterrupt:
            logger.info("Worker loop stopped by user (SIGINT)")
            return 0
    else:
        return asyncio.run(run_once(dry_run=args.dry_run, turbine_ids=args.turbine_ids))


if __name__ == "__main__":
    sys.exit(main())

__all__ = ["main", "run_once", "run_worker", "seconds_until_next_run"]
