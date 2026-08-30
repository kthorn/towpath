"""Shared Pydantic models — the frozen contract Pound and the Agent Core both import.

Per design §6. Field names are the integration seam; do not rename without
coordinating with labyrinth-core / labyrinth-agent.
"""

import math
from typing import Annotated, Literal

from pydantic import (  # pyright: ignore[reportMissingImports]
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    field_validator,
    model_validator,
)

from pound.catalog.manifest import CATALOG_KINDS
from pound.catalog.metadata import CatalogMetadata


class CanalConstraints(BaseModel):
    start: str
    end: str | None = None  # None => ring / round trip
    days: int | None = Field(gt=0, default=None)  # None => infer from hours_per_day (no cap)
    hours_per_day: FiniteFloat = Field(gt=0, default=6.0)
    movable_bridge_delay_min: FiniteFloat | None = Field(ge=0, default=None)
    boat_length_m: FiniteFloat | None = Field(gt=0, default=None)
    boat_beam_m: FiniteFloat | None = Field(gt=0, default=None)
    boat_draft_m: FiniteFloat | None = Field(gt=0, default=None)
    boat_height_m: FiniteFloat | None = Field(gt=0, default=None)
    amenity_prefs: list[str] = []  # ["pub", "water_point", "shop", ...]


class ResolvedConstraints(BaseModel):
    """The pure-routing input: resolved graph node uids, not place names.

    `start_uid`/`end_uid` are the graph's own synthetic internal node handles
    (what `nx.shortest_path` consumes) — not coordinates, not place names.
    Carrying uids means plan_route literally cannot need a name lookup or a
    coord→uid mapping step: it operates on the handles the graph already
    understands. The CLI / Agent Core obtain a ResolvedConstraints from a
    CanalConstraints via route.resolve.resolve_place; a future map-click UI
    obtains one via route.resolve.resolve_coord(lat, lon, graph). Request-scoped
    — built by a resolver with graph access, consumed immediately, never
    persisted across differently-built artifacts. (design §4 contract evolution.)
    """

    start_uid: int
    end_uid: int
    days: int | None = Field(gt=0, default=None)  # None => infer from hours_per_day (no cap)
    hours_per_day: FiniteFloat = Field(gt=0, default=6.0)
    movable_bridge_delay_min: FiniteFloat | None = Field(ge=0, default=None)
    boat_length_m: FiniteFloat | None = Field(gt=0, default=None)
    boat_beam_m: FiniteFloat | None = Field(gt=0, default=None)
    boat_draft_m: FiniteFloat | None = Field(gt=0, default=None)
    boat_height_m: FiniteFloat | None = Field(gt=0, default=None)


class Amenity(BaseModel):
    kind: str  # "pub" | "water_point" | "marina" | ...
    name: str | None
    lat: float
    lon: float
    distance_m: float  # from route
    source: str  # "osm" | "crt"


class RouteLeg(BaseModel):
    from_place: str
    to_place: str
    distance_km: float
    locks: int
    est_minutes: int
    flagged_unknown_dims: bool = False  # edge(s) lacked dimension tags


class RouteAccessSegment(BaseModel):
    from_uid: int = Field(ge=0)
    to_uid: int = Field(ge=0)
    osm_way_id: int = Field(gt=0)
    kind: Literal["discouraged", "unknown"]
    tag: Literal["boat", "access"]
    value: str

    @model_validator(mode="after")
    def require_canonical_edge(self):
        if self.from_uid >= self.to_uid:
            raise ValueError("access segment edge must use ascending endpoint uids")
        return self


class DayPlan(BaseModel):
    day: int
    legs: list[RouteLeg]
    end_near: str | None  # mooring/town the day ends at
    cruising_minutes: int


class RouteResult(BaseModel):
    start: str
    end: str | None
    is_ring: bool
    legs: list[RouteLeg]
    days: list[DayPlan]
    total_km: float
    total_locks: int
    total_minutes: int
    amenities: list[Amenity]
    warnings: list[str] = []  # e.g. "draft unknown on 3 segments"
    access_segments: list[RouteAccessSegment] = Field(default_factory=list)
    graph_source_date: str  # provenance from the artifact


