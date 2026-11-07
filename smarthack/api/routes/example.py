"""
# Example routes

Route handlers for querying example resources.

The following can be imported from this module:
- `router`
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
import httpx

from smarthack.api.dependencies import get_http_client
from smarthack.clients import example_service
from smarthack.schemas.example import ExampleResult

router = APIRouter(prefix="/example", tags=["example"])


@router.get("", response_model=ExampleResult)
async def get_example(
    q: str, http: Annotated[httpx.AsyncClient, Depends(get_http_client)]
) -> ExampleResult:
    """
    Search or query the example upstream service.

    :param q: Search query parameter.
    :param http: Injected application HTTP client.

    :returns result: Search result matching the query.
    :raises HTTPException: 502 when upstream request fails.
    """
    try:
        return await example_service.fetch_example(http, q)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream failed: {exc}") from exc


__all__ = ["router"]
