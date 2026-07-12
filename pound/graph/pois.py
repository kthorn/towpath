"""Normalize OSM POI geometry and attach it to routing-eligible waterway edges."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import networkx as nx
from pyproj import Transformer
from shapely import from_wkt, make_valid, transform
from shapely.errors import GEOSException
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points
from shapely.strtree import STRtree

from pound.ingest.ir import PoiCandidate, PoiCategory, PointOfInterest

_TO_BNG = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
_TO_WGS84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
_CORRIDOR_M = {
    PoiCategory.CANAL_SERVICE: 250.0,
    PoiCategory.PEDESTRIAN_ACCESS: 250.0,
    PoiCategory.PROVISIONS: 1000.0,
    PoiCategory.TRANSPORT: 1000.0,
}
_NON_NAVIGABLE_BOAT_VALUES = {"no", "unsuitable", "canoe"}


@dataclass(frozen=True)
class PoiBuildResult:
    pois: tuple[PointOfInterest, ...]
    summary: dict[str, int]


def _pound_to_xy(coordinate: tuple[float, float]) -> tuple[float, float]:
    """Convert Pound's (lat, lon) tuple to Shapely's (x=lon, y=lat)."""
    lat, lon = coordinate
    return lon, lat


def _xy_to_pound(point: Point) -> tuple[float, float]:
    """Convert a Shapely point to Pound's (lat, lon) ordering."""
    return point.y, point.x


def _to_bng(geometry):
    return transform(geometry, _TO_BNG.transform, interleaved=False)


def _to_wgs84(geometry):
    return transform(geometry, _TO_WGS84.transform, interleaved=False)


def _routing_eligible(data: dict[str, Any]) -> bool:
    if data.get("navigable") is False or data.get("routing_eligible") is False:
        return False
    tags = data.get("tags") or {}
    return data.get("boat", tags.get("boat")) not in _NON_NAVIGABLE_BOAT_VALUES


def _edge_line_wgs84(graph: nx.Graph, u: int, v: int, data: dict[str, Any]) -> LineString:
    coordinates = data.get("geometry")
    if not coordinates:
        coordinates = [
            (graph.nodes[u]["lat"], graph.nodes[u]["lon"]),
            (graph.nodes[v]["lat"], graph.nodes[v]["lon"]),
        ]
    return LineString([_pound_to_xy(coordinate) for coordinate in coordinates])


def _candidate_sort_key(candidate: PoiCandidate) -> tuple[str, int, str, str]:
    # The serialized candidate provides a stable winner when duplicate readers disagree.
    return (*candidate.identity, candidate.model_dump_json())


def _normalized_geometry(candidate: PoiCandidate):
    try:
        geometry = from_wkt(candidate.geometry_wkt)
    except (GEOSException, ValueError):
        return None, "invalid_geometry"
    if geometry.is_empty:
        return None, "empty_geometry"
    if not geometry.is_valid:
        try:
            geometry = make_valid(geometry)
        except GEOSException:
            return None, "invalid_geometry"
    if geometry.is_empty or not geometry.is_valid:
        return None, "invalid_geometry"
    usable_types = {
        "point": {"Point"},
        "area": {"Polygon", "MultiPolygon"},
        "derived_path": {"LineString", "MultiLineString"},
    }
    if geometry.geom_type not in usable_types[candidate.geometry_source]:
        return None, "invalid_geometry"
    return geometry, None


def attach_pois(graph: nx.Graph, candidates: Iterable[PoiCandidate]) -> PoiBuildResult:
    """Return deterministically normalized POIs attached to eligible graph edges.

    Distances and nearest-point operations are performed in British National Grid.
    Neither the graph nor any input candidate is modified.
    """
    edge_records: list[tuple[tuple[int, int], LineString]] = []
    for u, v, data in graph.edges(data=True):
        if not _routing_eligible(data):
            continue
        key = (min(u, v), max(u, v))
        edge_records.append((key, _to_bng(_edge_line_wgs84(graph, u, v, data))))
    edge_records.sort(key=lambda record: record[0])
    edge_lines = [record[1] for record in edge_records]
    tree = STRtree(edge_lines) if edge_lines else None

    summary = {
        "duplicate_identities": 0,
        "empty_geometry": 0,
        "invalid_geometry": 0,
        "rejected_by_corridor": 0,
    }
    pois: list[PointOfInterest] = []
    seen = set()
    for candidate in sorted(candidates, key=_candidate_sort_key):
        if candidate.identity in seen:
            summary["duplicate_identities"] += 1
            continue
        seen.add(candidate.identity)
        geometry_wgs84, skip_reason = _normalized_geometry(candidate)
        if skip_reason is not None:
            summary[skip_reason] += 1
            continue
        if tree is None:
            summary["rejected_by_corridor"] += 1
            continue

        geometry_bng = _to_bng(geometry_wgs84)
        indexes, distances = tree.query_nearest(
            geometry_bng, all_matches=True, return_distance=True
        )
        ranked = sorted(
            (float(distance), edge_records[int(index)][0], int(index))
            for index, distance in zip(indexes, distances, strict=True)
        )
        distance_m, edge_key, edge_index = ranked[0]
        if distance_m > _CORRIDOR_M[candidate.category]:
            summary["rejected_by_corridor"] += 1
            continue

        candidate_nearest_bng, projected_bng = nearest_points(
            geometry_bng, edge_lines[edge_index]
        )
        if candidate.geometry_source == "derived_path":
            display_wgs84 = _to_wgs84(candidate_nearest_bng)
        elif geometry_wgs84.geom_type == "Point":
            display_wgs84 = geometry_wgs84
        else:
            display_wgs84 = geometry_wgs84.representative_point()
        projected_wgs84 = _to_wgs84(projected_bng)
        lat, lon = _xy_to_pound(display_wgs84)
        projected_lat, projected_lon = _xy_to_pound(projected_wgs84)

        endpoint_choices = []
        for uid in edge_key:
            node = graph.nodes[uid]
            endpoint = Point(*_TO_BNG.transform(node["lon"], node["lat"]))
            endpoint_choices.append((geometry_bng.distance(endpoint), uid))
        nearest_node_uid = min(endpoint_choices)[1]

        pois.append(
            PointOfInterest(
                osm_type=candidate.osm_type,
                osm_id=candidate.osm_id,
                category=candidate.category,
                kind=candidate.kind,
                name=candidate.name,
                lat=lat,
                lon=lon,
                source_tags=dict(candidate.tags),
                geometry_source=candidate.geometry_source,
                nearest_waterway_distance_m=distance_m,
                nearest_edge=edge_key,
                nearest_node_uid=nearest_node_uid,
                projected_lat=projected_lat,
                projected_lon=projected_lon,
            )
        )

    return PoiBuildResult(pois=tuple(pois), summary=summary)
