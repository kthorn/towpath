"""HTTP API for candidate selection and pure artifact-backed routing."""

from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Request  # pyright: ignore[reportMissingImports]
from pydantic import (  # pyright: ignore[reportMissingImports]
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
)
from shapely.geometry import LineString

from pound.catalog.manifest import CATALOG_KINDS
from pound.catalog.spatial import CatalogQueryLimitError, CatalogQueryPolicy, wgs84_to_bng
from pound.ingest.pois import RETAINED_POI_KINDS
from pound.route.candidates import nearest_coord_candidates, select_spaced_candidates
from pound.route.cost import resolve_movable_bridge_delay
from pound.route.plan import RouteUnavailableError, plan_canal_route
from pound.schemas import (
    BoatHireBase,
    CanalCandidatesResponse,
    CanalNetworkResponse,
    CanalRouteResponse,
    CatalogPlaceResponse,
    CatalogPlacesRequest,
    CatalogPlacesResponse,
    Coordinate,
    ResolvedConstraints,
    RoutePoisRequest,
    RoutePoisResponse,
)
from pound.web.boat_hire import select_boat_hire_reachability
from pound.web.config import MAX_NETWORK_TRAVEL_MINUTES
from pound.web.network import prepare_network_geometry
from pound.web.places import MAX_PLACES_RESULTS

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


class CanalRouteRequest(BaseModel):
    """Artifact-scoped node handles and constraints accepted by the route API."""

    model_config = ConfigDict(extra="forbid", strict=True)

    start_uid: int
    end_uid: int
    artifact_revision: str
    days: int | None = Field(gt=0, default=None)
    hours_per_day: FiniteFloat = Field(gt=0, default=6.0)
    movable_bridge_delay_min: FiniteFloat | None = Field(ge=0, default=None)
    boat_length_m: FiniteFloat | None = Field(gt=0, default=None)
    boat_beam_m: FiniteFloat | None = Field(gt=0, default=None)
    boat_draft_m: FiniteFloat | None = Field(gt=0, default=None)
    boat_height_m: FiniteFloat | None = Field(gt=0, default=None)


class APIError(BaseModel):
    """Stable application error payload returned inside FastAPI ``detail``."""

    code: str
    message: str
    fields: list[str] = Field(default_factory=list)


def _error(status_code: int, *, code: str, message: str, fields: list[str] | None = None):
    detail = APIError(code=code, message=message, fields=fields or [])
    return HTTPException(status_code=status_code, detail=detail.model_dump())


@router.post("/canal-network", response_model=CanalNetworkResponse)
def canal_network(body: CanalNetworkRequest, request: Request) -> CanalNetworkResponse:
    """Return the one-way, time-reachable canal network from active hire bases."""

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

    overlay_graph = select_boat_hire_reachability(
        request.app.state.graph,
        request.app.state.boat_hire_anchors,
        cutoff_min=travel_minutes,
        boat_length_m=body.boat_length_m,
        boat_beam_m=body.boat_beam_m,
        boat_draft_m=body.boat_draft_m,
        boat_height_m=body.boat_height_m,
        movable_bridge_delay_min=resolve_movable_bridge_delay(body.movable_bridge_delay_min),
    )
    try:
        lines = prepare_network_geometry(overlay_graph)
    except Exception as exc:
        raise _error(
            503,
            code="network_unavailable",
            message="The canal network overlay is unavailable.",
        ) from exc

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
        bases=bases,
    )


@router.post("/canal-candidates", response_model=CanalCandidatesResponse)
def canal_candidates(body: CanalCandidatesRequest, request: Request) -> CanalCandidatesResponse:
    """Return tuned, spaced graph candidates nearest to a map coordinate."""

    graph = request.app.state.graph
    revision = request.app.state.artifact_revision
    settings = request.app.state.settings
    pool = nearest_coord_candidates(
        body.lat,
        body.lon,
        graph,
        request.app.state.spatial_index,
        artifact_revision=revision,
        limit=settings.candidate_pool_size,
    )
    candidates = select_spaced_candidates(
        pool,
        destination_limit=settings.google_destination_limit,
        minimum_spacing_m=settings.minimum_candidate_spacing_m,
    )
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


