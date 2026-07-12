"""FastAPI application factory and production entry point."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from stat import S_ISREG

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from starlette.staticfiles import StaticFiles

from pound.graph.artifact import load_artifact
from pound.web.api import router as api_router
from pound.web.config import WebSettings


def _load_web_artifact(settings: WebSettings) -> tuple[object, dict]:
    """Load and validate the artifact fields required by the web application."""

    path = settings.artifact_path
    try:
        graph, metadata = load_artifact(path)
    except KeyError as exc:
        missing = exc.args[0] if exc.args else "required field"
        raise RuntimeError(f"Artifact {path} is missing {missing}") from exc
    except Exception as exc:
        raise RuntimeError(f"Could not load routing artifact {path}: {exc}") from exc

    if graph is None:
        raise RuntimeError(f"Artifact {path} is missing graph")
    if not isinstance(metadata, dict):
        raise RuntimeError(f"Artifact {path} is missing metadata")
    if not metadata.get("artifact_revision"):
        raise RuntimeError(f"Artifact {path} is missing artifact_revision")
    return graph, metadata


def create_app(settings: WebSettings | None = None) -> FastAPI:
    """Create the Pound web application without loading its artifact yet."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime_settings = settings if settings is not None else WebSettings.from_env()
        graph, metadata = _load_web_artifact(runtime_settings)
        app.state.graph = graph
        app.state.metadata = metadata
        app.state.artifact_revision = metadata["artifact_revision"]
        app.state.settings = runtime_settings
        yield

    application = FastAPI(lifespan=lifespan)
    application.include_router(api_router)

    @application.get("/api/health")
    async def health(request: Request) -> dict[str, str]:
        return {
            "status": "healthy",
            "artifact_revision": request.app.state.artifact_revision,
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
