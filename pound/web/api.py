"""HTTP API for candidate selection and pure artifact-backed routing."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from pound.route.candidates import nearest_coord_candidates, select_spaced_candidates
from pound.route.plan import RouteUnavailableError, plan_canal_route
from pound.schemas import CanalCandidatesResponse, CanalRouteResponse, ResolvedConstraints

router = APIRouter(prefix="/api")


class CanalCandidatesRequest(BaseModel):
    """Coordinate used to find nearby canal graph nodes."""

    model_config = ConfigDict(extra="forbid", strict=True)

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class CanalRouteRequest(BaseModel):
    """Artifact-scoped node handles and constraints accepted by the route API."""

    model_config = ConfigDict(extra="forbid", strict=True)

    start_uid: int
    end_uid: int
    artifact_revision: str
    days: int | None = Field(gt=0, default=None)
    hours_per_day: float = Field(gt=0, default=6.0)
    boat_length_m: float | None = Field(gt=0, default=None)
    boat_beam_m: float | None = Field(gt=0, default=None)
    boat_draft_m: float | None = Field(gt=0, default=None)
    boat_height_m: float | None = Field(gt=0, default=None)
    allow_derelict: bool = False


class APIError(BaseModel):
    """Stable application error payload returned inside FastAPI ``detail``."""

    code: str
    message: str
    fields: list[str] = Field(default_factory=list)


def _error(status_code: int, *, code: str, message: str, fields: list[str] | None = None):
    detail = APIError(code=code, message=message, fields=fields or [])
    return HTTPException(status_code=status_code, detail=detail.model_dump())


@router.post("/canal-candidates", response_model=CanalCandidatesResponse)
def canal_candidates(
    body: CanalCandidatesRequest, request: Request
) -> CanalCandidatesResponse:
    """Return tuned, spaced graph candidates nearest to a map coordinate."""

    graph = request.app.state.graph
    revision = request.app.state.artifact_revision
    settings = request.app.state.settings
    pool = nearest_coord_candidates(
        body.lat,
        body.lon,
        graph,
        artifact_revision=revision,
        limit=settings.candidate_pool_size,
    )
    candidates = select_spaced_candidates(
        pool,
        destination_limit=settings.google_destination_limit,
        minimum_spacing_m=settings.minimum_candidate_spacing_m,
    )
    return CanalCandidatesResponse(artifact_revision=revision, candidates=candidates)


@router.post("/canal-route", response_model=CanalRouteResponse)
def canal_route(body: CanalRouteRequest, request: Request) -> CanalRouteResponse:
    """Route between two graph handles from the client's artifact revision."""

    revision = request.app.state.artifact_revision
    if body.artifact_revision != revision:
        raise _error(
            409,
            code="artifact_revision_mismatch",
            message="The routing artifact has changed; refresh canal candidates.",
            fields=["artifact_revision"],
        )

    graph = request.app.state.graph
    missing_fields = [
        field
        for field, uid in (("start_uid", body.start_uid), ("end_uid", body.end_uid))
        if uid not in graph
    ]
    if missing_fields:
        raise _error(
            400,
            code="invalid_node_handle",
            message="One or more canal node handles do not exist.",
            fields=missing_fields,
        )

    constraints = ResolvedConstraints(
        start_uid=body.start_uid,
        end_uid=body.end_uid,
        days=body.days,
        hours_per_day=body.hours_per_day,
        boat_length_m=body.boat_length_m,
        boat_beam_m=body.boat_beam_m,
        boat_draft_m=body.boat_draft_m,
        boat_height_m=body.boat_height_m,
        allow_derelict=body.allow_derelict,
    )
    try:
        return plan_canal_route(constraints, graph=graph)
    except RouteUnavailableError as exc:
        raise _error(422, code="route_unavailable", message=str(exc)) from exc
