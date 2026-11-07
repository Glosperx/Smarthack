"""
# Parks route

Endpoints for retrieving wind park geographic coordinates.

The following can be imported from this module:
- `router`
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
import httpx

from smarthack.api.dependencies import get_http_client
from smarthack.schemas.parks import Park
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


__all__ = ["router"]
