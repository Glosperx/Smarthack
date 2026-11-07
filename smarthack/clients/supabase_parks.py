"""
# Supabase parks client

Outbound HTTP client wrapper for reading wind parks from Supabase PostgREST.

The following can be imported from this module:
- `fetch_parks`
"""

from typing import Any

import httpx

from smarthack import config


def _headers() -> dict[str, str]:
    """
    Construct authentication headers for the Supabase PostgREST API.

    :returns headers: Dictionary containing apikey and optional Bearer auth header.
    """
    key = config.supabase_key()
    headers = {"apikey": key}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


async def fetch_parks(http: httpx.AsyncClient) -> list[dict[str, Any]]:
    """
    Fetch wind parks records from Supabase PostgREST endpoint.

    :param http: Shared asynchronous HTTP client.

    :returns rows: Raw list of dictionaries returned by PostgREST.
    :raises httpx.HTTPError: When the HTTP request to Supabase fails.
    """
    url = f"{config.supabase_url()}/rest/v1/{config.supabase_parks_table()}"
    resp = await http.get(
        url,
        params={"select": "*", "order": "id.asc", "limit": "1000"},
        headers=_headers(),
    )
    resp.raise_for_status()
    return resp.json()


__all__ = ["fetch_parks"]
