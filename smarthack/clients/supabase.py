"""
# Supabase client

Outbound HTTP client for the Supabase REST API (PostgREST). Reads tables and views of
the `public` schema with the key from `config.supabase_key`.

The following can be imported from this module:
- `fetch_rows`
"""

from typing import Any

import httpx

from smarthack import config


async def fetch_rows(
    http: httpx.AsyncClient, relation: str, limit: int | None = None
) -> list[dict[str, Any]]:
    """
    Select every column of a table or view in the `public` schema.

    :param http: Shared asynchronous HTTP client.
    :param relation: Name of the table or view, such as `"upward_turbine_mentenance"`.
    :param limit: Maximum number of rows. Defaults to None, meaning the server's own cap.

    :returns rows: One dict per row, keyed by column name.
    :raises httpx.HTTPError: When the request fails or Supabase answers with an error status.
    :raises RuntimeError: When `SUPABASE_URL` or `SUPABASE_KEY` is not set.
    """
    key = config.supabase_key()
    params = {"select": "*"}
    if limit is not None:
        params["limit"] = str(limit)
    resp = await http.get(
        f"{config.supabase_url()}/rest/v1/{relation}",
        params=params,
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
    )
    resp.raise_for_status()
    rows: list[dict[str, Any]] = resp.json()
    return rows


__all__ = ["fetch_rows"]
