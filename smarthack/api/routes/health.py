"""
# Health route

Health check and probe endpoint.

The following can be imported from this module:
- `router`
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
import httpx

from smarthack import config
from smarthack.api.dependencies import get_http_client
from smarthack.clients.supabase_parks import _headers

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=dict[str, str])
async def health_check() -> dict[str, str]:
    """
    Return the health status of the application.

    :returns status: A dictionary containing the operational status string.
    """
    return {"status": "ok"}


@router.get("/db", response_model=dict[str, Any])
async def health_check_db(
    http: Annotated[httpx.AsyncClient, Depends(get_http_client)],
) -> dict[str, Any]:
    """
    Test connectivity to Supabase and query the configured table.

    :param http: Injected application HTTP client.

    :returns result: Connection test details including status, table name, and rows found.
    """
    supabase_url = config.supabase_url()
    table = config.supabase_parks_table()

    if not supabase_url or not config.supabase_key():
        return {
            "status": "unconfigured",
            "message": "SUPABASE_URL or SUPABASE_KEY is missing in environment/.env",
        }

    target_url = f"{supabase_url}/rest/v1/{table}"
    try:
        resp = await http.get(target_url, params={"select": "*", "limit": "5"}, headers=_headers())
        resp.raise_for_status()
        rows = resp.json()
        return {
            "status": "connected",
            "message": f"Successfully connected to Supabase and queried '{table}'",
            "table": table,
            "rows_count": len(rows),
            "sample_rows": rows,
        }
    except httpx.HTTPStatusError as exc:
        return {
            "status": "error",
            "http_status": exc.response.status_code,
            "error_detail": exc.response.text,
            "message": f"Supabase responded with error HTTP {exc.response.status_code}",
        }
    except Exception as exc:
        return {
            "status": "error",
            "error_type": type(exc).__name__,
            "message": "Failed to connect to Supabase",
        }


__all__ = ["router"]
