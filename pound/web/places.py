"""Unified bounded queries over independent OSM and boat-hire place sources."""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry

from pound.catalog.manifest import CATALOG_KINDS, MAX_CATALOG_KINDS, MAX_CATALOG_RADIUS_M
from pound.catalog.spatial import (
    CatalogQueryLimitError,
    CatalogQueryPolicy,
    CatalogSourceMatch,
    CatalogSourceResult,
    CatalogSpatialIndex,
    wgs84_to_bng,
)
from pound.graph.spatial import GraphSpatialIndex
from pound.schemas import (
    MAX_CATALOG_ROUTE_COORDINATES,
    BoatHireProvenance,
    Coordinate,
    GeoJSONPoint,
    NearbyPlacesRequest,
    OsmProvenance,
    PlaceResponse,
    PlacesResponse,
    ViewportPlacesRequest,
)
from pound.web.boat_hire import BoatHireSeed

PLACE_KINDS = CATALOG_KINDS | frozenset({"boat_hire"})
MAX_PLACES_RESULTS = 1_000
MAX_PLACES_QUERY_WORK = 100_000
MAX_PLACES_VIEWPORT_SPAN_DEGREES = 10.0
MAX_PLACES_TARGETS = 64


class PlacesQueryBudgetError(ValueError):
    """A places query exceeds a configured request or candidate-work budget."""

    fields: list[str]

    def __init__(self, fields: list[str]) -> None:
        self.fields = list(fields)
        super().__init__(f"places query budget exceeded for {', '.join(self.fields)}")


class PlacesResultLimitError(ValueError):
    """The complete places result would exceed its configured result ceiling."""

    target_id: str | None
    fields: list[str]

    def __init__(self, target_id: str | None) -> None:
        self.target_id = target_id
        self.fields = ["targets"] if target_id is not None else []
        detail = f" for target {target_id!r}" if target_id is not None else ""
        super().__init__(f"places result limit exceeded{detail}")


@dataclass
class PlacesQueryStats:
    """Optional mutable instrumentation sink for one places query attempt."""

    work_used: int = 0


@dataclass(frozen=True)
class _BoatHireMatch:
    seed: BoatHireSeed
    distance_m: float | None = None
    full_route_distance_m: float | None = None
    selected_geometry_distance_m: float | None = None
    waterway_distance_m: float | None = None


