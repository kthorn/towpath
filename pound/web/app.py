"""FastAPI application factory and production entry point."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from stat import S_ISREG

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.staticfiles import StaticFiles

from pound.catalog.artifact import load_catalog
from pound.catalog.spatial import CatalogSpatialIndex
from pound.graph.artifact import GraphArtifact, InvalidArtifactError, load_artifact
from pound.graph.spatial import GraphSpatialIndex, PoiSpatialIndex
from pound.web.api import router as api_router
from pound.web.boat_hire import load_boat_hire_seeds, snap_boat_hire_bases
from pound.web.config import WebSettings


def _load_web_artifact(settings: WebSettings) -> GraphArtifact:
    """Load and validate the artifact fields required by the web application."""

    path = settings.artifact_path
    try:
        return load_artifact(path)
    except InvalidArtifactError as exc:
        raise RuntimeError(f"Could not load routing artifact {path}: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Could not load routing artifact {path}: {exc}") from exc


def create_app(settings: WebSettings | None = None) -> FastAPI:
    """Create the Pound web application without loading artifacts yet."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime_settings = settings if settings is not None else WebSettings.from_env()
        artifact = _load_web_artifact(runtime_settings)
        app.state.artifact = artifact
        app.state.graph = artifact.graph
        app.state.pois = artifact.pois
        app.state.metadata = artifact.metadata
        app.state.artifact_revision = artifact.metadata["artifact_revision"]
        app.state.settings = runtime_settings
        app.state.spatial_index = GraphSpatialIndex(artifact.graph)
        app.state.poi_spatial_index = PoiSpatialIndex(artifact.pois)
        seeds = load_boat_hire_seeds(runtime_settings.boat_hire_enrichment_path)
        app.state.boat_hire_anchors = snap_boat_hire_bases(app.state.spatial_index, seeds)
        app.state.network_unavailable = not app.state.boat_hire_anchors

        app.state.catalog = None
        app.state.catalog_revision = None
        app.state.catalog_spatial_index = None
        app.state.catalog_status = "unavailable"
        app.state.catalog_error = None
        if runtime_settings.catalog_path is not None:
            try:
                catalog = load_catalog(runtime_settings.catalog_path)
                app.state.catalog = catalog
                app.state.catalog_revision = catalog.metadata["catalog_revision"]
                app.state.catalog_spatial_index = CatalogSpatialIndex(
                    catalog.places, app.state.spatial_index
                )
                app.state.catalog_status = "available"
            except Exception as exc:
                app.state.catalog_error = str(exc)
        yield

    application = FastAPI(lifespan=lifespan)
    application.include_router(api_router)

    @application.exception_handler(RequestValidationError)
    async def catalog_request_validation_error(
        request: Request,
        exc: RequestValidationError,
    ):
        if request.url.path != "/api/catalog-places":
            return await request_validation_exception_handler(request, exc)

        fields = sorted(
            {
                ".".join(str(part) for part in error["loc"] if part != "body") or "body"
                for error in exc.errors()
            }
        )
        return JSONResponse(
            status_code=400,
            content={
                "detail": {
                    "code": "invalid_catalog_query",
                    "message": "Invalid catalog query.",
                    "fields": fields,
                }
            },
        )

    @application.get("/api/health")
    async def health(request: Request) -> dict[str, str | None]:
        catalog_configured = request.app.state.settings.catalog_path is not None
        status = "healthy"
        if catalog_configured and request.app.state.catalog_status != "available":
            status = "degraded"
        return {
            "status": status,
            "artifact_revision": request.app.state.artifact_revision,
            "catalog_revision": request.app.state.catalog_revision,
            "catalog_status": request.app.state.catalog_status,
        }

    configured_static_dir = (
        settings.static_dir
        if settings is not None
        else Path(os.environ.get("POUND_STATIC_DIR", "web/dist"))
    )
    assets_dir = configured_static_dir / "assets"
    if assets_dir.is_dir():
        application.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @application.get("/{client_path:path}", response_model=None)
    async def static_site(request: Request, client_path: str) -> FileResponse:
        """Serve the built client, falling back to its index for extensionless routes."""

        if (
            client_path == "api"
            or client_path.startswith("api/")
            or client_path == "assets"
            or client_path.startswith("assets/")
        ):
            raise HTTPException(status_code=404)

        static_dir = Path(request.app.state.settings.static_dir)
        static_files = StaticFiles(directory=static_dir, check_dir=False)
        index_path, index_stat = await run_in_threadpool(static_files.lookup_path, "index.html")
        if index_stat is None or not S_ISREG(index_stat.st_mode):
            raise HTTPException(status_code=404)
        if client_path:
            full_path, stat_result = await run_in_threadpool(static_files.lookup_path, client_path)
            if stat_result is not None and S_ISREG(stat_result.st_mode):
                return FileResponse(full_path, stat_result=stat_result)

        if Path(client_path).suffix:
            raise HTTPException(status_code=404)
        return FileResponse(index_path, stat_result=index_stat, media_type="text/html")

    return application


app = create_app()
