"""FastAPI application factory and production entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

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

    return application


app = create_app()
