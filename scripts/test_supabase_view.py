"""
Smoke test for Supabase: select everything from the `upward_turbine_mentenance` view.

Needs `SUPABASE_URL` and `SUPABASE_KEY` in `.env` (see `.env.example`).

Usage: python scripts/test_supabase_view.py [--limit N]
"""

import argparse
import asyncio
import sys
from typing import Any

import httpx

from smarthack import config
from smarthack.clients.supabase import fetch_rows

VIEW = "upward_turbine_mentenance"


def format_table(rows: list[dict[str, Any]]) -> str:
    """
    Lay rows out as a plain-text table, one column per key of the first row.

    :param rows: Rows as returned by `fetch_rows`.

    :returns table: The table, or `"(no rows)"` when `rows` is empty.
    """
    if not rows:
        return "(no rows)"
    columns = list(rows[0])
    cells = [["" if row.get(c) is None else str(row.get(c)) for c in columns] for row in rows]
    widths = [max(len(c), *(len(line[i]) for line in cells)) for i, c in enumerate(columns)]

    def render(values: list[str]) -> str:
        return " | ".join(value.ljust(width) for value, width in zip(values, widths))

    separator = "-+-".join("-" * width for width in widths)
    return "\n".join([render(columns), separator, *(render(line) for line in cells)])


async def run(limit: int | None) -> int:
    """
    Fetch the rows of the view and print them.

    :param limit: Maximum number of rows, or None for all.

    :returns: Process exit code, 0 on success.
    """
    try:
        async with httpx.AsyncClient(timeout=config.http_timeout()) as http:
            rows = await fetch_rows(http, VIEW, limit)
    except httpx.HTTPStatusError as exc:
        print(f"Supabase answered {exc.response.status_code}: {exc.response.text}", file=sys.stderr)
        return 1
    except (httpx.HTTPError, RuntimeError) as exc:
        print(f"Could not query Supabase: {exc}", file=sys.stderr)
        return 1

    print(f"{len(rows)} row(s) from public.{VIEW}")
    print(format_table(rows))
    return 0


def main() -> int:
    """
    Parse the command line and run the query.

    :returns: Process exit code.
    """
    parser = argparse.ArgumentParser(description=f"Select all from public.{VIEW}")
    parser.add_argument("--limit", type=int, default=None, help="Maximum rows to fetch")
    return asyncio.run(run(parser.parse_args().limit))


if __name__ == "__main__":
    sys.exit(main())
