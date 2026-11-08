"""
# Oversize transport route

Endpoints of the oversize transport network: its summary (vehicle, ports, kilometres
per verdict and reason) and the road network itself, a gzipped compact JSON.

The following can be imported from this module:
- `router`
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from smarthack.schemas.transport import TransportSummary
from smarthack.services import transport_service
from smarthack.services.transport_service import NetworkNotBuiltError

router = APIRouter(prefix="/transport", tags=["transport"])


@router.get("/summary", response_model=TransportSummary)
def get_summary() -> TransportSummary:
    """
    Return the vehicle, ports, kilometres per verdict and reason, caveats and sources.

    :returns summary: The network summary.
    :raises HTTPException: 503 when the network has not been built.
    """
    try:
        return transport_service.load_summary()
    except NetworkNotBuiltError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get(
    "/network",
    response_class=FileResponse,
    responses={200: {"content": {"application/json": {}}, "description": "Road network"}},
)
def get_network() -> FileResponse:
    """
    Return every judged road as compact JSON (layout in `transport_service`).

    The file is stored gzipped and sent with `Content-Encoding: gzip`, which the browser
    undoes on its own.

    :returns file: The network.
    :raises HTTPException: 503 when the network has not been built.
    """
    try:
        path = transport_service.network_path()
    except NetworkNotBuiltError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type="application/json",
        headers={"Content-Encoding": "gzip", "Cache-Control": "no-cache"},
    )


__all__ = ["router"]
