"""Immutable, reusable spatial indexes for a loaded routing graph."""

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast

import networkx as nx
from pyproj import Transformer
from shapely import transform, wkb
from shapely.geometry import LineString, Point, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points
from shapely.strtree import STRtree

from pound.geometry import haversine_m as _haversine_m
from pound.models import POI_CORRIDOR_M as _CORRIDOR_M
from pound.models import RuntimePoi
from pound.route.project import (
    canonical_edge_line_wgs84 as _canonical_edge_line_wgs84,
)
from pound.route.project import (
    metric_edge_line as _metric_edge_line,
)
from pound.schemas import (
    CanalPointHandle,
    Coordinate,
    GeoJSONLineString,
    MapBounds,
    ProjectedCanalPoint,
    RoutePoi,
)

_EARTH_RADIUS_M = 6_371_000.0
_MAX_RADIUS_M = math.pi * _EARTH_RADIUS_M
_INITIAL_RADIUS_M = 100.0
_TO_BNG = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
_TO_WGS84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)


def _routing_eligible(data: dict[str, Any]) -> bool:
    return data.get("navigable") is not False and data.get("routing_eligible") is not False


def lat_lon_to_xy(*, lat: float, lon: float) -> tuple[float, float]:
    """Convert named API coordinates to Shapely's unambiguous ``(x, y)`` order."""
    return lon, lat


def _normalize_lon(lon: float) -> float:
    normalized = (lon + 180.0) % 360.0 - 180.0
    return 180.0 if normalized == -180.0 and lon > 0 else normalized


def spherical_envelopes(*, lon: float, lat: float, radius_m: float) -> tuple[Any, ...]:
    """Return WGS84 boxes conservatively containing a spherical-radius circle."""
    delta = min(radius_m / _EARTH_RADIUS_M, math.pi)
    lat_radians = math.radians(lat)
    south_radians = max(-math.pi / 2, lat_radians - delta)
    north_radians = min(math.pi / 2, lat_radians + delta)
    south = math.degrees(south_radians)
    north = math.degrees(north_radians)
    if south_radians <= -math.pi / 2 or north_radians >= math.pi / 2:
        return (box(-180.0, south, 180.0, north),)

    half_width = math.asin(min(1.0, math.sin(delta) / math.cos(lat_radians)))
    west_raw = lon - math.degrees(half_width)
    east_raw = lon + math.degrees(half_width)
    if east_raw - west_raw >= 360.0:
        return (box(-180.0, south, 180.0, north),)
    west = _normalize_lon(west_raw)
    east = _normalize_lon(east_raw)
    if west <= east:
        return (box(west, south, east, north),)
    return (box(-180.0, south, east, north), box(west, south, 180.0, north))


@dataclass(frozen=True)
class PoiQueryResult:
    """Bounded POI query output, with a sentinel for an overly broad match."""

    pois: tuple[RoutePoi, ...]
    matching_count: int
    zoom_in_required: bool


@dataclass(frozen=True)
class PoiSpatialIndex:
    """Stable WGS84 POI points and a metric route-corridor query tree."""

    pois: tuple[RuntimePoi, ...]
    poi_points: tuple[Point, ...]
    poi_tree: STRtree | None

    def __init__(self, pois: tuple[RuntimePoi, ...]) -> None:
        ordered_pois = tuple(
            sorted(pois, key=lambda poi: (poi.osm_type.value, poi.osm_id, poi.kind))
        )
        points = tuple(Point(*lat_lon_to_xy(lat=poi.lat, lon=poi.lon)) for poi in ordered_pois)
        object.__setattr__(self, "pois", ordered_pois)
        object.__setattr__(self, "poi_points", points)
        object.__setattr__(self, "poi_tree", STRtree(points) if points else None)

    def query(
        self,
        bounds: MapBounds,
        route_geometry: GeoJSONLineString,
        kinds: tuple[str, ...],
    ) -> PoiQueryResult:
        """Return selected POIs in a viewport and category-specific route corridor."""
        if self.poi_tree is None or not kinds:
            return PoiQueryResult(pois=(), matching_count=0, zoom_in_required=False)

        viewport = box(bounds.west, bounds.south, bounds.east, bounds.north)
        positions = sorted(int(position) for position in self.poi_tree.query(viewport))
        route = transform(
            LineString(route_geometry.coordinates),
            cast(Any, _TO_BNG.transform),
            interleaved=False,
        )
        selected_kinds = set(kinds)
        matches: list[RoutePoi] = []
        matching_count = 0
        for position in positions:
            poi = self.pois[position]
            if poi.kind not in selected_kinds:
                continue
            point_bng = transform(
                self.poi_points[position], cast(Any, _TO_BNG.transform), interleaved=False
            )
            distance_m = float(point_bng.distance(route))
            if distance_m > _CORRIDOR_M[poi.category]:
                continue
            matching_count += 1
            if matching_count > 1000:
                return PoiQueryResult(pois=(), matching_count=1001, zoom_in_required=True)
            matches.append(
                RoutePoi(
                    identity=f"{poi.osm_type.value}/{poi.osm_id}/{poi.kind}",
                    kind=poi.kind,
                    name=poi.name,
                    coordinate=Coordinate(lat=poi.lat, lon=poi.lon),
                    distance_to_route_m=distance_m,
                )
            )
        return PoiQueryResult(
            pois=tuple(matches), matching_count=matching_count, zoom_in_required=False
        )


