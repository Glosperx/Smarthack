"""
# Wind resource route

Endpoints of the hill-zone wind atlas: summary and legend, heatmap image, proposed park
sites and a point query for any clicked location.

The following can be imported from this module:
- `router`
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from smarthack.schemas.resource import ResourcePoint, ResourceSite, ResourceSummary
from smarthack.services import resource_service
from smarthack.services.resource_service import AtlasNotBuiltError

router = APIRouter(prefix="/resource", tags=["resource"])


def _not_built(exc: AtlasNotBuiltError) -> HTTPException:
    """503 telling the operator how to build the atlas."""
    return HTTPException(status_code=503, detail=str(exc))


@router.get("/summary", response_model=ResourceSummary)
def get_summary() -> ResourceSummary:
    """
    Return the atlas method, backtest scores, legend, bounds and data sources.

    :returns summary: The atlas summary.
    :raises HTTPException: 503 when the atlas has not been built.
    """
    try:
        return resource_service.load_summary()
    except AtlasNotBuiltError as exc:
        raise _not_built(exc) from exc


@router.get(
    "/heatmap.png",
    response_class=FileResponse,
    responses={200: {"content": {"image/png": {}}, "description": "Heatmap overlay"}},
)
def get_heatmap() -> FileResponse:
    """
    Return the forecast wind heatmap of hill terrain as a transparent PNG.

    Rows are spaced in Web Mercator; place it with the bounds from `/summary`.

    :returns image: The PNG overlay.
    :raises HTTPException: 503 when the atlas has not been built.
    """
    try:
        path = resource_service.heatmap_path()
    except AtlasNotBuiltError as exc:
        raise _not_built(exc) from exc
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})


@router.get(
    "/heatmap-plain.png",
    response_class=FileResponse,
    responses={200: {"content": {"image/png": {}}, "description": "Plain heatmap overlay"}},
)
def get_plain_heatmap() -> FileResponse:
    """
    Return the forecast wind heatmap of plain terrain (below the hill band) as a PNG.

    Same placement and wind scale as `/heatmap.png`.

    :returns image: The PNG overlay.
    :raises HTTPException: 503 when the plain layer has not been built.
    """
    try:
        path = resource_service.plain_heatmap_path()
    except AtlasNotBuiltError as exc:
        raise _not_built(exc) from exc
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})


@router.get("/sites", response_model=list[ResourceSite])
def get_sites() -> list[ResourceSite]:
    """
    Return the proposed wind park sites, best first.

    :returns sites: Candidate sites with forecast wind and terrain.
    :raises HTTPException: 503 when the atlas has not been built.
    """
    try:
        return resource_service.list_sites()
    except AtlasNotBuiltError as exc:
        raise _not_built(exc) from exc


@router.get("/sites/plain", response_model=list[ResourceSite])
def get_plain_sites() -> list[ResourceSite]:
    """
    Return the proposed plain wind park sites, windiest first.

    :returns sites: Candidate sites below the hill band, with forecast wind and terrain.
    :raises HTTPException: 503 when the plain layer has not been built.
    """
    try:
        return resource_service.list_plain_sites()
    except AtlasNotBuiltError as exc:
        raise _not_built(exc) from exc


@router.get("/point", response_model=ResourcePoint)
def get_point(
    lat: Annotated[float, Query(ge=-90, le=90, description="Latitude")],
    lon: Annotated[float, Query(ge=-180, le=180, description="Longitude")],
) -> ResourcePoint:
    """
    Return forecast wind and terrain for the cell containing a point.

    :param lat: Latitude.
    :param lon: Longitude.

    :returns point: Values for the cell and a plain-language reading.
    :raises HTTPException: 503 when the atlas has not been built.
    """
    try:
        return resource_service.query_point(lat, lon)
    except AtlasNotBuiltError as exc:
        raise _not_built(exc) from exc


__all__ = ["router"]
