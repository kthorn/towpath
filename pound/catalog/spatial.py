"""Bounded spatial queries over the independent place catalog."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal, cast

from pyproj import Transformer  # pyright: ignore[reportMissingImports]
from shapely import transform, wkb
from shapely.geometry import Point, box
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from pound.catalog.manifest import CATALOG_KINDS, MAX_CATALOG_KINDS, MAX_CATALOG_RADIUS_M
from pound.catalog.models import CatalogPlace
from pound.graph.spatial import GraphSpatialIndex
from pound.schemas import MapBounds

_TO_BNG = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)


def wgs84_to_bng(geometry: BaseGeometry) -> BaseGeometry:
    """Transform a validated WGS84 geometry to metric British National Grid."""
    return transform(geometry, cast(Any, _TO_BNG.transform), interleaved=False)


class CatalogQueryLimitError(ValueError):
    """A catalog source operation exceeds one of its supplied budgets."""

    limit: Literal["work", "result"]

    def __init__(self, limit: Literal["work", "result"]) -> None:
        if limit not in {"work", "result"}:
            raise ValueError(f"unknown catalog query limit: {limit!r}")
        self.limit = limit
        super().__init__(f"catalog query {limit} budget exceeded")


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
class CatalogSourceMatch:
    """One catalog place with source-query metric distances."""

    place: CatalogPlace
    distance_m: float | None = None
    waterway_distance_m: float | None = None
    full_route_distance_m: float | None = None
    selected_geometry_distance_m: float | None = None

    @property
    def distance_to_full_route_m(self) -> float | None:
        """Return the full-route distance using the public response terminology."""
        return self.full_route_distance_m

    @property
    def distance_to_selected_geometry_m(self) -> float | None:
        """Return the selected-geometry distance using public response terminology."""
        return self.selected_geometry_distance_m


@dataclass(frozen=True)
class CatalogSourceResult:
    """Complete source matches and the spatial candidate work they consumed."""

    matches: tuple[CatalogSourceMatch, ...]
    work_used: int


@dataclass(frozen=True)
class CatalogSpatialIndex:
    """Immutable WGS84 catalog trees backed by a graph-owned waterway index."""

    places: tuple[CatalogPlace, ...]
    geometries: tuple[BaseGeometry, ...]
    display_points: tuple[Point, ...]
    display_tree: STRtree | None
    metric_geometries: tuple[BaseGeometry, ...]
    metric_tree: STRtree | None
    waterway_index: GraphSpatialIndex
    search_names: tuple[tuple[str, ...], ...]

    def __init__(self, places: tuple[CatalogPlace, ...], waterway_index: GraphSpatialIndex) -> None:
        ordered_places = tuple(
            sorted(places, key=lambda place: (place.osm_type.value, place.osm_id, place.kind))
        )
        geometries = tuple(wkb.loads(place.geometry_wkb) for place in ordered_places)
        display_points = tuple(Point(place.lon, place.lat) for place in ordered_places)
        metric_geometries = tuple(wgs84_to_bng(geometry) for geometry in geometries)
        object.__setattr__(self, "places", ordered_places)
        object.__setattr__(self, "geometries", geometries)
        object.__setattr__(self, "display_points", display_points)
        object.__setattr__(
            self, "display_tree", STRtree(display_points) if display_points else None
        )
        object.__setattr__(self, "metric_geometries", metric_geometries)
        object.__setattr__(
            self,
            "metric_tree",
            STRtree(metric_geometries) if metric_geometries else None,
        )
        object.__setattr__(self, "waterway_index", waterway_index)
        search_names = tuple(
            tuple(
                value.casefold()
                for value in (place.name, place.metadata.alt_name)
                if value is not None
            )
            for place in ordered_places
        )
        object.__setattr__(self, "search_names", search_names)

    @staticmethod
    def _validate_kinds(kinds: frozenset[str]) -> frozenset[str]:
        if len(kinds) > MAX_CATALOG_KINDS:
            raise ValueError(f"catalog query cannot select more than {MAX_CATALOG_KINDS} kinds")
        unknown_kinds = set(kinds) - CATALOG_KINDS
        if unknown_kinds:
            raise ValueError(f"unknown catalog kinds: {sorted(unknown_kinds)}")
        return kinds

    @staticmethod
    def _validate_budgets(work_budget: int, result_budget: int) -> None:
        if work_budget < 0:
            raise ValueError("work_budget must be nonnegative")
        if result_budget < 0:
            raise ValueError("result_budget must be nonnegative")

    @staticmethod
    def _normalize_text(text: str | None) -> str:
        return text.strip().casefold() if text is not None else ""

    @staticmethod
    def _matches_text(search_names: tuple[str, ...], text: str) -> bool:
        return not text or any(text in name for name in search_names)

    @staticmethod
    def _check_work(work_used: int, work_budget: int) -> None:
        if work_used > work_budget:
            raise CatalogQueryLimitError("work")

    def viewport_candidate_count(self, bounds: MapBounds) -> int:
        """Return display points in bounds without running metric transformations."""
        if self.display_tree is None:
            return 0
        viewport = box(bounds.west, bounds.south, bounds.east, bounds.north)
        return len(self.display_tree.query(viewport))

    def _waterway_distance(self, metric_geometry: BaseGeometry) -> float | None:
        edge_tree = self.waterway_index.edge_tree
        if edge_tree is None:
            return None
        _positions, distances = edge_tree.query_nearest(
            metric_geometry,
            all_matches=True,
            return_distance=True,
        )
        if len(distances) == 0:
            return None
        return float(min(distances))

    def query_viewport(
        self,
        *,
        kinds: frozenset[str],
        bounds: MapBounds,
        text: str | None,
        policy: CatalogQueryPolicy,
        route_bng: BaseGeometry | None,
        day_bng: BaseGeometry | None,
        work_budget: int,
        result_budget: int,
    ) -> CatalogSourceResult:
        """Return bounded catalog matches selected by display-point viewport."""
        selected_kinds = self._validate_kinds(kinds)
        self._validate_budgets(work_budget, result_budget)
        if bounds.south > bounds.north:
            raise ValueError("bounds south must not exceed north")
        if bounds.west > bounds.east:
            raise ValueError("bounds west must not exceed east")
        if day_bng is not None and route_bng is None:
            raise ValueError("day geometry requires route geometry")
        if policy.basis == "route" and route_bng is None:
            raise ValueError("route policy requires route geometry")
        search_text = self._normalize_text(text)
        if not selected_kinds or self.display_tree is None:
            return CatalogSourceResult(matches=(), work_used=0)

        viewport = box(bounds.west, bounds.south, bounds.east, bounds.north)
        positions = sorted(int(position) for position in self.display_tree.query(viewport))
        work_used = len(positions)
        self._check_work(work_used, work_budget)

        full_route_requested = route_bng is not None
        selected_geometry_requested = day_bng is not None
        waterway_requested = policy.basis in {"waterway", "none"} or full_route_requested
        matches: list[CatalogSourceMatch] = []
        for position in positions:
            place = self.places[position]
            if place.kind not in selected_kinds:
                continue
            if not self._matches_text(self.search_names[position], search_text):
                continue

            metric_geometry = self.metric_geometries[position]
            full_route_distance = (
                float(metric_geometry.distance(route_bng)) if full_route_requested else None
            )
            selected_geometry_distance = (
                float(metric_geometry.distance(day_bng)) if selected_geometry_requested else None
            )
            waterway_distance = (
                self._waterway_distance(metric_geometry) if waterway_requested else None
            )

            active_distance = None
            if policy.basis == "route":
                active_distance = (
                    selected_geometry_distance
                    if selected_geometry_distance is not None
                    else full_route_distance
                )
                if active_distance is None or policy.radius_m is None:
                    raise ValueError("route policy requires route geometry and radius")
                if active_distance > policy.radius_m:
                    continue
            elif policy.basis == "waterway":
                active_distance = waterway_distance
                if policy.radius_m is None:
                    raise ValueError("waterway policy requires a radius")
                if active_distance is None or active_distance > policy.radius_m:
                    continue
            elif policy.basis != "none":
                raise ValueError(f"unknown catalog query basis: {policy.basis!r}")

            if len(matches) >= result_budget:
                raise CatalogQueryLimitError("result")
            matches.append(
                CatalogSourceMatch(
                    place=place,
                    distance_m=active_distance,
                    waterway_distance_m=waterway_distance,
                    full_route_distance_m=full_route_distance,
                    selected_geometry_distance_m=selected_geometry_distance,
                )
            )

        def identity(match: CatalogSourceMatch):
            return match.place.kind, match.place.osm_type.value, match.place.osm_id

        if policy.basis in {"route", "waterway"}:
            matches.sort(key=lambda match: (match.distance_m, *identity(match)))
        else:
            matches.sort(key=identity)
        return CatalogSourceResult(matches=tuple(matches), work_used=work_used)

    def query_nearby(
        self,
        *,
        target_bng: BaseGeometry,
        radius_m: float,
        kinds: frozenset[str],
        text: str | None,
        work_budget: int,
        result_budget: int,
    ) -> CatalogSourceResult:
        """Return bounded catalog matches near a metric target geometry."""
        selected_kinds = self._validate_kinds(kinds)
        self._validate_budgets(work_budget, result_budget)
        if not math.isfinite(radius_m) or not 0 <= radius_m <= MAX_CATALOG_RADIUS_M:
            raise ValueError(
                f"catalog query radius must be from 0 through {MAX_CATALOG_RADIUS_M:g} m"
            )
        if not selected_kinds or self.metric_tree is None:
            return CatalogSourceResult(matches=(), work_used=0)

        positions = sorted(
            int(position)
            for position in self.metric_tree.query(
                target_bng,
                predicate="dwithin",
                distance=radius_m,
            )
        )
        work_used = len(positions)
        self._check_work(work_used, work_budget)
        search_text = self._normalize_text(text)
        matches: list[CatalogSourceMatch] = []
        for position in positions:
            place = self.places[position]
            if place.kind not in selected_kinds:
                continue
            if not self._matches_text(self.search_names[position], search_text):
                continue
            distance_m = float(self.metric_geometries[position].distance(target_bng))
            if distance_m > radius_m:
                continue
            if len(matches) >= result_budget:
                raise CatalogQueryLimitError("result")
            matches.append(CatalogSourceMatch(place=place, distance_m=distance_m))

        matches.sort(
            key=lambda match: (
                match.distance_m,
                match.place.kind,
                match.place.osm_type.value,
                match.place.osm_id,
            )
        )
        return CatalogSourceResult(matches=tuple(matches), work_used=work_used)