@dataclass(frozen=True)
class GraphSpatialIndex:
    """Stable node and navigable-edge STRtrees derived from one graph snapshot."""

    node_uids: tuple[int, ...]
    node_points: tuple[Point, ...]
    node_tree: STRtree | None
    edge_keys: tuple[tuple[int, int], ...]
    edge_lines: tuple[Any, ...]
    edge_tree: STRtree | None
    candidate_index: Any

    def __init__(self, graph: nx.Graph) -> None:
        node_uids = tuple(sorted(graph.nodes))
        node_points = tuple(
            Point(
                *lat_lon_to_xy(
                    lat=graph.nodes[uid]["lat"],
                    lon=graph.nodes[uid]["lon"],
                )
            )
            for uid in node_uids
        )
        edge_records = sorted(
            (
                (min(u, v), max(u, v)),
                transform(
                    _canonical_edge_line_wgs84(graph, (min(u, v), max(u, v))),
                    cast(Any, _TO_BNG.transform),
                    interleaved=False,
                ),
            )
            for u, v, data in graph.edges(data=True)
            if _routing_eligible(data)
        )
        edge_keys = tuple(record[0] for record in edge_records)
        edge_lines = tuple(record[1] for record in edge_records)
        object.__setattr__(self, "node_uids", node_uids)
        object.__setattr__(self, "node_points", node_points)
        object.__setattr__(self, "node_tree", STRtree(node_points) if node_points else None)
        object.__setattr__(self, "edge_keys", edge_keys)
        object.__setattr__(self, "edge_lines", edge_lines)
        object.__setattr__(self, "edge_tree", STRtree(edge_lines) if edge_lines else None)
        object.__setattr__(self, "candidate_index", CandidateSpatialIndex(graph))

    def query_node_uids(self, envelopes: tuple[Any, ...]) -> tuple[int, ...]:
        """Return stable UIDs whose points intersect any supplied envelope."""
        if self.node_tree is None:
            return ()
        positions = {
            int(position) for envelope in envelopes for position in self.node_tree.query(envelope)
        }
        return tuple(self.node_uids[position] for position in sorted(positions))

    def distance_to_waterway(self, geometry: BaseGeometry | bytes) -> float | None:
        """Return metric distance from normalized catalog geometry to a navigable edge."""
        if self.edge_tree is None:
            return None
        if isinstance(geometry, bytes):
            geometry = wkb.loads(geometry)
        if not isinstance(geometry, BaseGeometry):
            raise TypeError("geometry must be a Shapely geometry or WKB bytes")
        if geometry.is_empty:
            return None
        geometry_bng = transform(geometry, cast(Any, _TO_BNG.transform), interleaved=False)
        _positions, distances = self.edge_tree.query_nearest(
            geometry_bng, all_matches=True, return_distance=True
        )
        if len(distances) == 0:
            return None
        return float(min(distances))

    def project_to_nearest_edge(
        self, lat: float, lon: float
    ) -> tuple[tuple[int, int], Point, float]:
        """Return canonical nearest edge, projected WGS84 point, and metric distance."""
        if self.edge_tree is None:
            raise ValueError("no navigable edges to project against")
        x, y = lat_lon_to_xy(lat=lat, lon=lon)
        query_bng = Point(*_TO_BNG.transform(x, y))
        positions, distances = self.edge_tree.query_nearest(
            query_bng, all_matches=True, return_distance=True
        )
        ranked = sorted(
            (float(distance), self.edge_keys[int(position)], int(position))
            for position, distance in zip(positions, distances, strict=True)
        )
        distance, edge_key, position = ranked[0]
        _, projected_bng = nearest_points(query_bng, self.edge_lines[position])
        projected = transform(projected_bng, cast(Any, _TO_WGS84.transform), interleaved=False)
        return edge_key, projected, distance


