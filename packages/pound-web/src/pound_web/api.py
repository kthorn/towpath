"""HTTP API for candidate selection and pure artifact-backed routing."""

import threading
from collections import OrderedDict

import networkx as nx
from fastapi import APIRouter, HTTPException, Request  # pyright: ignore[reportMissingImports]
from pound.models import RETAINED_POI_KINDS  # pyright: ignore[reportMissingImports]
from pound.route.candidates import nearest_candidates  # pyright: ignore[reportMissingImports]
from pound.route.cost import resolve_movable_bridge_delay  # pyright: ignore[reportMissingImports]
from pound.route.plan import (  # pyright: ignore[reportMissingImports]
    RouteUnavailableError,
    plan_projected_route,
)
from pound.schemas import (  # pyright: ignore[reportMissingImports]
    BoatHireBase,
    CanalCandidatesResponse,
    CanalNetworkResponse,
    CanalPointHandle,
    CanalRouteResponse,
    Coordinate,
    PlacesRequest,
    PlacesResponse,
    ProjectedRouteConstraints,
    RoutePoisRequest,
    RoutePoisResponse,
)
from pydantic import (  # pyright: ignore[reportMissingImports]
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    field_validator,
)

from pound_web.boat_hire import select_boat_hire_reachability
from pound_web.config import MAX_NETWORK_TRAVEL_MINUTES
from pound_web.network import prepare_network_geometry
from pound_web.places import PlacesQueryBudgetError, PlacesResultLimitError

# ponytail: process-global LRUs of computed reachability geometry; per-app caches if apps
# with different artifacts share a process.
_NETWORK_UNION_CACHE_MAX = 8
_NETWORK_HIGHLIGHT_CACHE_MAX = 32
_network_union_cache: OrderedDict[tuple, tuple] = OrderedDict()
_network_highlight_cache: OrderedDict[tuple, tuple] = OrderedDict()
_network_geometry_lock = threading.Lock()


def clear_network_geometry_caches() -> None:
    """Clear process-global geometry cache entries between application lifespans."""
    with _network_geometry_lock:
        _network_union_cache.clear()
        _network_highlight_cache.clear()


router = APIRouter(prefix="/api")


class CanalCandidatesRequest(BaseModel):
    """Coordinate used to find nearby canal graph nodes."""

    model_config = ConfigDict(extra="forbid", strict=True)

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class CanalNetworkRequest(BaseModel):
    """Strict schedule and boat constraints for a bounded network overlay."""

    model_config = ConfigDict(extra="forbid", strict=True)

    days: int = Field(gt=0, le=365)
    hours_per_day: FiniteFloat = Field(gt=0, le=24)
    boat_length_m: FiniteFloat | None = Field(gt=0, default=None)
    boat_beam_m: FiniteFloat | None = Field(gt=0, default=None)
    boat_draft_m: FiniteFloat | None = Field(gt=0, default=None)
    boat_height_m: FiniteFloat | None = Field(gt=0, default=None)
    movable_bridge_delay_min: FiniteFloat | None = Field(ge=0, default=None)
    selected_base_identity: str | None = Field(default=None, min_length=1)


