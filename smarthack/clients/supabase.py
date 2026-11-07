"""
# Supabase client

Outbound HTTP client for the Supabase REST API (PostgREST). Reads tables and views of
the `public` schema with the key from `config.supabase_key`.

The following can be imported from this module:
- `_headers`
- `_write_headers`
- `fetch_all_turbine_ids`
- `fetch_maintenance_inputs`
- `fetch_parks`
- `fetch_rows`
- `fetch_turbines_with_predictions`
- `parse_ewkb_point`
- `select_rows`
- `upsert_predictions`
"""

from datetime import date
from itertools import batched
import logging
import struct
from typing import Any

import httpx

from smarthack import config
from smarthack.constants import (
    MAINTENANCE_INPUT_TABLE,
    MAINTENANCE_TABLE,
    PARK_TABLE,
    PARK_VIEW,
    TURBINE_TABLE,
)

logger = logging.getLogger(__name__)


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


def _write_headers() -> dict[str, str]:
    """
    Construct administrative write headers with service role privileges.

    :returns headers: Dictionary containing apikey and Authorization header for writes.
    """
    key = config.supabase_service_key()
    headers = {"apikey": key}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _url(resource: str) -> str:
    """
    Construct resource URL under Supabase PostgREST endpoint.

    :param resource: Database table or view name.

    :returns url: Full endpoint URL string.
    """
    return f"{config.supabase_url()}/rest/v1/{resource}"


def parse_ewkb_point(hex_str: str) -> tuple[float, float] | None:
    """
    Parse a PostGIS WKB or EWKB hex string for a 2D Point.

    :param hex_str: Hexadecimal string representing geometry.

    :returns coords: Tuple of (latitude, longitude) or None if malformed.
    """
    try:
        raw = bytes.fromhex(hex_str)
        if len(raw) < 21:
            return None
        bo = "<" if raw[0] == 1 else ">"
        gtype = struct.unpack_from(bo + "I", raw, 1)[0]
        offset = 9 if bool(gtype & 0x20000000) else 5
        if len(raw) < offset + 16:
            return None
        lon, lat = struct.unpack_from(bo + "2d", raw, offset)
        return lat, lon
    except Exception:
        return None


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