@dataclass(frozen=True)
class CandidateSpatialIndex:
    """Immutable metric edge and fixed projected-candidate indexes."""

    spacing_m: float
    edge_keys: tuple[tuple[int, int], ...]
    edge_lines: tuple[Any, ...]
    edge_tree: STRtree | None
    eligible_edge_keys: tuple[tuple[int, int], ...]
    eligible_edge_lines: tuple[Any, ...]
    eligible_edge_tree: STRtree | None
    endpoint_points: tuple[ProjectedCanalPoint, ...]
    endpoint_geometries: tuple[Point, ...]
    endpoint_tree: STRtree | None
    candidate_points: tuple[ProjectedCanalPoint, ...]
    candidate_geometries: tuple[Point, ...]
    candidate_tree: STRtree | None
    candidate_wgs84_points: tuple[Point, ...]
    candidate_wgs84_tree: STRtree | None
    candidate_display_names: tuple[str, ...]
    candidate_bounds: tuple[float, float, float, float] | None
    edge_positions: Any
    edge_names: tuple[str | None, ...]
    node_names: tuple[tuple[int, str], ...]

    def __init__(self, graph: nx.Graph, spacing_m: float = 250.0) -> None:
        if not isinstance(graph, nx.Graph) or graph.is_directed() or graph.is_multigraph():
            raise TypeError("expected an undirected networkx.Graph")
        if (
            isinstance(spacing_m, bool)
            or not isinstance(spacing_m, (int, float))
            or not math.isfinite(spacing_m)
            or spacing_m <= 0
        ):
            raise ValueError("spacing_m must be a finite number greater than zero")

        edge_records = []
        for u, v, data in graph.edges(data=True):
            if not _routing_eligible(data):
                continue
            edge = (min(int(u), int(v)), max(int(u), int(v)))
            line = _metric_edge_line(graph, edge)
            edge_records.append((edge, line, data.get("candidate_eligible", True) is not False))
        edge_records.sort(key=lambda record: record[0])

        edge_keys = tuple(record[0] for record in edge_records)
        edge_lines = tuple(record[1] for record in edge_records)
        eligible_records = tuple(
            record for record in edge_records if record[2] and record[1].length > 0
        )
        eligible_edge_keys = tuple(record[0] for record in eligible_records)
        eligible_edge_lines = tuple(record[1] for record in eligible_records)
        edge_names = tuple(
            self._normalized_name(graph.edges[edge].get("name")) for edge in edge_keys
        )
        node_names = tuple(
            (int(uid), name)
            for uid, data in sorted(graph.nodes(data=True), key=lambda item: item[0])
            if (name := self._normalized_name(data.get("name"))) is not None
        )

        endpoint_by_coordinate: dict[tuple[float, float], ProjectedCanalPoint] = {}
        for low, high in edge_keys:
            for uid, fraction in ((low, 0.0), (high, 1.0)):
                coordinate = Coordinate(lat=graph.nodes[uid]["lat"], lon=graph.nodes[uid]["lon"])
                endpoint_by_coordinate.setdefault(
                    (coordinate.lat, coordinate.lon),
                    ProjectedCanalPoint(
                        handle=CanalPointHandle(edge=(low, high), fraction=fraction),
                        coordinate=coordinate,
                    ),
                )
        endpoint_points = tuple(sorted(endpoint_by_coordinate.values(), key=self._point_sort_key))
        endpoint_geometries = tuple(
            self._metric_point(point.coordinate) for point in endpoint_points
        )

        fixed_points: dict[CanalPointHandle, ProjectedCanalPoint] = {
            point.handle: point for point in endpoint_points
        }
        for edge, line, eligible in edge_records:
            if not eligible or line.length <= 0:
                continue
            distance = float(spacing_m)
            while distance < line.length - 1e-9:
                fraction = distance / line.length
                handle = CanalPointHandle(edge=edge, fraction=fraction)
                fixed_points.setdefault(handle, self._point_at(line, handle))
                distance += float(spacing_m)
        candidate_points = tuple(sorted(fixed_points.values(), key=self._point_sort_key))
        candidate_geometries = tuple(
            self._metric_point(point.coordinate) for point in candidate_points
        )
        candidate_wgs84_points = tuple(
            Point(point.coordinate.lon, point.coordinate.lat) for point in candidate_points
        )
        candidate_display_names = tuple(
            self._display_name(point.handle, point.coordinate, edge_keys, edge_names, node_names)
            for point in candidate_points
        )
        candidate_bounds = (
            (
                min(point.x for point in candidate_geometries),
                min(point.y for point in candidate_geometries),
                max(point.x for point in candidate_geometries),
                max(point.y for point in candidate_geometries),
            )
            if candidate_geometries
            else None
        )

        object.__setattr__(self, "spacing_m", float(spacing_m))
        object.__setattr__(self, "edge_keys", edge_keys)
        object.__setattr__(self, "edge_lines", edge_lines)
        object.__setattr__(self, "edge_tree", STRtree(edge_lines) if edge_lines else None)
        object.__setattr__(self, "eligible_edge_keys", eligible_edge_keys)
        object.__setattr__(self, "eligible_edge_lines", eligible_edge_lines)
        object.__setattr__(
            self,
            "eligible_edge_tree",
            STRtree(eligible_edge_lines) if eligible_edge_lines else None,
        )
        object.__setattr__(self, "endpoint_points", endpoint_points)
        object.__setattr__(self, "endpoint_geometries", endpoint_geometries)
        object.__setattr__(
            self,
            "endpoint_tree",
            STRtree(endpoint_geometries) if endpoint_geometries else None,
        )
        object.__setattr__(self, "candidate_points", candidate_points)
        object.__setattr__(self, "candidate_geometries", candidate_geometries)
        object.__setattr__(
            self,
            "candidate_tree",
            STRtree(candidate_geometries) if candidate_geometries else None,
        )
        object.__setattr__(self, "candidate_wgs84_points", candidate_wgs84_points)
        object.__setattr__(
            self,
            "candidate_wgs84_tree",
            STRtree(candidate_wgs84_points) if candidate_wgs84_points else None,
        )
        object.__setattr__(self, "candidate_display_names", candidate_display_names)
        object.__setattr__(self, "candidate_bounds", candidate_bounds)
        object.__setattr__(
            self,
            "edge_positions",
            MappingProxyType({edge: position for position, edge in enumerate(edge_keys)}),
        )
        object.__setattr__(self, "edge_names", edge_names)
        object.__setattr__(self, "node_names", node_names)

    @staticmethod
    def _normalized_name(value: object) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _point_sort_key(point: ProjectedCanalPoint) -> tuple[int, int, float]:
        return (*point.handle.edge, point.handle.fraction)

    @staticmethod
    def _metric_point(coordinate: Coordinate) -> Point:
        return Point(*_TO_BNG.transform(coordinate.lon, coordinate.lat))

    @staticmethod
    def _point_at(line: Any, handle: CanalPointHandle) -> ProjectedCanalPoint:
        point_bng = line.interpolate(handle.fraction * line.length)
        point_wgs84 = transform(point_bng, cast(Any, _TO_WGS84.transform), interleaved=False)
        return ProjectedCanalPoint(
            handle=handle,
            coordinate=Coordinate(lat=float(point_wgs84.y), lon=float(point_wgs84.x)),
        )

    @classmethod
    def _edge_name(cls, data: dict[str, Any]) -> str | None:
        return cls._normalized_name(data.get("name"))

    @classmethod
    def _display_name(
        cls,
        handle: CanalPointHandle,
        coordinate: Coordinate,
        edge_keys: tuple[tuple[int, int], ...],
        edge_names: tuple[str | None, ...],
        node_names: tuple[tuple[int, str], ...],
    ) -> str:
        node_name_map = dict(node_names)
        low, high = handle.edge
        if handle.fraction == 0 and low in node_name_map:
            return node_name_map[low]
        if handle.fraction == 1 and high in node_name_map:
            return node_name_map[high]
        edge_position = edge_keys.index(handle.edge)
        edge_name = edge_names[edge_position]
        if edge_name is not None:
            return edge_name
        named_endpoints = [
            (fraction, node_name_map.get(uid)) for uid, fraction in ((low, 0), (high, 1))
        ]
        named_endpoints = [
            (fraction, name) for fraction, name in named_endpoints if name is not None
        ]
        if named_endpoints:
            return min(
                named_endpoints,
                key=lambda item: (abs(item[0] - handle.fraction), item[1]),
            )[1]
        return "Unnamed canal point"

    @property
    def sample_points(self) -> tuple[ProjectedCanalPoint, ...]:
        return self.candidate_points

    @property
    def sample_handles(self) -> tuple[CanalPointHandle, ...]:
        return tuple(point.handle for point in self.candidate_points)

    @property
    def sample_coordinates(self) -> tuple[Coordinate, ...]:
        return tuple(point.coordinate for point in self.candidate_points)

    def project(self, handle: CanalPointHandle) -> ProjectedCanalPoint:
        handle = CanalPointHandle.model_validate(handle)
        position = self.edge_positions.get(handle.edge)
        if position is None:
            raise ValueError(f"edge {handle.edge!r} is absent from candidate index")
        return self._point_at(self.edge_lines[position], handle)

    def display_name(self, handle: CanalPointHandle, coordinate: Coordinate | None = None) -> str:
        handle = CanalPointHandle.model_validate(handle)
        if coordinate is None:
            coordinate = self.project(handle).coordinate
        return self._display_name(
            handle, coordinate, self.edge_keys, self.edge_names, self.node_names
        )

    @staticmethod
    def _query_point(lat: float, lon: float) -> Point:
        return Point(*_TO_BNG.transform(lon, lat))

    def nearest_projection(
        self, lat: float, lon: float
    ) -> tuple[ProjectedCanalPoint, float] | None:
        query = self._query_point(lat, lon)
        options: list[tuple[float, CanalPointHandle, ProjectedCanalPoint]] = []
        if self.eligible_edge_tree is not None:
            positions, _ = self.eligible_edge_tree.query_nearest(
                query, all_matches=True, return_distance=True
            )
            for position in positions:
                line = self.eligible_edge_lines[int(position)]
                distance_along = line.project(query)
                fraction = distance_along / line.length
                if fraction <= 1e-12:
                    fraction = 0.0
                elif 1 - fraction <= 1e-12:
                    fraction = 1.0
                handle = CanalPointHandle(
                    edge=self.eligible_edge_keys[int(position)], fraction=fraction
                )
                projected = self._point_at(line, handle)
                options.append(
                    (
                        float(query.distance(self._metric_point(projected.coordinate))),
                        handle,
                        projected,
                    )
                )
        if self.endpoint_tree is not None:
            positions, distances = self.endpoint_tree.query_nearest(
                query, all_matches=True, return_distance=True
            )
            for position, distance in zip(positions, distances, strict=True):
                projected = self.endpoint_points[int(position)]
                options.append((float(distance), projected.handle, projected))
        if not options:
            return None
        distance, _, projected = min(
            options, key=lambda option: (option[0], *option[1].edge, option[1].fraction)
        )
        return projected, distance

    def nearest_samples(
        self, lat: float, lon: float, *, radius_m: float
    ) -> tuple[tuple[ProjectedCanalPoint, float], ...]:
        if self.candidate_tree is None:
            return ()
        if self.candidate_wgs84_tree is None:
            return ()
        envelopes = spherical_envelopes(lon=lon, lat=lat, radius_m=radius_m)
        positions = {
            int(position)
            for envelope in envelopes
            for position in self.candidate_wgs84_tree.query(envelope)
        }
        ranked = [
            (
                self.candidate_points[position],
                _haversine_m(
                    (lat, lon),
                    (
                        self.candidate_points[position].coordinate.lat,
                        self.candidate_points[position].coordinate.lon,
                    ),
                ),
            )
            for position in positions
        ]
        return tuple(sorted(ranked, key=lambda item: (item[1], self._point_sort_key(item[0]))))

    def sample_envelope_covers_all(self, lat: float, lon: float, radius_m: float) -> bool:
        return radius_m >= _MAX_RADIUS_M