@router.post("/catalog-places", response_model=CatalogPlacesResponse)
def catalog_places(body: CatalogPlacesRequest, request: Request) -> CatalogPlacesResponse:
    """Return bounded independent catalog places for one explicit policy."""

    if request.app.state.catalog_status != "available":
        raise _error(
            503,
            code="catalog_unavailable",
            message="The place catalog is unavailable; route planning remains available.",
        )
    settings = request.app.state.settings
    if body.catalog_revision != request.app.state.catalog_revision:
        raise _error(
            409,
            code="catalog_revision_mismatch",
            message="The place catalog has changed; refresh catalog layers.",
            fields=["catalog_revision"],
        )
    if len(body.kinds) > settings.catalog_max_kinds:
        raise _error(
            413,
            code="catalog_query_budget_exceeded",
            message="The catalog query selects too many kinds.",
            fields=["kinds"],
        )
    if body.bounds.south > body.bounds.north or body.bounds.west > body.bounds.east:
        raise _error(
            400,
            code="invalid_bounds",
            message="Bounds must be ordered south <= north and west <= east.",
            fields=["bounds"],
        )
    unknown_kinds = set(body.kinds) - CATALOG_KINDS
    if unknown_kinds:
        raise _error(
            400,
            code="invalid_catalog_kind",
            message="One or more catalog kinds do not exist in this catalog.",
            fields=["kinds"],
        )
    viewport_span = max(
        body.bounds.north - body.bounds.south,
        body.bounds.east - body.bounds.west,
    )
    if viewport_span > settings.catalog_max_viewport_span_deg:
        raise _error(
            413,
            code="catalog_query_budget_exceeded",
            message="The catalog viewport exceeds the configured span budget.",
            fields=["bounds"],
        )
    if body.policy.radius_m is not None and body.policy.radius_m > settings.catalog_max_radius_m:
        raise _error(
            413,
            code="catalog_query_budget_exceeded",
            message="The catalog radius exceeds the configured query budget.",
            fields=["policy.radius_m"],
        )
    if (body.day is None) != (body.day_geometry is None) or (
        body.day_geometry is not None and body.route_geometry is None
    ):
        raise _error(
            400,
            code="invalid_catalog_geometry",
            message="day and day_geometry require route_geometry and must be supplied together.",
            fields=["day", "day_geometry", "route_geometry"],
        )
    coordinate_count = sum(
        len(geometry.coordinates)
        for geometry in (
            body.route_geometry,
            body.day_geometry,
            body.segment_geometry,
        )
        if geometry is not None
    )
    if coordinate_count > settings.catalog_max_route_vertices:
        raise _error(
            413,
            code="catalog_query_budget_exceeded",
            message="The catalog geometry exceeds the configured vertex budget.",
            fields=["route_geometry", "day_geometry", "segment_geometry"],
        )
    if body.policy.basis == "route" and body.route_geometry is None:
        raise _error(
            400,
            code="invalid_catalog_policy",
            message="A route policy requires route_geometry.",
            fields=["policy", "route_geometry"],
        )

    catalog_index = request.app.state.catalog_spatial_index
    if catalog_index.viewport_candidate_count(body.bounds) > settings.catalog_query_work_budget:
        raise _error(
            413,
            code="catalog_query_budget_exceeded",
            message="The catalog query exceeds the configured work budget.",
            fields=["bounds"],
        )
    is_segment_query = body.policy.basis == "segment"
    source_route_geometry = body.segment_geometry if is_segment_query else body.route_geometry
    route_bng = (
        wgs84_to_bng(LineString(source_route_geometry.coordinates))
        if source_route_geometry is not None
        else None
    )
    full_route_bng = (
        wgs84_to_bng(LineString(body.route_geometry.coordinates))
        if is_segment_query and body.route_geometry is not None
        else None
    )
    day_bng = (
        wgs84_to_bng(LineString(body.day_geometry.coordinates))
        if body.day_geometry is not None
        else None
    )
    source_basis = cast(
        Literal["route", "waterway", "none"],
        "route" if is_segment_query else body.policy.basis,
    )
    source_policy = CatalogQueryPolicy(source_basis, body.policy.radius_m)

    def query_source(*, policy, route_geometry, selected_geometry, result_budget):
        return catalog_index.query_viewport(
            kinds=frozenset(body.kinds),
            bounds=body.bounds,
            text=body.text,
            policy=policy,
            route_bng=route_geometry,
            day_bng=selected_geometry,
            work_budget=settings.catalog_query_work_budget,
            result_budget=result_budget,
        )

    context_result = None
    try:
        if is_segment_query and body.route_geometry is not None:
            context_result = query_source(
                policy=CatalogQueryPolicy("none", None),
                route_geometry=full_route_bng,
                selected_geometry=day_bng,
                result_budget=settings.catalog_query_work_budget,
            )
        result = query_source(
            policy=source_policy,
            route_geometry=route_bng,
            selected_geometry=None if is_segment_query else day_bng,
            result_budget=MAX_PLACES_RESULTS,
        )
    except CatalogQueryLimitError as exc:
        if exc.limit == "result":
            return CatalogPlacesResponse(
                catalog_revision=request.app.state.catalog_revision,
                places=[],
                matching_count=MAX_PLACES_RESULTS + 1,
                over_cap=True,
                day=body.day,
            )
        raise _error(
            413,
            code="catalog_query_budget_exceeded",
            message=str(exc),
            fields=["bounds"],
        ) from exc
    except ValueError as exc:
        raise _error(
            400,
            code="invalid_catalog_query",
            message=str(exc),
        ) from exc

    context_by_identity = (
        {match.place.identity: match for match in context_result.matches}
        if context_result is not None
        else {}
    )
    places = []
    for match in result.matches:
        context = context_by_identity.get(match.place.identity, match)
        places.append(
            CatalogPlaceResponse(
                identity=f"{match.place.osm_type.value}/{match.place.osm_id}/{match.place.kind}",
                kind=match.place.kind,
                name=match.place.name,
                coordinate=Coordinate(lat=match.place.lat, lon=match.place.lon),
                waterway_distance_m=(
                    context.waterway_distance_m
                    if not is_segment_query or context_result is not None
                    else None
                ),
                distance_to_full_route_m=(
                    context.full_route_distance_m
                    if not is_segment_query or context_result is not None
                    else None
                ),
                distance_to_segment_m=match.full_route_distance_m if is_segment_query else None,
                distance_to_selected_geometry_m=(
                    context.selected_geometry_distance_m
                    if not is_segment_query or context_result is not None
                    else None
                ),
                metadata=match.place.metadata,
            )
        )
    return CatalogPlacesResponse(
        catalog_revision=request.app.state.catalog_revision,
        places=places,
        matching_count=len(result.matches),
        over_cap=False,
        day=body.day,
    )


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
        movable_bridge_delay_min=body.movable_bridge_delay_min,
        boat_length_m=body.boat_length_m,
        boat_beam_m=body.boat_beam_m,
        boat_draft_m=body.boat_draft_m,
        boat_height_m=body.boat_height_m,
    )
    try:
        return plan_canal_route(constraints, graph=graph)
    except RouteUnavailableError as exc:
        raise _error(422, code="route_unavailable", message=str(exc)) from exc
