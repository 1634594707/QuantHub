"""Single-process application used by the published container image."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .main import app as api_app
from .main import health as api_health


class SPAStaticFiles(StaticFiles):
    """Serve Vite assets and fall back to index.html for client routes."""

    async def get_response(self, path: str, scope: dict):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or scope.get("method") not in {"GET", "HEAD"}:
                raise
            return await super().get_response("index.html", scope)


def create_app(static_directory: str | Path | None = None) -> FastAPI:
    """Create the same-origin Web and API application for container startup."""
    static_root = Path(static_directory or Path(__file__).resolve().parents[2] / "web" / "dist")
    container_app = FastAPI(
        title="QuantHub",
        version=api_app.version,
        lifespan=api_app.router.lifespan_context,
    )

    @container_app.get("/health", include_in_schema=False)
    def health() -> dict:
        return api_health()

    container_app.mount("/api", api_app)
    container_app.mount("/", SPAStaticFiles(directory=static_root, html=True), name="web")
    return container_app