class CanalRouteRequest(BaseModel):
    """Artifact-scoped node handles and constraints accepted by the route API."""

    model_config = ConfigDict(extra="forbid", strict=True)

    start: CanalPointHandle
    end: CanalPointHandle
    artifact_revision: str
    days: int | None = Field(gt=0, default=None)
    hours_per_day: FiniteFloat = Field(gt=0, default=6.0)
    movable_bridge_delay_min: FiniteFloat | None = Field(ge=0, default=None)
    boat_length_m: FiniteFloat | None = Field(gt=0, default=None)
    boat_beam_m: FiniteFloat | None = Field(gt=0, default=None)
    boat_draft_m: FiniteFloat | None = Field(gt=0, default=None)
    boat_height_m: FiniteFloat | None = Field(gt=0, default=None)

    @field_validator("start", "end", mode="before")
    @classmethod
    def reject_coercible_handle_values(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        edge = value.get("edge")
        fraction = value.get("fraction")
        if isinstance(edge, (list, tuple)) and (
            len(edge) != 2 or any(type(uid) is not int for uid in edge)
        ):
            raise ValueError("edge must contain two integer UIDs")
        if "fraction" in value and (
            isinstance(fraction, bool) or type(fraction) not in (int, float)
        ):
            raise ValueError("fraction must be numeric")
        return value


class APIError(BaseModel):
    """Stable application error payload returned inside FastAPI ``detail``."""

    code: str
    message: str
    fields: list[str] = Field(default_factory=list)


def _error(status_code: int, *, code: str, message: str, fields: list[str] | None = None):
    detail = APIError(code=code, message=message, fields=fields or [])
    return HTTPException(status_code=status_code, detail=detail.model_dump())


def _network_lines(graph: nx.Graph, reachability) -> tuple:
    if isinstance(reachability, nx.Graph):
        return prepare_network_geometry(reachability)
    return prepare_network_geometry(
        graph,
        reachability.full_edge_keys,
        reachability.clipped_lines,
    )


@router.post("/canal-network", response_model=CanalNetworkResponse)
def canal_network(body: CanalNetworkRequest, request: Request) -> CanalNetworkResponse:
    """Return the canal network reachable on a return trip from active hire bases."""

    if request.app.state.network_unavailable:
        raise _error(
            503,
            code="network_unavailable",
            message="The canal network overlay is unavailable.",
        )

    travel_minutes = body.days * body.hours_per_day * 60
    if travel_minutes > MAX_NETWORK_TRAVEL_MINUTES:
        raise _error(
            413,
            code="network_query_budget_exceeded",
            message="The requested travel time exceeds the network overlay limit.",
            fields=["days", "hours_per_day"],
        )

    selected_anchors = ()
    if body.selected_base_identity is not None:
        selected_anchors = tuple(
            anchor
            for anchor in request.app.state.boat_hire_anchors
            if anchor.seed.identity == body.selected_base_identity
        )
        if not selected_anchors:
            raise _error(
                422,
                code="selected_base_not_found",
                message="The selected boat-hire base is unavailable.",
                fields=["selected_base_identity"],
            )

    cutoff_min = travel_minutes / 2
    delay_min = resolve_movable_bridge_delay(body.movable_bridge_delay_min)
    cache_key = (
        request.app.state.artifact_revision,
        cutoff_min,
        body.boat_length_m,
        body.boat_beam_m,
        body.boat_draft_m,
        body.boat_height_m,
        delay_min,
    )
    with _network_geometry_lock:
        lines = _network_union_cache.get(cache_key)
        if lines is not None:
            _network_union_cache.move_to_end(cache_key)
    if lines is None:
        try:
            lines = _network_lines(
                request.app.state.graph,
                select_boat_hire_reachability(
                    request.app.state.graph,
                    request.app.state.boat_hire_anchors,
                    cutoff_min=cutoff_min,
                    boat_length_m=body.boat_length_m,
                    boat_beam_m=body.boat_beam_m,
                    boat_draft_m=body.boat_draft_m,
                    boat_height_m=body.boat_height_m,
                    movable_bridge_delay_min=delay_min,
                ),
            )
        except Exception as exc:
            raise _error(
                503,
                code="network_unavailable",
                message="The canal network overlay is unavailable.",
            ) from exc
        with _network_geometry_lock:
            _network_union_cache[cache_key] = lines
            _network_union_cache.move_to_end(cache_key)
            while len(_network_union_cache) > _NETWORK_UNION_CACHE_MAX:
                _network_union_cache.popitem(last=False)

    if selected_anchors:
        highlight_key = (*cache_key, body.selected_base_identity)
        with _network_geometry_lock:
            highlight_lines = _network_highlight_cache.get(highlight_key)
            if highlight_lines is not None:
                _network_highlight_cache.move_to_end(highlight_key)
        if highlight_lines is None:
            try:
                highlight_lines = _network_lines(
                    request.app.state.graph,
                    select_boat_hire_reachability(
                        request.app.state.graph,
                        selected_anchors,
                        cutoff_min=cutoff_min,
                        boat_length_m=body.boat_length_m,
                        boat_beam_m=body.boat_beam_m,
                        boat_draft_m=body.boat_draft_m,
                        boat_height_m=body.boat_height_m,
                        movable_bridge_delay_min=delay_min,
                    ),
                )
            except Exception as exc:
                raise _error(
                    503,
                    code="network_unavailable",
                    message="The canal network overlay is unavailable.",
                ) from exc
            with _network_geometry_lock:
                _network_highlight_cache[highlight_key] = highlight_lines
                _network_highlight_cache.move_to_end(highlight_key)
                while len(_network_highlight_cache) > _NETWORK_HIGHLIGHT_CACHE_MAX:
                    _network_highlight_cache.popitem(last=False)
    else:
        highlight_lines = ()

    bases = [
        BoatHireBase(
            identity=anchor.seed.identity,
            operator=anchor.seed.operator,
            name=anchor.seed.name,
            coordinate=Coordinate(lat=anchor.seed.latitude, lon=anchor.seed.longitude),
        )
        for anchor in request.app.state.boat_hire_anchors
    ]
    return CanalNetworkResponse(
        artifact_revision=request.app.state.artifact_revision,
        lines=list(lines),
        highlight_lines=list(highlight_lines),
        bases=bases,
    )


@router.post("/canal-candidates", response_model=CanalCandidatesResponse)
def canal_candidates(body: CanalCandidatesRequest, request: Request) -> CanalCandidatesResponse:
    """Return tuned, spaced graph candidates nearest to a map coordinate."""

    revision = request.app.state.artifact_revision
    settings = request.app.state.settings
    candidates = nearest_candidates(
        body.lat,
        body.lon,
        request.app.state.candidate_index,
        limit=settings.candidate_pool_size,
    )[: settings.google_destination_limit]
    return CanalCandidatesResponse(artifact_revision=revision, candidates=candidates)


@router.post("/route-pois", response_model=RoutePoisResponse)
def route_pois(body: RoutePoisRequest, request: Request) -> RoutePoisResponse:
    """Return selected POIs within the current viewport and route corridor."""

    if body.artifact_revision != request.app.state.artifact_revision:
        raise _error(
            409,
            code="artifact_revision_mismatch",
            message="The routing artifact has changed; refresh the route.",
            fields=["artifact_revision"],
        )
    if body.bounds.south > body.bounds.north or body.bounds.west > body.bounds.east:
        raise _error(
            400,
            code="invalid_bounds",
            message="Bounds must be ordered south <= north and west <= east.",
            fields=["bounds"],
        )
    if set(body.kinds) - RETAINED_POI_KINDS:
        raise _error(
            400,
            code="invalid_poi_kind",
            message="One or more POI kinds do not exist in this artifact.",
            fields=["kinds"],
        )
    poi_index = request.app.state.poi_spatial_index
    result = poi_index.query(
        body.bounds,
        body.day_geometry or body.route_geometry,
        tuple(body.kinds),
    )
    return RoutePoisResponse(
        pois=list(result.pois),
        zoom_in_required=result.zoom_in_required,
        matching_count=result.matching_count,
        day=body.day,
    )


@router.post("/places", response_model=PlacesResponse)
def places(body: PlacesRequest, request: Request) -> PlacesResponse:
    """Return bounded places from the independent OSM and boat-hire sources."""

    if request.app.state.places_status != "available":
        raise _error(503, code="places_unavailable", message="Places are unavailable.")
    try:
        return request.app.state.places_index.query(body)  # pi-lens-ignore: python-sql-injection
    except PlacesResultLimitError as exc:
        raise _error(
            413,
            code="places_result_limit_exceeded",
            message="The places result limit was exceeded; narrow the query.",
            fields=exc.fields,
        ) from exc
    except PlacesQueryBudgetError as exc:
        raise _error(
            413,
            code="places_query_budget_exceeded",
            message="The places query exceeds its configured budget.",
            fields=exc.fields,
        ) from exc


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
    invalid_fields = [
        field
        for field, handle in (("start", body.start), ("end", body.end))
        if not graph.has_edge(*handle.edge)
        or (
            0 < handle.fraction < 1
            and graph.edges[handle.edge].get("candidate_eligible", True) is False
        )
    ]
    if invalid_fields:
        raise _error(
            400,
            code="invalid_node_handle",
            message="One or more canal node handles do not exist.",
            fields=invalid_fields,
        )

    constraints = ProjectedRouteConstraints(
        start=body.start,
        end=body.end,
        days=body.days,
        hours_per_day=body.hours_per_day,
        movable_bridge_delay_min=body.movable_bridge_delay_min,
        boat_length_m=body.boat_length_m,
        boat_beam_m=body.boat_beam_m,
        boat_draft_m=body.boat_draft_m,
        boat_height_m=body.boat_height_m,
    )
    try:
        return plan_projected_route(constraints, artifact=request.app.state.artifact)
    except RouteUnavailableError as exc:
        raise _error(422, code="route_unavailable", message=str(exc)) from exc
