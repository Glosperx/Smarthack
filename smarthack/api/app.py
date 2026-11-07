"""
# Application factory

Creates and configures the FastAPI application instance with lifespan handlers,
routers, and static SPA serving.

The following can be imported from this module:
- `create_app`
- `lifespan`
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
import httpx

from smarthack import config
from smarthack.api.router import api_router
from smarthack.api.spa import mount_spa


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Manage application lifecycle resources including the shared HTTP client.

    :param app: The FastAPI application instance.

    :returns: Async iterator yielding control during application execution.
    """
    app.state.http = httpx.AsyncClient(timeout=config.http_timeout())
    yield
    await app.state.http.aclose()


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application instance.

    Mounts API routers under `/api` and attaches SPA fallback serving
    for the built frontend assets.

    :returns app: Configured FastAPI application instance.
    """
    app = FastAPI(
        title="Smarthack",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.include_router(api_router, prefix="/api")
    mount_spa(app, config.frontend_dist_dir())
    return app


__all__ = ["create_app", "lifespan"]