class Coordinate(BaseModel):
    lat: float
    lon: float


class CanalPointHandle(BaseModel):
    """Stable location handle for a position on a canonical compact edge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    edge: tuple[int, int]
    fraction: float

    @model_validator(mode="after")
    def validate_handle(self):
        if self.edge[0] >= self.edge[1]:
            raise ValueError("edge must be in canonical order")
        if not math.isfinite(self.fraction) or not 0 <= self.fraction <= 1:
            raise ValueError("fraction must be finite and from 0 through 1")
        return self


class ProjectedCanalPoint(BaseModel):
    """A canonical handle together with its derived WGS84 coordinate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    handle: CanalPointHandle
    coordinate: Coordinate


class CanalCandidate(BaseModel):
    candidate_id: str
    handle: CanalPointHandle
    coordinate: Coordinate
    straight_line_distance_m: FiniteFloat = Field(ge=0)
    display_name: str


class CanalCandidatesResponse(BaseModel):
    artifact_revision: str
    candidates: list[CanalCandidate]


MAX_ROUTE_POI_COORDINATES = 10_000
MAX_CATALOG_ROUTE_COORDINATES = MAX_ROUTE_POI_COORDINATES
MAX_CATALOG_TEXT_LENGTH = 256


class GeoJSONPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]

    @field_validator("coordinates", mode="before")
    @classmethod
    def accept_json_coordinate_array(cls, coordinates):
        return tuple(coordinates) if isinstance(coordinates, list) else coordinates

    @field_validator("coordinates")
    @classmethod
    def validate_coordinates(cls, coordinates: tuple[float, float]):
        longitude, latitude = coordinates
        if not math.isfinite(longitude) or not -180 <= longitude <= 180:
            raise ValueError("Point longitude must be finite and within -180 through 180")
        if not math.isfinite(latitude) or not -90 <= latitude <= 90:
            raise ValueError("Point latitude must be finite and within -90 through 90")
        return coordinates


class GeoJSONLineString(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["LineString"] = "LineString"
    coordinates: list[tuple[float, float]]

    @field_validator("coordinates", mode="before")
    @classmethod
    def accept_json_coordinate_arrays(cls, coordinates):
        if not isinstance(coordinates, list):
            return coordinates
        return [
            tuple(coordinate) if isinstance(coordinate, list) else coordinate
            for coordinate in coordinates
        ]

    @field_validator("coordinates")
    @classmethod
    def validate_coordinates(cls, coordinates: list[tuple[float, float]]):
        for longitude, latitude in coordinates:
            if not math.isfinite(longitude) or not -180 <= longitude <= 180:
                raise ValueError("LineString longitude must be finite and within -180 through 180")
            if not math.isfinite(latitude) or not -90 <= latitude <= 90:
                raise ValueError("LineString latitude must be finite and within -90 through 90")
        return coordinates


class MapBounds(BaseModel):
    """Ordered WGS84 viewport bounds used by bounded map queries."""

    model_config = ConfigDict(extra="forbid", strict=True)

    south: float = Field(ge=-90, le=90)
    west: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)


def _validate_place_kinds(kinds: list[str]) -> list[str]:
    unknown_kinds = set(kinds) - (CATALOG_KINDS | {"boat_hire"})
    if unknown_kinds:
        raise ValueError(f"unknown place kinds: {sorted(unknown_kinds)}")
    return kinds


class PlacesQueryPolicy(BaseModel):
    """Explicit proximity basis for a bounded places viewport query."""

    model_config = ConfigDict(extra="forbid", strict=True)

    basis: Literal["route", "waterway", "none"]
    radius_m: FiniteFloat | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_radius_for_basis(self):
        if self.basis == "none" and self.radius_m is not None:
            raise ValueError("none policy must not specify a radius")
        if self.basis != "none" and self.radius_m is None:
            raise ValueError(f"{self.basis} policy requires a radius")
        return self


