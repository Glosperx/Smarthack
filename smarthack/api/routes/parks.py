"""
# Parks route

Endpoints for retrieving wind park geographic coordinates and turbine maintenance diagnostics.

The following can be imported from this module:
- `router`
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
import httpx

from smarthack.api.dependencies import get_http_client, get_today
from smarthack.schemas.parks import Park, ParkTurbines
from smarthack.services import parks_service

router = APIRouter(prefix="/parks", tags=["parks"])


@router.get("", response_model=list[Park])
async def get_parks(http: Annotated[httpx.AsyncClient, Depends(get_http_client)]) -> list[Park]:
    """
    Return all valid wind parks.

    :param http: Injected application asynchronous HTTP client.

    :returns parks: List of validated `Park` objects.
    :raises HTTPException: 502 Bad Gateway if the upstream database query fails.
    """
    try:
        return await parks_service.list_parks(http)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not load parks") from exc


@router.get("/{park_id}/turbines", response_model=ParkTurbines)
async def get_park_turbines(
    park_id: int,
    http: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    today: Annotated[date, Depends(get_today)],
) -> ParkTurbines:
    """
    Return all turbines and today's maintenance predictions for a specific park.

    :param park_id: Unique numeric identifier of the park.
    :param http: Injected application asynchronous HTTP client.
    :param today: Target calendar date provided by dependency injection.

    :returns result: Park turbines diagnostics collection.
    :raises HTTPException: 502 Bad Gateway if the upstream database query fails.
    """
    try:
        return await parks_service.list_turbines_for_park(http, park_id, today)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not load turbines") from exc


__all__ = ["router"]
