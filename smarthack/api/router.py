"""
# API root router

Aggregates resource routers into a single top-level API router.

The following can be imported from this module:
- `api_router`
"""

from fastapi import APIRouter

from smarthack.api.routes.dispatch import router as dispatch_router
from smarthack.api.routes.example import router as example_router
from smarthack.api.routes.health import router as health_router
from smarthack.api.routes.parks import router as parks_router
from smarthack.api.routes.resource import router as resource_router
from smarthack.api.routes.transport import router as transport_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(example_router)
api_router.include_router(dispatch_router)
api_router.include_router(parks_router)
api_router.include_router(resource_router)
api_router.include_router(transport_router)

__all__ = ["api_router"]
