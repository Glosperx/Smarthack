"""
# API route modules

Route definitions grouped by domain resource.

The following can be imported from this module:
- `example_router`
- `health_router`
- `parks_router`
"""

from smarthack.api.routes.example import router as example_router
from smarthack.api.routes.health import router as health_router
from smarthack.api.routes.parks import router as parks_router

__all__ = ["example_router", "health_router", "parks_router"]