class ViewportPlacesRequest(BaseModel):
    """Strict, bounded input for a viewport places query."""

    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["viewport"]
    kinds: list[str] = Field(min_length=1)
    bounds: MapBounds
    text: str | None = Field(default=None, max_length=MAX_CATALOG_TEXT_LENGTH)
    route_geometry: GeoJSONLineString | None = None
    day_geometry: GeoJSONLineString | None = None
    policy: PlacesQueryPolicy

    @field_validator("kinds")
    @classmethod
    def validate_kinds(cls, kinds: list[str]) -> list[str]:
        return _validate_place_kinds(kinds)

    @field_validator("route_geometry", "day_geometry")
    @classmethod
    def validate_lines(cls, geometry: GeoJSONLineString | None):
        if geometry is not None and len(geometry.coordinates) < 2:
            raise ValueError("LineString geometry must contain at least two coordinates")
        return geometry

    @model_validator(mode="after")
    def validate_request(self):
        if self.bounds.south > self.bounds.north:
            raise ValueError("bounds south must not exceed north")
        if self.bounds.west > self.bounds.east:
            raise ValueError("bounds west must not exceed east")
        if self.day_geometry is not None and self.route_geometry is None:
            raise ValueError("day_geometry requires route_geometry")
        if self.policy.basis == "route" and self.route_geometry is None:
            raise ValueError("route policy requires route_geometry")
        return self


