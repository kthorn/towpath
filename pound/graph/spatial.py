"""Immutable, reusable spatial indexes for a loaded routing graph."""

import math
from dataclasses import dataclass
from typing import Any

import networkx as nx
from pyproj import Transformer
from shapely import transform, wkb
from shapely.geometry import LineString, Point, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points
from shapely.strtree import STRtree

from pound.graph.build import _haversine_m
from pound.graph.pois import _CORRIDOR_M, _edge_line_wgs84, _routing_eligible
from pound.ingest.ir import PointOfInterest
from pound.schemas import Coordinate, GeoJSONLineString, MapBounds, RoutePoi

_EARTH_RADIUS_M = 6_371_000.0
_MAX_RADIUS_M = math.pi * _EARTH_RADIUS_M
_INITIAL_RADIUS_M = 100.0
_TO_BNG = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
_TO_WGS84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)


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

    pois: tuple[PointOfInterest, ...]
    poi_points: tuple[Point, ...]
    poi_tree: STRtree | None

    def __init__(self, pois: tuple[PointOfInterest, ...]) -> None:
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
            _TO_BNG.transform,
            interleaved=False,
        )
        selected_kinds = set(kinds)
        matches: list[RoutePoi] = []
        matching_count = 0
        for position in positions:
            poi = self.pois[position]
            if poi.kind not in selected_kinds:
                continue
            point_bng = transform(self.poi_points[position], _TO_BNG.transform, interleaved=False)
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
                    _edge_line_wgs84(graph, u, v, data),
                    _TO_BNG.transform,
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
        geometry_bng = transform(geometry, _TO_BNG.transform, interleaved=False)
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
        projected = transform(projected_bng, _TO_WGS84.transform, interleaved=False)
        return edge_key, projected, distance


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