class PlacesIndex:
    """Compose bounded OSM catalog and curated boat-hire source queries."""

    def __init__(
        self,
        catalog_index: CatalogSpatialIndex,
        waterway_index: GraphSpatialIndex,
        boat_hire_seeds: tuple[BoatHireSeed, ...],
        *,
        max_kinds: int = MAX_CATALOG_KINDS,
        max_radius_m: float = MAX_CATALOG_RADIUS_M,
        max_viewport_span_deg: float = MAX_PLACES_VIEWPORT_SPAN_DEGREES,
        max_vertices: int = MAX_CATALOG_ROUTE_COORDINATES,
        max_targets: int = MAX_PLACES_TARGETS,
        max_work: int = MAX_PLACES_QUERY_WORK,
        max_results: int = MAX_PLACES_RESULTS,
    ) -> None:
        self._validate_integer_limit("max_kinds", max_kinds, 1, MAX_CATALOG_KINDS)
        self._validate_float_limit("max_radius_m", max_radius_m, 0.0, MAX_CATALOG_RADIUS_M)
        self._validate_float_limit(
            "max_viewport_span_deg",
            max_viewport_span_deg,
            0.0,
            MAX_PLACES_VIEWPORT_SPAN_DEGREES,
            minimum_exclusive=True,
        )
        self._validate_integer_limit("max_vertices", max_vertices, 1, MAX_CATALOG_ROUTE_COORDINATES)
        self._validate_integer_limit("max_targets", max_targets, 1, MAX_PLACES_TARGETS)
        self._validate_integer_limit("max_work", max_work, 0, MAX_PLACES_QUERY_WORK)
        self._validate_integer_limit("max_results", max_results, 0, MAX_PLACES_RESULTS)

        self.catalog_index = catalog_index
        self.waterway_index = waterway_index
        self.boat_hire_seeds = tuple(seed for seed in boat_hire_seeds if seed.is_public_place)
        self.max_kinds = max_kinds
        self.max_radius_m = max_radius_m
        self.max_viewport_span_deg = max_viewport_span_deg
        self.max_vertices = max_vertices
        self.max_targets = max_targets
        self.max_work = max_work
        self.max_results = max_results

    @staticmethod
    def _validate_integer_limit(name: str, value: int, minimum: int, maximum: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f"{name} must be an integer from {minimum} through {maximum}")

    @staticmethod
    def _validate_float_limit(
        name: str,
        value: float,
        minimum: float,
        maximum: float,
        *,
        minimum_exclusive: bool = False,
    ) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a numeric limit")
        valid_minimum = value > minimum if minimum_exclusive else value >= minimum
        if not math.isfinite(value) or not valid_minimum or value > maximum:
            lower = "greater than" if minimum_exclusive else "at least"
            raise ValueError(
                f"{name} must be finite and {lower} {minimum:g} and at most {maximum:g}"
            )

    def query(
        self,
        request: ViewportPlacesRequest | NearbyPlacesRequest,
        *,
        stats: PlacesQueryStats | None = None,
    ) -> PlacesResponse:
        """Run one complete bounded places query."""
        self._validate_request_limits(request)
        if isinstance(request, ViewportPlacesRequest):
            return self._query_viewport(request, stats)
        if isinstance(request, NearbyPlacesRequest):
            return self._query_nearby(request, stats)
        raise TypeError("request must be a viewport or nearby places request")

    def _validate_request_limits(
        self, request: ViewportPlacesRequest | NearbyPlacesRequest
    ) -> None:
        if not isinstance(request, (ViewportPlacesRequest, NearbyPlacesRequest)):
            raise TypeError("request must be a viewport or nearby places request")

        kinds = set(request.kinds)
        unknown_kinds = kinds - PLACE_KINDS
        if unknown_kinds:
            raise ValueError(f"unknown place kinds: {sorted(unknown_kinds)}")
        if len(request.kinds) > self.max_kinds:
            raise PlacesQueryBudgetError(["kinds"])

        if isinstance(request, ViewportPlacesRequest):
            span = max(
                request.bounds.north - request.bounds.south,
                request.bounds.east - request.bounds.west,
            )
            if span > self.max_viewport_span_deg:
                raise PlacesQueryBudgetError(["bounds"])
            vertex_count = sum(
                len(geometry.coordinates)
                for geometry in (request.route_geometry, request.day_geometry)
                if geometry is not None
            )
            if vertex_count > self.max_vertices:
                raise PlacesQueryBudgetError(["route_geometry", "day_geometry"])
            radius_m = request.policy.radius_m
            if radius_m is not None and radius_m > self.max_radius_m:
                raise PlacesQueryBudgetError(["policy.radius_m"])
            return

        if request.radius_m > self.max_radius_m:
            raise PlacesQueryBudgetError(["radius_m"])
        if len(request.targets) > self.max_targets:
            raise PlacesQueryBudgetError(["targets"])
        vertex_count = sum(
            1 if isinstance(target.geometry, GeoJSONPoint) else len(target.geometry.coordinates)
            for target in request.targets
        )
        if vertex_count > self.max_vertices:
            raise PlacesQueryBudgetError(["targets"])

    def _query_viewport(
        self,
        request: ViewportPlacesRequest,
        stats: PlacesQueryStats | None,
    ) -> PlacesResponse:
        selected_kinds = frozenset(request.kinds)
        osm_kinds = selected_kinds & CATALOG_KINDS
        route_bng = self._line_bng(request.route_geometry)
        day_bng = self._line_bng(request.day_geometry)
        remaining_work = self.max_work
        remaining_results = self.max_results

        osm_result = CatalogSourceResult(matches=(), work_used=0)
        if osm_kinds:
            osm_result = self._catalog_viewport(
                request,
                kinds=osm_kinds,
                route_bng=route_bng,
                day_bng=day_bng,
                work_budget=remaining_work,
                result_budget=remaining_results,
                stats=stats,
            )
            remaining_work -= osm_result.work_used
            if len(osm_result.matches) > remaining_results:
                raise PlacesResultLimitError(None)
            remaining_results -= len(osm_result.matches)

        hire_matches: tuple[_BoatHireMatch, ...] = ()
        if "boat_hire" in selected_kinds:
            hire_matches = self._scan_hire_viewport(
                request,
                route_bng=route_bng,
                day_bng=day_bng,
                work_budget=remaining_work,
                result_budget=remaining_results,
                stats=stats,
            )

        osm_matches = self._suppress_osm(osm_result.matches, hire_matches)
        results = self._sorted_viewport_results(osm_matches, hire_matches)
        return PlacesResponse(places=[self._viewport_response(match) for match in results])

    def _query_nearby(
        self,
        request: NearbyPlacesRequest,
        stats: PlacesQueryStats | None,
    ) -> PlacesResponse:
        selected_kinds = frozenset(request.kinds)
        osm_kinds = selected_kinds & CATALOG_KINDS
        remaining_work = self.max_work
        remaining_results = self.max_results
        results: list[PlaceResponse] = []

        for target in request.targets:
            target_bng = self._target_bng(target.geometry)
            osm_result = CatalogSourceResult(matches=(), work_used=0)
            if osm_kinds:
                osm_result = self._catalog_nearby(
                    request,
                    kinds=osm_kinds,
                    target_bng=target_bng,
                    work_budget=remaining_work,
                    result_budget=remaining_results,
                    target_id=target.id,
                    stats=stats,
                )
                remaining_work -= osm_result.work_used
                if len(osm_result.matches) > remaining_results:
                    raise PlacesResultLimitError(target.id)
                remaining_results -= len(osm_result.matches)

            hire_matches: tuple[_BoatHireMatch, ...] = ()
            if "boat_hire" in selected_kinds:
                hire_matches = self._scan_hire_target(
                    request,
                    target_bng=target_bng,
                    work_budget=remaining_work,
                    result_budget=remaining_results,
                    target_id=target.id,
                    stats=stats,
                )
                remaining_work -= len(self.boat_hire_seeds)

            osm_matches = self._suppress_osm(osm_result.matches, hire_matches)
            target_results = self._sorted_nearby_results(osm_matches, hire_matches)
            results.extend(self._nearby_response(match, target.id) for match in target_results)
            remaining_results -= len(hire_matches)

        return PlacesResponse(places=results)

    @staticmethod
    def _line_bng(geometry) -> BaseGeometry | None:
        if geometry is None:
            return None
        return wgs84_to_bng(LineString(geometry.coordinates))

    @staticmethod
    def _target_bng(geometry) -> BaseGeometry:
        if isinstance(geometry, GeoJSONPoint):
            return wgs84_to_bng(Point(*geometry.coordinates))
        return wgs84_to_bng(LineString(geometry.coordinates))

    @staticmethod
    def _normalize_text(text: str | None) -> str:
        return text.strip().casefold() if text is not None else ""

    def _catalog_viewport(
        self,
        request: ViewportPlacesRequest,
        *,
        kinds: frozenset[str],
        route_bng: BaseGeometry | None,
        day_bng: BaseGeometry | None,
        work_budget: int,
        result_budget: int,
        stats: PlacesQueryStats | None,
    ) -> CatalogSourceResult:
        try:
            result = self.catalog_index.query_viewport(
                kinds=kinds,
                bounds=request.bounds,
                text=request.text,
                policy=CatalogQueryPolicy(request.policy.basis, request.policy.radius_m),
                route_bng=route_bng,
                day_bng=day_bng,
                work_budget=work_budget,
                result_budget=result_budget,
            )
        except CatalogQueryLimitError as exc:
            self._record_failed_catalog_work(
                stats,
                lambda: self.catalog_index.viewport_candidate_count(request.bounds),
            )
            if exc.limit == "result":
                raise PlacesResultLimitError(None) from exc
            raise PlacesQueryBudgetError(["bounds"]) from exc
        self._record_work(stats, result.work_used)
        return result

    def _catalog_nearby(
        self,
        request: NearbyPlacesRequest,
        *,
        kinds: frozenset[str],
        target_bng: BaseGeometry,
        work_budget: int,
        result_budget: int,
        target_id: str,
        stats: PlacesQueryStats | None,
    ) -> CatalogSourceResult:
        try:
            result = self.catalog_index.query_nearby(
                target_bng=target_bng,
                radius_m=request.radius_m,
                kinds=kinds,
                text=request.text,
                work_budget=work_budget,
                result_budget=result_budget,
            )
        except CatalogQueryLimitError as exc:
            self._record_failed_catalog_work(
                stats,
                lambda: self._nearby_candidate_count(target_bng, request.radius_m),
            )
            if exc.limit == "result":
                raise PlacesResultLimitError(target_id) from exc
            raise PlacesQueryBudgetError(["targets"]) from exc
        self._record_work(stats, result.work_used)
        return result

    def _nearby_candidate_count(self, target_bng: BaseGeometry, radius_m: float) -> int:
        metric_geometries = self.catalog_index.metric_geometries
        return sum(geometry.distance(target_bng) <= radius_m for geometry in metric_geometries)

    @staticmethod
    def _record_work(stats: PlacesQueryStats | None, work_used: int) -> None:
        if stats is not None:
            stats.work_used += work_used

    def _record_failed_catalog_work(
        self,
        stats: PlacesQueryStats | None,
        candidate_count,
    ) -> None:
        if stats is None:
            return
        try:
            work_used = int(candidate_count())
        except (AttributeError, TypeError, ValueError):
            return
        stats.work_used += work_used

    def _scan_hire_viewport(
        self,
        request: ViewportPlacesRequest,
        *,
        route_bng: BaseGeometry | None,
        day_bng: BaseGeometry | None,
        work_budget: int,
        result_budget: int,
        stats: PlacesQueryStats | None,
    ) -> tuple[_BoatHireMatch, ...]:
        self._consume_hire_work(work_budget, stats, ["bounds"])
        search_text = self._normalize_text(request.text)
        route_requested = route_bng is not None
        waterway_requested = request.policy.basis in {"waterway", "none"} or route_requested
        matches: list[_BoatHireMatch] = []
        for seed in self.boat_hire_seeds:
            if not (
                request.bounds.south <= seed.latitude <= request.bounds.north
                and request.bounds.west <= seed.longitude <= request.bounds.east
            ):
                continue
            if search_text and not (
                search_text in seed.operator.casefold() or search_text in seed.name.casefold()
            ):
                continue

            point = Point(seed.longitude, seed.latitude)
            point_bng = wgs84_to_bng(point)
            full_route_distance = float(point_bng.distance(route_bng)) if route_requested else None
            selected_geometry_distance = (
                float(point_bng.distance(day_bng)) if day_bng is not None else None
            )
            waterway_distance = (
                self.waterway_index.distance_to_waterway(point) if waterway_requested else None
            )
            active_distance = None
            if request.policy.basis == "route":
                active_distance = (
                    selected_geometry_distance
                    if selected_geometry_distance is not None
                    else full_route_distance
                )
                if active_distance is None or request.policy.radius_m is None:
                    raise ValueError("route policy requires route geometry and radius")
                if active_distance > request.policy.radius_m:
                    continue
            elif request.policy.basis == "waterway":
                active_distance = waterway_distance
                if request.policy.radius_m is None:
                    raise ValueError("waterway policy requires a radius")
                if active_distance is None or active_distance > request.policy.radius_m:
                    continue
            elif request.policy.basis != "none":
                raise ValueError(f"unknown places query basis: {request.policy.basis!r}")

            matches.append(
                _BoatHireMatch(
                    seed=seed,
                    distance_m=active_distance,
                    full_route_distance_m=full_route_distance,
                    selected_geometry_distance_m=selected_geometry_distance,
                    waterway_distance_m=(
                        float(waterway_distance) if waterway_distance is not None else None
                    ),
                )
            )
        if len(matches) > result_budget:
            raise PlacesResultLimitError(None)
        return tuple(matches)

    def _scan_hire_target(
        self,
        request: NearbyPlacesRequest,
        *,
        target_bng: BaseGeometry,
        work_budget: int,
        result_budget: int,
        target_id: str,
        stats: PlacesQueryStats | None,
    ) -> tuple[_BoatHireMatch, ...]:
        self._consume_hire_work(work_budget, stats, ["targets"])
        search_text = self._normalize_text(request.text)
        matches: list[_BoatHireMatch] = []
        for seed in self.boat_hire_seeds:
            if search_text and not (
                search_text in seed.operator.casefold() or search_text in seed.name.casefold()
            ):
                continue
            point_bng = wgs84_to_bng(Point(seed.longitude, seed.latitude))
            distance_m = float(point_bng.distance(target_bng))
            if distance_m > request.radius_m:
                continue
            matches.append(_BoatHireMatch(seed=seed, distance_m=distance_m))
        if len(matches) > result_budget:
            raise PlacesResultLimitError(target_id)
        return tuple(matches)

    def _consume_hire_work(
        self,
        work_budget: int,
        stats: PlacesQueryStats | None,
        fields: list[str],
    ) -> None:
        work_used = len(self.boat_hire_seeds)
        self._record_work(stats, work_used)
        if work_used > work_budget:
            raise PlacesQueryBudgetError(fields)

    @staticmethod
    def _suppress_osm(
        osm_matches: tuple[CatalogSourceMatch, ...],
        hire_matches: tuple[_BoatHireMatch, ...],
    ) -> tuple[CatalogSourceMatch, ...]:
        hire_osm_ids = {
            (identity.osm_type, identity.osm_id)
            for match in hire_matches
            if (identity := match.seed.osm_identity) is not None
        }
        if not hire_osm_ids:
            return osm_matches
        return tuple(
            match
            for match in osm_matches
            if (match.place.osm_type.value, match.place.osm_id) not in hire_osm_ids
        )

    @staticmethod
    def _sorted_viewport_results(
        osm_matches: tuple[CatalogSourceMatch, ...],
        hire_matches: tuple[_BoatHireMatch, ...],
    ) -> tuple[CatalogSourceMatch | _BoatHireMatch, ...]:
        def sort_key(match):
            if isinstance(match, CatalogSourceMatch):
                return (
                    match.distance_m is None,
                    match.distance_m if match.distance_m is not None else 0.0,
                    0,
                    match.place.osm_type.value,
                    match.place.osm_id,
                    match.place.kind,
                )
            return (
                match.distance_m is None,
                match.distance_m if match.distance_m is not None else 0.0,
                1,
                match.seed.source_provider_id,
                match.seed.location_id,
            )

        return tuple(sorted((*osm_matches, *hire_matches), key=sort_key))

    @staticmethod
    def _sorted_nearby_results(
        osm_matches: tuple[CatalogSourceMatch, ...],
        hire_matches: tuple[_BoatHireMatch, ...],
    ) -> tuple[CatalogSourceMatch | _BoatHireMatch, ...]:
        return PlacesIndex._sorted_viewport_results(osm_matches, hire_matches)

    @staticmethod
    def _viewport_response(
        match: CatalogSourceMatch | _BoatHireMatch,
    ) -> PlaceResponse:
        if isinstance(match, CatalogSourceMatch):
            place = match.place
            return PlaceResponse(
                kind=place.kind,
                name=place.name,
                coordinate=Coordinate(lat=place.lat, lon=place.lon),
                distance_to_full_route_m=match.full_route_distance_m,
                distance_to_selected_geometry_m=match.selected_geometry_distance_m,
                waterway_distance_m=match.waterway_distance_m,
                provenance=OsmProvenance(
                    source="osm",
                    osm_type=place.osm_type.value,
                    osm_id=place.osm_id,
                    metadata=place.metadata,
                ),
            )
        return PlacesIndex._hire_response(match, target_id=None)

    @staticmethod
    def _nearby_response(
        match: CatalogSourceMatch | _BoatHireMatch,
        target_id: str,
    ) -> PlaceResponse:
        if isinstance(match, CatalogSourceMatch):
            place = match.place
            return PlaceResponse(
                kind=place.kind,
                name=place.name,
                coordinate=Coordinate(lat=place.lat, lon=place.lon),
                target_id=target_id,
                distance_to_target_m=match.distance_m,
                provenance=OsmProvenance(
                    source="osm",
                    osm_type=place.osm_type.value,
                    osm_id=place.osm_id,
                    metadata=place.metadata,
                ),
            )
        return PlacesIndex._hire_response(match, target_id=target_id)

    @staticmethod
    def _hire_response(match: _BoatHireMatch, target_id: str | None) -> PlaceResponse:
        seed = match.seed
        return PlaceResponse(
            kind="boat_hire",
            name=seed.name,
            coordinate=Coordinate(lat=seed.latitude, lon=seed.longitude),
            target_id=target_id,
            distance_to_target_m=match.distance_m if target_id is not None else None,
            distance_to_full_route_m=(match.full_route_distance_m if target_id is None else None),
            distance_to_selected_geometry_m=(
                match.selected_geometry_distance_m if target_id is None else None
            ),
            waterway_distance_m=match.waterway_distance_m if target_id is None else None,
            provenance=BoatHireProvenance(
                source="boat_hire",
                provider_id=seed.source_provider_id,
                provider_name=seed.operator,
                location_id=seed.location_id,
                location_name=seed.name,
                provider_url=seed.source_provider_website or None,
                osm_url=seed.osm_url or None,
                evidence_url=seed.evidence_url or None,
                booking_url=seed.booking_url or None,
            ),
        )


__all__ = [
    "MAX_PLACES_QUERY_WORK",
    "MAX_PLACES_RESULTS",
    "MAX_PLACES_TARGETS",
    "MAX_PLACES_VIEWPORT_SPAN_DEGREES",
    "PLACE_KINDS",
    "PlacesIndex",
    "PlacesQueryBudgetError",
    "PlacesQueryStats",
    "PlacesResultLimitError",
]
