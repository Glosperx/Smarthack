"""
# SPA static mounting

Serves the built React Single Page Application distribution with HTML5 fallback.

The following can be imported from this module:
- `mount_spa`
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def mount_spa(app: FastAPI, dist: Path) -> None:
    """
    Mount the frontend distribution directory onto the FastAPI application.

    If `index.html` is absent (such as in local development where Vite serves
    the UI independently on port 5173), no static routes are mounted.

    :param app: The FastAPI application instance.
    :param dist: The path to the built frontend distribution directory.

    :returns: None.
    """
    index = dist / "index.html"
    if not index.exists():
        return

    assets_dir = dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        """
        Serve static assets or fallback to index.html for client-side SPA routing.

        :param full_path: Requested URL subpath.

        :returns response: The static file or index.html fallback.
        :raises HTTPException: 404 error if an unhandled /api path is requested.
        """
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        candidate = (dist / full_path).resolve()
        if candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)


__all__ = ["mount_spa"]