class NearbyTarget(BaseModel):
    """One caller-named Point or LineString proximity target."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1, max_length=128)
    geometry: GeoJSONPoint | GeoJSONLineString

    @field_validator("geometry")
    @classmethod
    def validate_lines(cls, geometry: GeoJSONPoint | GeoJSONLineString):
        if isinstance(geometry, GeoJSONLineString) and len(geometry.coordinates) < 2:
            raise ValueError("LineString geometry must contain at least two coordinates")
        return geometry


class NearbyPlacesRequest(BaseModel):
    """Strict, bounded input for a batch of nearby places targets."""

    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["nearby"]
    kinds: list[str] = Field(min_length=1)
    text: str | None = Field(default=None, max_length=MAX_CATALOG_TEXT_LENGTH)
    radius_m: FiniteFloat = Field(ge=0)
    targets: list[NearbyTarget] = Field(min_length=1)

    @field_validator("kinds")
    @classmethod
    def validate_kinds(cls, kinds: list[str]) -> list[str]:
        return _validate_place_kinds(kinds)

    @model_validator(mode="after")
    def validate_targets(self):
        target_ids = [target.id for target in self.targets]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("nearby target IDs must be unique")
        return self


PlacesRequest = Annotated[
    ViewportPlacesRequest | NearbyPlacesRequest,
    Field(discriminator="mode"),
]


class OsmProvenance(BaseModel):
    """Structured identity and normalized metadata for an OSM place."""

    model_config = ConfigDict(extra="forbid", strict=True)

    source: Literal["osm"]
    osm_type: Literal["node", "way", "relation"]
    osm_id: int = Field(gt=0)
    metadata: CatalogMetadata


class BoatHireProvenance(BaseModel):
    """Validated provider and location provenance for a curated hire place."""

    model_config = ConfigDict(extra="forbid", strict=True)

    source: Literal["boat_hire"]
    provider_id: str
    provider_name: str
    location_id: str
    location_name: str
    provider_url: str | None = None
    osm_url: str | None = None
    evidence_url: str | None = None
    booking_url: str | None = None


PlaceProvenance = Annotated[
    OsmProvenance | BoatHireProvenance,
    Field(discriminator="source"),
]


class PlaceResponse(BaseModel):
    """A place with source provenance and explicit nullable query context."""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: str = Field(min_length=1)
    name: str | None
    coordinate: Coordinate
    target_id: str | None = None
    distance_to_target_m: FiniteFloat | None = Field(default=None, ge=0)
    distance_to_full_route_m: FiniteFloat | None = Field(default=None, ge=0)
    distance_to_selected_geometry_m: FiniteFloat | None = Field(default=None, ge=0)
    waterway_distance_m: FiniteFloat | None = Field(default=None, ge=0)
    provenance: PlaceProvenance


class PlacesResponse(BaseModel):
    """Complete bounded places results."""

    model_config = ConfigDict(extra="forbid", strict=True)

    places: list[PlaceResponse]


class RoutePoi(BaseModel):
    """A retained POI projected into the route overlay response."""

    identity: str
    kind: str
    name: str | None
    coordinate: Coordinate
    distance_to_route_m: float = Field(ge=0)


class RoutePoisRequest(BaseModel):
    """Strict, artifact-scoped input for bounded route POI queries."""

    model_config = ConfigDict(extra="forbid", strict=True)

    artifact_revision: str
    kinds: list[str]
    bounds: MapBounds
    route_geometry: GeoJSONLineString
    day_geometry: GeoJSONLineString | None = None
    day: int | None = Field(gt=0, default=None)

    @field_validator("route_geometry", "day_geometry", mode="before")
    @classmethod
    def require_numeric_line_coordinates(cls, geometry):
        if geometry is None:
            return None
        coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if isinstance(coordinates, (list, tuple)):
            if len(coordinates) > MAX_ROUTE_POI_COORDINATES:
                raise ValueError(
                    "LineString geometry cannot contain more than "
                    f"{MAX_ROUTE_POI_COORDINATES:,} coordinates"
                )
            for coordinate in coordinates:
                if isinstance(coordinate, (list, tuple)) and any(
                    not isinstance(value, (int, float)) or isinstance(value, bool)
                    for value in coordinate
                ):
                    raise ValueError("LineString coordinates must contain numbers")
        return geometry

    @field_validator("route_geometry", "day_geometry")
    @classmethod
    def require_line_coordinates(cls, geometry: GeoJSONLineString | None):
        if geometry is None:
            return None
        if len(geometry.coordinates) < 2:
            raise ValueError("LineString geometry must contain at least two coordinates")
        for lon, lat in geometry.coordinates:
            if not math.isfinite(lon) or not -180 <= lon <= 180:
                raise ValueError("LineString longitude must be finite and within -180 through 180")
            if not math.isfinite(lat) or not -90 <= lat <= 90:
                raise ValueError("LineString latitude must be finite and within -90 through 90")
        return geometry

    @model_validator(mode="after")
    def require_bounded_geometry_request(self):
        coordinate_count = len(self.route_geometry.coordinates)
        if self.day_geometry is not None:
            coordinate_count += len(self.day_geometry.coordinates)
        if coordinate_count > MAX_ROUTE_POI_COORDINATES:
            raise ValueError(
                "Route POI geometry request cannot contain more than "
                f"{MAX_ROUTE_POI_COORDINATES:,} coordinates in total"
            )
        return self


class RoutePoisResponse(BaseModel):
    """Bounded route POI results and the selected day label."""

    pois: list[RoutePoi]
    zoom_in_required: bool
    matching_count: int = Field(ge=0)
    day: int | None = None


class RouteDayGeometry(BaseModel):
    day: int = Field(gt=0)
    geometry: GeoJSONLineString
    start: Coordinate
    end: Coordinate


class RouteLock(BaseModel):
    coordinate: Coordinate
    name: str | None = None
    day: int = Field(gt=0)
    approximate: bool = False


class BoatHireBase(BaseModel):
    identity: str
    operator: str
    name: str
    coordinate: Coordinate


class CanalNetworkResponse(BaseModel):
    artifact_revision: str
    lines: list[GeoJSONLineString]
    highlight_lines: list[GeoJSONLineString]
    bases: list[BoatHireBase]


class CanalRouteResponse(BaseModel):
    route: RouteResult
    geometry: GeoJSONLineString
    day_geometries: list[RouteDayGeometry] = Field(default_factory=list)
    locks: list[RouteLock] = Field(default_factory=list)
