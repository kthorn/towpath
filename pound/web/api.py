"""HTTP API for candidate selection and pure artifact-backed routing."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from pound.catalog.manifest import CATALOG_KINDS
from pound.catalog.spatial import CatalogQueryLimitError
from pound.ingest.pois import RETAINED_POI_KINDS
from pound.route.candidates import nearest_coord_candidates, select_spaced_candidates
from pound.route.plan import RouteUnavailableError, plan_canal_route
from pound.schemas import (
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


class APIError(BaseModel):
    """Stable application error payload returned inside FastAPI ``detail``."""

    code: str
    message: str
    fields: list[str] = Field(default_factory=list)


def _error(status_code: int, *, code: str, message: str, fields: list[str] | None = None):
    detail = APIError(code=code, message=message, fields=fields or [])
    return HTTPException(status_code=status_code, detail=detail.model_dump())


@router.get("/canal-network", response_model=CanalNetworkResponse)
def canal_network(request: Request) -> CanalNetworkResponse:
    """Return the startup-prepared full canal network overlay."""

    if request.app.state.network_error is not None:
        raise _error(
            503,
            code="network_unavailable",
            message="The canal network overlay is unavailable.",
        )
    return CanalNetworkResponse(
        artifact_revision=request.app.state.artifact_revision,
        lines=list(request.app.state.network_lines),
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
        for geometry in (body.route_geometry, body.day_geometry)
        if geometry is not None
    )
    if coordinate_count > settings.catalog_max_route_vertices:
        raise _error(
            413,
            code="catalog_query_budget_exceeded",
            message="The catalog geometry exceeds the configured vertex budget.",
            fields=["route_geometry", "day_geometry"],
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
    try:
        result = catalog_index.query(body)
    except CatalogQueryLimitError as exc:
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

    places = [
        CatalogPlaceResponse(
            identity=f"{place.osm_type.value}/{place.osm_id}/{place.kind}",
            kind=place.kind,
            name=place.name,
            coordinate=Coordinate(lat=place.lat, lon=place.lon),
            waterway_distance_m=result.waterway_distances[index],
            distance_to_full_route_m=result.full_route_distances[index],
            distance_to_selected_geometry_m=result.selected_geometry_distances[index],
            metadata=place.metadata,
        )
        for index, place in enumerate(result.places)
    ]
    return CatalogPlacesResponse(
        catalog_revision=request.app.state.catalog_revision,
        places=places,
        matching_count=result.matching_count,
        over_cap=result.over_cap,
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
        boat_length_m=body.boat_length_m,
        boat_beam_m=body.boat_beam_m,
        boat_draft_m=body.boat_draft_m,
        boat_height_m=body.boat_height_m,
    )
    try:
        return plan_canal_route(constraints, graph=graph)
    except RouteUnavailableError as exc:
        raise _error(422, code="route_unavailable", message=str(exc)) from exc
