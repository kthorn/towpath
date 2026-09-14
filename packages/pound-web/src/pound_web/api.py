"""HTTP API for candidate selection and pure artifact-backed routing."""

import hashlib
import math
import threading
from collections import OrderedDict
from typing import Annotated, Literal

import networkx as nx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response  # pyright: ignore[reportMissingImports]
from pound.geometry import haversine_m as _haversine_m  # pyright: ignore[reportMissingImports]
from pound.models import RETAINED_POI_KINDS  # pyright: ignore[reportMissingImports]
from pound.route.candidates import nearest_candidates  # pyright: ignore[reportMissingImports]
from pound.route.cost import resolve_movable_bridge_delay  # pyright: ignore[reportMissingImports]
from pound.route.hire_reachability import (
    HireReachabilityError,
    compute_hire_base_reachability,
)
from pound.route.plan import (  # pyright: ignore[reportMissingImports]
    RouteUnavailableError,
    plan_projected_route,
)
from pound.route.round_trip import RoundTripError, discover_round_trips, plan_out_and_back
from pound.schemas import (
    BoatHireBase,
    CanalCandidatesResponse,
    CanalNetworkResponse,
    CanalPointHandle,
    CanalRouteResponse,
    ClimateLocationResponse,
    ClimateLocationsResponse,
    Coordinate,
    OutAndBackRoute,
    OutAndBackRouteRequest,
    PlacesRequest,
    PlacesResponse,
    ProjectedRouteConstraints,
    RoutePoisRequest,
    RoutePoisResponse,
    TurnaroundCandidatesRequest,  # pyright: ignore[reportMissingImports]
    TurnaroundCandidatesResponse,
)
from pydantic import (  # pyright: ignore[reportMissingImports]
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    field_validator,
    model_validator,
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


class HireBasesRequest(BaseModel):
    """Strict bounded query for source-backed boat-hire bases."""

    model_config = ConfigDict(extra="forbid", strict=True)

    lat: FiniteFloat = Field(ge=-90, le=90)
    lon: FiniteFloat = Field(ge=-180, le=180)
    limit: int = Field(default=6, ge=1, le=20)
    offset: int = Field(default=0, ge=0, le=1000)
    radius_km: FiniteFloat = Field(default=100.0, ge=1, le=250)
    target: CanalPointHandle | None = None
    artifact_revision: str | None = Field(default=None, min_length=1)
    days: int | None = Field(default=None, gt=0, le=365)
    hours_per_day: FiniteFloat = Field(default=6.0, gt=0, le=24)
    movable_bridge_delay_min: FiniteFloat | None = Field(default=None, ge=0)
    boat_length_m: FiniteFloat | None = Field(default=None, gt=0)
    boat_beam_m: FiniteFloat | None = Field(default=None, gt=0)
    boat_draft_m: FiniteFloat | None = Field(default=None, gt=0)
    boat_height_m: FiniteFloat | None = Field(default=None, gt=0)

    @field_validator(
        "lat",
        "lon",
        "radius_km",
        "hours_per_day",
        "movable_bridge_delay_min",
        "boat_length_m",
        "boat_beam_m",
        "boat_draft_m",
        "boat_height_m",
        mode="before",
    )
    @classmethod
    def reject_nonfinite_values(cls, value: object) -> object:
        # Keep FastAPI's JSON validation response serializable when a non-standard
        # JSON parser accepts NaN or Infinity before Pydantic sees it.
        if isinstance(value, float) and not math.isfinite(value):
            return repr(value)
        return value

    @model_validator(mode="after")
    def require_network_constraints(self):
        if self.target is not None and (self.artifact_revision is None or self.days is None):
            raise ValueError("target requires artifact_revision and days")
        return self


class HireBaseResponse(BaseModel):
    """Published source-provider base details and its artifact projection."""

    base_ref: str
    name: str
    provider_name: str
    provider_id: str
    coordinate: Coordinate
    straight_line_distance_m: FiniteFloat = Field(ge=0)
    one_way_minutes: FiniteFloat | None = Field(default=None, ge=0)
    return_minutes: FiniteFloat | None = Field(default=None, ge=0)
    handle: CanalPointHandle
    canal_coordinate: Coordinate
    snap_distance_m: FiniteFloat = Field(ge=0)
    provider_url: str | None = None
    evidence_url: str | None = None
    booking_url: str | None = None


class HireBasesResponse(BaseModel):
    """Bounded source-backed boat-hire base results."""

    artifact_revision: str
    total_matches: int = Field(ge=0)
    truncated: bool
    next_offset: int | None = Field(default=None, ge=0)
    budget_minutes: FiniteFloat | None = Field(default=None, ge=0)
    cutoff_minutes: FiniteFloat | None = Field(default=None, ge=0)
    ranking_basis: Literal["straight_line_distance", "canal_travel_time"] = (
        "straight_line_distance"
    )
    bases: list[HireBaseResponse]


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


@router.post("/hire-bases", response_model=HireBasesResponse)
def hire_bases(body: HireBasesRequest, request: Request) -> HireBasesResponse:
    """Return nearby published source-provider bases with runtime projections."""

    public_anchors = tuple(
        anchor
        for anchor in request.app.state.boat_hire_anchors
        if anchor.seed.is_public_place
    )
    ranking_basis: Literal["straight_line_distance", "canal_travel_time"]
    budget_minutes: float | None = None
    cutoff_minutes: float | None = None
    if body.target is not None:
        if body.artifact_revision != request.app.state.artifact_revision:
            raise _error(
                409,
                code="artifact_revision_mismatch",
                message="The routing artifact has changed; refresh the canal waypoint.",
                fields=["artifact_revision"],
            )
        ranking_basis = "canal_travel_time"
        budget_minutes = body.days * body.hours_per_day * 60
        cutoff_minutes = budget_minutes / 2
        matches = []
        if public_anchors:
            try:
                matches = [
                    (match.one_way_minutes, match.identity, match.anchor, match)
                    for match in compute_hire_base_reachability(
                        body.target,
                        public_anchors,
                        graph=request.app.state.graph,
                        cutoff_min=cutoff_minutes,
                        boat_length_m=body.boat_length_m,
                        boat_beam_m=body.boat_beam_m,
                        boat_draft_m=body.boat_draft_m,
                        boat_height_m=body.boat_height_m,
                        movable_bridge_delay_min=body.movable_bridge_delay_min,
                    )
                ]
            except HireReachabilityError as exc:
                raise _error(413, code=exc.code, message=exc.message) from exc
            except ValueError as exc:
                raise _error(
                    400,
                    code="invalid_hire_target",
                    message="The canal waypoint is not valid for this routing artifact.",
                    fields=["target"],
                ) from exc
        matches.sort(key=lambda match: (match[0], match[1]))
    else:
        ranking_basis = "straight_line_distance"
        radius_m = body.radius_km * 1000.0
        matches = []
        for anchor in public_anchors:
            seed = anchor.seed
            distance_m = _haversine_m((body.lat, body.lon), (seed.latitude, seed.longitude))
            if distance_m <= radius_m:
                matches.append((distance_m, seed.identity, anchor, None))
        matches.sort(key=lambda match: (match[0], match[1]))

    total_matches = len(matches)
    page_end = body.offset + body.limit
    bases = []
    for _distance_or_minutes, _identity, anchor, reachability in matches[body.offset:page_end]:
        seed = anchor.seed
        distance_m = _haversine_m((body.lat, body.lon), (seed.latitude, seed.longitude))
        bases.append(
            HireBaseResponse(
                base_ref=seed.identity,
                name=seed.name,
                provider_name=seed.operator,
                provider_id=seed.source_provider_id,
                coordinate=Coordinate(lat=seed.latitude, lon=seed.longitude),
                straight_line_distance_m=distance_m,
                one_way_minutes=(
                    reachability.one_way_minutes if reachability is not None else None
                ),
                return_minutes=(
                    reachability.return_minutes if reachability is not None else None
                ),
                handle=anchor.handle,
                canal_coordinate=anchor.projected,
                snap_distance_m=anchor.snap_distance_m,
                provider_url=seed.source_provider_website or None,
                evidence_url=seed.evidence_url or None,
                booking_url=seed.booking_url or None,
            )
        )
    return HireBasesResponse(
        artifact_revision=request.app.state.artifact_revision,
        total_matches=total_matches,
        truncated=page_end < total_matches,
        next_offset=page_end if page_end < total_matches else None,
        budget_minutes=budget_minutes,
        cutoff_minutes=cutoff_minutes,
        ranking_basis=ranking_basis,
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


def _climate_data(request: Request) -> dict:
    data = getattr(request.app.state, "climate", None)
    if data is None:
        raise _error(
            503, code="climate_unavailable", message="Historical temperatures are unavailable."
        )
    return data


def _climate_response(request: Request, data: dict, key: str) -> Response:
    # Include the representation key: a week or period change must not reuse another ETag.
    tag = '"' + hashlib.sha256(f"{data['revision']}:{key}".encode()).hexdigest() + '"'
    headers = {"ETag": tag, "Cache-Control": "public, max-age=0, must-revalidate"}
    matches = request.headers.get("if-none-match", "").split(",")
    if any(value.strip().removeprefix("W/") in (tag, "*") for value in matches):
        return Response(status_code=304, headers=headers)
    return JSONResponse(data, headers=headers)


@router.get("/climate/locations", response_model=ClimateLocationsResponse)
def climate_locations(
    request: Request,
    week_id: Annotated[int, Query(ge=0, le=17)] = 8,
    period_years: Annotated[int, Query()] = 25,
    metric: Literal["high", "low"] = "high",
) -> Response:
    """Return bounded named-location summaries without distribution sample arrays."""
    if period_years not in (5, 25):
        raise HTTPException(status_code=422, detail="period_years must be 5 or 25")
    artifact = _climate_data(request)
    locations = []
    for location in artifact["locations"]:
        week = location["weeks"][week_id]
        distribution = week[metric][str(period_years)]
        locations.append(
            {
                "id": location["id"],
                "name": location["name"],
                "coordinate": location["coordinate"],
                "distribution": {k: v for k, v in distribution.items() if k != "samples"},
            }
        )
    from pound.climate.calendar import week_label

    payload = {
        "revision": artifact["revision"],
        "end_year": artifact["end_year"],
        "source": artifact["source"],
        "week_id": week_id,
        "week_label": week_label(week_id),
        "period_years": period_years,
        "metric": metric,
        "locations": locations,
    }
    return _climate_response(
        request,
        ClimateLocationsResponse.model_validate(payload).model_dump(mode="json"),
        f"list:{week_id}:{period_years}:{metric}",
    )


@router.get("/climate/locations/{location_id}", response_model=ClimateLocationResponse)
def climate_location(
    location_id: str,
    request: Request,
    week_id: Annotated[int, Query(ge=0, le=17)] = 8,
) -> Response:
    """Return both historical periods and metrics for one supported location."""
    artifact = _climate_data(request)
    location = next((loc for loc in artifact["locations"] if loc["id"] == location_id), None)
    if location is None:
        raise _error(404, code="climate_location_not_found", message="Climate location not found.")
    week = location["weeks"][week_id]
    payload = {
        "revision": artifact["revision"],
        "end_year": artifact["end_year"],
        "source": artifact["source"],
        "week_id": week_id,
        "week_label": week["label"],
        "location": {k: v for k, v in location.items() if k != "weeks"},
        "high": week["high"],
        "low": week["low"],
    }
    return _climate_response(
        request,
        ClimateLocationResponse.model_validate(payload).model_dump(mode="json"),
        f"detail:{location_id}:{week_id}",
    )


def _check_round_trip_revision(body: TurnaroundCandidatesRequest, request: Request) -> None:
    if body.artifact_revision != request.app.state.artifact_revision:
        raise _error(
            409,
            code="artifact_revision_mismatch",
            message="The routing artifact has changed; refresh turnaround candidates.",
            fields=["artifact_revision"],
        )


def _round_trip_limits(request: Request) -> dict[str, int]:
    """Read optional bounded-search settings without coupling the API to config shape."""

    settings = getattr(request.app.state, "settings", None)
    limits = {
        "max_work": getattr(settings, "round_trip_max_work", None),
        "max_routes": getattr(settings, "round_trip_max_routes", None),
        "max_vertices": getattr(settings, "round_trip_max_vertices", None),
    }
    return {name: value for name, value in limits.items() if value is not None}


@router.post("/turnaround-candidates", response_model=TurnaroundCandidatesResponse)
def turnaround_candidates(
    body: TurnaroundCandidatesRequest,
    request: Request,
) -> TurnaroundCandidatesResponse:
    """Enumerate complete feasible out-and-back route alternatives."""

    _check_round_trip_revision(body, request)
    try:
        return discover_round_trips(
            body,
            graph=request.app.state.graph,
            **_round_trip_limits(request),
        )
    except RoundTripError as exc:
        raise _round_trip_error(exc) from exc


@router.post("/out-and-back-route", response_model=OutAndBackRoute)
def out_and_back_route(body: OutAndBackRouteRequest, request: Request) -> OutAndBackRoute:
    """Return the default or exact selected out-and-back route."""

    _check_round_trip_revision(body, request)
    try:
        return plan_out_and_back(
            body,
            graph=request.app.state.graph,
            **_round_trip_limits(request),
        )
    except RoundTripError as exc:
        raise _round_trip_error(exc) from exc


def _round_trip_error(exc: RoundTripError) -> HTTPException:
    detail = {"code": exc.code, "message": exc.message, "fields": exc.fields}
    if exc.rejections:
        detail["rejections"] = [
            r.model_dump() if hasattr(r, "model_dump") else r for r in exc.rejections
        ]
    return HTTPException(status_code=exc.status, detail=detail)