def select_rows(relation: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """
    Synchronously select rows of a table or view, with PostgREST filters.

    :param relation: Name of the table or view in the `public` schema.
    :param params: PostgREST query parameters, such as `{"park_id": "eq.1"}`. `select`
        defaults to `*`.

    :returns rows: One dict per row, keyed by column name.
    :raises httpx.HTTPError: When the request fails or Supabase answers with an error status.
    :raises RuntimeError: When `SUPABASE_URL` or `SUPABASE_KEY` is not set.
    """
    key = config.supabase_key()
    resp = httpx.get(
        f"{config.supabase_url()}/rest/v1/{relation}",
        params={"select": "*", **(params or {})},
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=config.http_timeout(),
    )
    resp.raise_for_status()
    rows: list[dict[str, Any]] = resp.json()
    return rows


async def fetch_parks(http: httpx.AsyncClient) -> list[dict[str, Any]]:
    """
    Fetch wind parks records from Supabase PostgREST endpoint.

    Attempts to query `park_map` view, falling back to base `park` table if absent.

    :param http: Shared asynchronous HTTP client.

    :returns rows: Raw list of dictionaries returned by PostgREST.
    :raises httpx.HTTPError: When the HTTP request to Supabase fails.
    """
    resp = await http.get(
        _url(PARK_VIEW),
        params={"select": "id,name,latitude,longitude", "order": "id.asc", "limit": "1000"},
        headers=_headers(),
    )
    if resp.status_code == 404:
        # Fall back to base table `park`
        resp = await http.get(
            _url(PARK_TABLE),
            params={"select": "*", "order": "id.asc", "limit": "1000"},
            headers=_headers(),
        )
        resp.raise_for_status()
        raw_rows = resp.json()
        parsed_rows: list[dict[str, Any]] = []
        for r in raw_rows:
            loc = r.get("location")
            if loc and isinstance(loc, str):
                coords = parse_ewkb_point(loc)
                if coords:
                    parsed_rows.append(
                        {
                            "id": r["id"],
                            "name": r.get("name", f"Park #{r['id']}"),
                            "latitude": coords[0],
                            "longitude": coords[1],
                        }
                    )
                    continue
            parsed_rows.append(r)
        return parsed_rows

    resp.raise_for_status()
    return resp.json()


async def fetch_turbines_with_predictions(
    http: httpx.AsyncClient, park_id: int, day: date
) -> list[dict[str, Any]]:
    """
    Fetch wind turbines and their daily maintenance predictions for a specific park and date.

    :param http: Shared asynchronous HTTP client.
    :param park_id: Unique numeric wind park identifier.
    :param day: Target calendar date for prediction records.

    :returns rows: Raw list of turbine dictionaries with embedded maintenance records.
    :raises httpx.HTTPError: When the HTTP request to Supabase fails.
    """
    cols = (
        "entry_id,predicted_date,daily_fault_probability,"
        "cumulative_fault_probability,status,suspected_subsystem"
    )
    resp = await http.get(
        _url(TURBINE_TABLE),
        params={
            "select": f"id,{MAINTENANCE_TABLE}({cols})",
            "park_id": f"eq.{park_id}",
            f"{MAINTENANCE_TABLE}.predicted_date": f"eq.{day.isoformat()}",
            f"{MAINTENANCE_TABLE}.order": "entry_id.desc",
            "order": "id.asc",
            "limit": "1000",
        },
        headers=_headers(),
    )
    resp.raise_for_status()
    return resp.json()


async def fetch_all_turbine_ids(http: httpx.AsyncClient) -> list[int]:
    """
    Retrieve all turbine identifiers across all parks, using pagination.

    :param http: Shared asynchronous HTTP client.

    :returns ids: Exhaustive list of numeric turbine identifiers.
    :raises httpx.HTTPError: When the HTTP request to Supabase fails.
    """
    ids: list[int] = []
    while True:
        resp = await http.get(
            _url(TURBINE_TABLE),
            params={"select": "id", "order": "id.asc", "limit": 1000, "offset": len(ids)},
            headers=_headers(),
        )
        resp.raise_for_status()
        page: list[dict[str, Any]] = resp.json()
        ids.extend([int(row["id"]) for row in page if "id" in row])
        if len(page) < 1000:
            return ids


async def upsert_predictions(http: httpx.AsyncClient, rows: list[dict[str, Any]]) -> None:
    """
    Upsert daily turbine health predictions into database with conflict resolution on (turbine_id, predicted_date).

    :param http: Shared asynchronous HTTP client.
    :param rows: Serialized diagnostic prediction dictionaries.
    :raises httpx.HTTPError: When the upsert request fails.
    """
    headers = {
        **_write_headers(),
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    core_cols = {
        "turbine_id",
        "predicted_date",
        "daily_fault_probability",
        "cumulative_fault_probability",
        "status",
        "suspected_subsystem",
    }
    for chunk in batched(rows, 500):
        chunk_list = list(chunk)
        resp = await http.post(
            _url(MAINTENANCE_TABLE),
            params={"on_conflict": "turbine_id,predicted_date"},
            headers=headers,
            json=chunk_list,
        )
        if resp.status_code == 400:
            logger.warning("Initial upsert with all columns returned 400: %s", resp.text)
            fallback_chunk = [
                {k: v for k, v in item.items() if k in core_cols} for item in chunk_list
            ]
            resp = await http.post(
                _url(MAINTENANCE_TABLE),
                params={"on_conflict": "turbine_id,predicted_date"},
                headers=headers,
                json=fallback_chunk,
            )
            if resp.status_code == 400 and any(
                k in resp.text.lower() for k in ("unique", "42p10", "conflict")
            ):
                logger.warning(
                    "Database missing UNIQUE (turbine_id, predicted_date) constraint on %s; "
                    "falling back to direct INSERT. (Run db/migrations/V14__turbine_mentenance_unique.sql): %s",
                    MAINTENANCE_TABLE,
                    resp.text,
                )
                resp = await http.post(
                    _url(MAINTENANCE_TABLE),
                    headers=_write_headers(),
                    json=fallback_chunk,
                )
        if resp.is_error:
            logger.error("Supabase upsert/insert failed (%s): %s", resp.status_code, resp.text)
        resp.raise_for_status()


async def fetch_maintenance_inputs(
    http: httpx.AsyncClient, turbine_ids: list[int] | None = None
) -> dict[int, dict[str, Any]]:
    """
    Fetch pre-computed feature inputs from `public.turbine_maintenance_input`.

    :param http: Shared asynchronous HTTP client.
    :param turbine_ids: Optional list of turbine IDs to filter for.

    :returns mapping: Mapping from turbine_id to latest feature input row.
    :raises httpx.HTTPError: When the HTTP request to Supabase fails.
    """
    inputs: dict[int, dict[str, Any]] = {}
    offset = 0
    while True:
        params: dict[str, Any] = {
            "select": "*",
            "order": "turbine_id.asc",
            "limit": 1000,
            "offset": offset,
        }
        if turbine_ids:
            params["turbine_id"] = f"in.({','.join(str(i) for i in turbine_ids)})"
        resp = await http.get(_url(MAINTENANCE_INPUT_TABLE), params=params, headers=_headers())
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        page: list[dict[str, Any]] = resp.json()
        for row in page:
            tid = row.get("turbine_id")
            if tid is not None:
                inputs[int(tid)] = row
        offset += len(page)
        if len(page) < 1000:
            break
    return inputs


__all__ = [
    "_headers",
    "_write_headers",
    "fetch_all_turbine_ids",
    "fetch_maintenance_inputs",
    "fetch_parks",
    "fetch_rows",
    "fetch_turbines_with_predictions",
    "parse_ewkb_point",
    "select_rows",
    "upsert_predictions",
]
