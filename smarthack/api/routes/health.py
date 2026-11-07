"""
# Health route

Health check and probe endpoint.

The following can be imported from this module:
- `router`
"""

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=dict[str, str])
async def health_check() -> dict[str, str]:
    """
    Return the health status of the application.

    :returns status: A dictionary containing the operational status string.
    """
    return {"status": "ok"}


__all__ = ["router"]