def nearest_node_distances(
    lat: float,
    lon: float,
    graph: nx.Graph,
    index: GraphSpatialIndex,
    *,
    limit: int,
) -> list[tuple[float, int]]:
    """Return exact haversine nearest nodes via a conservative expanding query."""
    if limit <= 0:
        raise ValueError("limit must be greater than zero")
    k = min(limit, len(index.node_uids))
    if k == 0:
        return []
    x, y = lat_lon_to_xy(lat=lat, lon=lon)
    radius = _INITIAL_RADIUS_M
    while True:
        whole_world = radius >= _MAX_RADIUS_M
        search_radius = _MAX_RADIUS_M if whole_world else radius
        envelopes = spherical_envelopes(lon=x, lat=y, radius_m=search_radius)
        envelope_covers_world = len(envelopes) == 1 and envelopes[0].bounds == (
            -180.0,
            -90.0,
            180.0,
            90.0,
        )
        uids = index.query_node_uids(envelopes)
        ranked = sorted(
            (
                _haversine_m(
                    (lat, lon),
                    (graph.nodes[uid]["lat"], graph.nodes[uid]["lon"]),
                ),
                uid,
            )
            for uid in uids
        )
        if (
            whole_world
            or envelope_covers_world
            or (len(ranked) >= k and ranked[k - 1][0] <= search_radius)
        ):
            return ranked[:k]
        radius = min(radius * 2, _MAX_RADIUS_M)
