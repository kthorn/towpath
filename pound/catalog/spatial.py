"""Bounded spatial queries over the independent place catalog."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from pyproj import Transformer
from shapely import transform, wkb
from shapely.geometry import LineString, Point, box
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from pound.catalog.manifest import (
    CATALOG_KINDS,
    MAX_CATALOG_KINDS,
    MAX_CATALOG_RADIUS_M,
    MAX_CATALOG_RESULTS,
)
from pound.catalog.models import CatalogPlace
from pound.graph.spatial import GraphSpatialIndex
from pound.schemas import CatalogPlacesRequest

_TO_BNG = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
MAX_CATALOG_VIEWPORT_SPAN_DEGREES = 10.0
MAX_CATALOG_QUERY_WORK = 100_000
MAX_CATALOG_ROUTE_VERTICES = 10_000


class CatalogQueryLimitError(ValueError):
    """A catalog request exceeds a bounded spatial-query budget."""


@dataclass(frozen=True)
class CatalogQueryPolicy:
    """Request-scoped proximity policy used by catalog callers."""

    basis: Literal["route", "waterway", "none"]
    radius_m: float | None

    def __post_init__(self) -> None:
        if self.basis not in {"route", "waterway", "none"}:
            raise ValueError(f"unknown catalog query basis: {self.basis!r}")
        if self.radius_m is not None and (
            not math.isfinite(self.radius_m) or not 0 <= self.radius_m <= MAX_CATALOG_RADIUS_M
        ):
            raise ValueError(
                f"catalog query radius must be from 0 through {MAX_CATALOG_RADIUS_M:g} m"
            )
        if self.basis == "none" and self.radius_m is not None:
            raise ValueError("none catalog policy must not specify a radius")
        if self.basis != "none" and self.radius_m is None:
            raise ValueError(f"{self.basis} catalog policy requires a radius")


@dataclass(frozen=True)
class CatalogQueryResult:
    """Deterministic bounded catalog results and request-scoped distances."""

    places: tuple[CatalogPlace, ...]
    matching_count: int
    over_cap: bool
    waterway_distances: tuple[float | None, ...] = field(default=(), compare=False, repr=False)
    full_route_distances: tuple[float | None, ...] = field(default=(), compare=False, repr=False)
    selected_geometry_distances: tuple[float | None, ...] = field(
        default=(), compare=False, repr=False
    )


@dataclass(frozen=True)
class CatalogSpatialIndex:
    """Immutable WGS84 catalog trees backed by a graph-owned waterway index."""

    places: tuple[CatalogPlace, ...]
    geometries: tuple[BaseGeometry, ...]
    display_points: tuple[Point, ...]
    display_tree: STRtree | None
    waterway_index: GraphSpatialIndex

    def __init__(self, places: tuple[CatalogPlace, ...], waterway_index: GraphSpatialIndex) -> None:
        ordered_places = tuple(
            sorted(places, key=lambda place: (place.osm_type.value, place.osm_id, place.kind))
        )
        geometries = tuple(wkb.loads(place.geometry_wkb) for place in ordered_places)
        display_points = tuple(Point(place.lon, place.lat) for place in ordered_places)
        object.__setattr__(self, "places", ordered_places)
        object.__setattr__(self, "geometries", geometries)
        object.__setattr__(self, "display_points", display_points)
        object.__setattr__(
            self, "display_tree", STRtree(display_points) if display_points else None
        )
        object.__setattr__(self, "waterway_index", waterway_index)

    @staticmethod
    def _validate_request_limits(request: CatalogPlacesRequest) -> None:
        if len(request.kinds) > MAX_CATALOG_KINDS:
            raise CatalogQueryLimitError(
                f"catalog query cannot select more than {MAX_CATALOG_KINDS} kinds"
            )
        if request.bounds.south > request.bounds.north:
            raise ValueError("bounds south must not exceed north")
        if request.bounds.west > request.bounds.east:
            raise ValueError("bounds west must not exceed east")
        latitude_span = request.bounds.north - request.bounds.south
        longitude_span = request.bounds.east - request.bounds.west
        if max(latitude_span, longitude_span) > MAX_CATALOG_VIEWPORT_SPAN_DEGREES:
            raise CatalogQueryLimitError(
                "catalog viewport span exceeds the configured query budget"
            )
        if request.policy.radius_m is not None and request.policy.radius_m > MAX_CATALOG_RADIUS_M:
            raise CatalogQueryLimitError("catalog query radius exceeds the configured budget")
        if (request.day is None) != (request.day_geometry is None) or (
            request.day_geometry is not None and request.route_geometry is None
        ):
            raise ValueError(
                "day and day_geometry require route_geometry and must be supplied together"
            )
        if request.policy.basis == "route" and request.route_geometry is None:
            raise ValueError("route policy requires route geometry")
        coordinate_count = 0
        if request.route_geometry is not None:
            coordinate_count += len(request.route_geometry.coordinates)
        if request.day_geometry is not None:
            coordinate_count += len(request.day_geometry.coordinates)
        if coordinate_count > MAX_CATALOG_ROUTE_VERTICES:
            raise CatalogQueryLimitError(
                "catalog geometry exceeds the configured coordinate budget"
            )

    def viewport_candidate_count(self, bounds) -> int:
        """Return display points in bounds without running metric transformations."""
        if self.display_tree is None:
            return 0
        viewport = box(bounds.west, bounds.south, bounds.east, bounds.north)
        return len(self.display_tree.query(viewport))

    @staticmethod
    def _metric_distance(geometry: BaseGeometry, target_bng: BaseGeometry) -> float:
        geometry_bng = transform(geometry, _TO_BNG.transform, interleaved=False)
        return float(geometry_bng.distance(target_bng))

    def query(self, request: CatalogPlacesRequest) -> CatalogQueryResult:
        """Return bounded places selected by kind, viewport, and explicit policy."""
        self._validate_request_limits(request)
        unknown_kinds = set(request.kinds) - CATALOG_KINDS
        if unknown_kinds:
            raise ValueError(f"unknown catalog kinds: {sorted(unknown_kinds)}")
        policy = CatalogQueryPolicy(request.policy.basis, request.policy.radius_m)
        if not request.kinds or self.display_tree is None:
            return CatalogQueryResult(places=(), matching_count=0, over_cap=False)

        viewport = box(
            request.bounds.west,
            request.bounds.south,
            request.bounds.east,
            request.bounds.north,
        )
        positions = sorted(int(position) for position in self.display_tree.query(viewport))
        if len(positions) > MAX_CATALOG_QUERY_WORK:
            raise CatalogQueryLimitError("catalog query work budget exceeded")

        selected_kinds = set(request.kinds)
        full_route_bng = None
        selected_geometry_bng = None
        if request.route_geometry is not None:
            route = request.route_geometry
            full_route_bng = transform(
                LineString(route.coordinates),
                _TO_BNG.transform,
                interleaved=False,
            )
        if request.day_geometry is not None:
            day = request.day_geometry
            selected_geometry_bng = transform(
                LineString(day.coordinates),
                _TO_BNG.transform,
                interleaved=False,
            )

        matches: list[CatalogPlace] = []
        waterway_distances: list[float | None] = []
        full_route_distances: list[float | None] = []
        selected_geometry_distances: list[float | None] = []
        for position in positions:
            place = self.places[position]
            if place.kind not in selected_kinds:
                continue
            geometry = self.geometries[position]
            full_route_distance = (
                self._metric_distance(geometry, full_route_bng)
                if full_route_bng is not None
                else None
            )
            selected_geometry_distance = (
                self._metric_distance(geometry, selected_geometry_bng)
                if selected_geometry_bng is not None
                else None
            )
            waterway_distance = None
            if policy.basis == "waterway" or policy.basis == "none" or full_route_bng is not None:
                waterway_distance = self.waterway_index.distance_to_waterway(geometry)

            if policy.basis == "route":
                route_distance = (
                    selected_geometry_distance
                    if selected_geometry_distance is not None
                    else full_route_distance
                )
                if route_distance is None or policy.radius_m is None:
                    raise ValueError("route policy requires route geometry and radius")
                if route_distance > policy.radius_m:
                    continue
            elif policy.basis == "waterway":
                if policy.radius_m is None:
                    raise ValueError("waterway policy requires a radius")
                if waterway_distance is None or waterway_distance > policy.radius_m:
                    continue

            matches.append(place)
            waterway_distances.append(waterway_distance)
            full_route_distances.append(full_route_distance)
            selected_geometry_distances.append(selected_geometry_distance)
            if len(matches) > MAX_CATALOG_RESULTS:
                return CatalogQueryResult(
                    places=(),
                    matching_count=MAX_CATALOG_RESULTS + 1,
                    over_cap=True,
                )

        return CatalogQueryResult(
            places=tuple(matches),
            matching_count=len(matches),
            over_cap=False,
            waterway_distances=tuple(waterway_distances),
            full_route_distances=tuple(full_route_distances),
            selected_geometry_distances=tuple(selected_geometry_distances),
        )
