"""
# API route modules

Route definitions grouped by domain resource.

The following can be imported from this module:
- `dispatch_router`
- `example_router`
- `health_router`
"""

from smarthack.api.routes.dispatch import router as dispatch_router
from smarthack.api.routes.example import router as example_router
from smarthack.api.routes.health import router as health_router

__all__ = ["dispatch_router", "example_router", "health_router"]
