"""FastAPI application factory and production entry point."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from stat import S_ISREG

from fastapi import FastAPI, HTTPException, Request  # pyright: ignore[reportMissingImports]
from fastapi.exception_handlers import (  # pyright: ignore[reportMissingImports]
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError  # pyright: ignore[reportMissingImports]
from fastapi.responses import FileResponse, JSONResponse  # pyright: ignore[reportMissingImports]
from pound.artifact import (  # pyright: ignore[reportMissingImports]
    InvalidArtifactError,
    RuntimeArtifact,
    load_artifact,
)
from pound.catalog.artifact import load_catalog  # pyright: ignore[reportMissingImports]
from pound.catalog.spatial import CatalogSpatialIndex  # pyright: ignore[reportMissingImports]
from pound.graph.spatial import (  # pyright: ignore[reportMissingImports]
    GraphSpatialIndex,
    PoiSpatialIndex,
)
from starlette.concurrency import run_in_threadpool  # pyright: ignore[reportMissingImports]
from starlette.staticfiles import StaticFiles  # pyright: ignore[reportMissingImports]

from pound_web.api import router as api_router
from pound_web.boat_hire import load_boat_hire_seeds, snap_boat_hire_bases
from pound_web.config import WebSettings
from pound_web.places import MAX_PLACES_RESULTS, PlacesIndex


def _load_web_artifact(settings: WebSettings) -> RuntimeArtifact:
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
        app.state.gazetteer = artifact.gazetteer
        app.state.artifact_revision = artifact.metadata["artifact_revision"]
        app.state.settings = runtime_settings
        app.state.spatial_index = GraphSpatialIndex(artifact.graph)
        app.state.candidate_index = app.state.spatial_index.candidate_index
        app.state.poi_spatial_index = PoiSpatialIndex(artifact.pois)
        seeds = load_boat_hire_seeds(runtime_settings.boat_hire_enrichment_path)
        app.state.boat_hire_anchors = snap_boat_hire_bases(app.state.spatial_index, seeds)
        app.state.network_unavailable = not app.state.boat_hire_anchors

        app.state.catalog = None
        app.state.catalog_spatial_index = None
        app.state.catalog_error = None
        app.state.places_index = None
        app.state.places_status = "unavailable"
        if runtime_settings.catalog_path is not None:
            try:
                catalog = load_catalog(runtime_settings.catalog_path)
                app.state.catalog = catalog
                app.state.catalog_spatial_index = CatalogSpatialIndex(
                    catalog.places, app.state.spatial_index
                )
                app.state.places_index = PlacesIndex(
                    app.state.catalog_spatial_index,
                    app.state.spatial_index,
                    seeds,
                    max_kinds=runtime_settings.catalog_max_kinds,
                    max_radius_m=runtime_settings.catalog_max_radius_m,
                    max_viewport_span_deg=runtime_settings.catalog_max_viewport_span_deg,
                    max_vertices=runtime_settings.catalog_max_route_vertices,
                    max_targets=runtime_settings.places_max_targets,
                    max_work=runtime_settings.catalog_query_work_budget,
                    max_results=MAX_PLACES_RESULTS,
                )
                app.state.places_status = "available"
            except Exception as exc:
                app.state.catalog_error = str(exc)
        yield

    application = FastAPI(lifespan=lifespan)
    application.include_router(api_router)

    @application.exception_handler(RequestValidationError)
    async def places_request_validation_error(
        request: Request,
        exc: RequestValidationError,
    ):
        if request.url.path == "/api/canal-route":
            fields = sorted(
                {
                    str(error["loc"][1])
                    for error in exc.errors()
                    if len(error["loc"]) > 1
                    and error["loc"][1] in {"start", "end"}
                    and (error["type"] != "missing" or len(error["loc"]) > 2)
                }
            )
            if fields:
                return JSONResponse(
                    status_code=400,
                    content={
                        "detail": {
                            "code": "invalid_node_handle",
                            "message": "One or more canal node handles do not exist.",
                            "fields": fields,
                        }
                    },
                )

        if request.url.path != "/api/places":
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
                    "code": "invalid_places_query",
                    "message": "Invalid places query.",
                    "fields": fields,
                }
            },
        )

    @application.get("/api/health")
    async def health(request: Request) -> dict[str, str]:
        catalog_configured = request.app.state.settings.catalog_path is not None
        status = "healthy"
        if catalog_configured and request.app.state.places_status != "available":
            status = "degraded"
        return {
            "status": status,
            "artifact_revision": request.app.state.artifact_revision,
            "places_status": request.app.state.places_status,
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
