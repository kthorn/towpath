import math
from typing import Any, cast

import networkx as nx
from pyproj import Transformer
from shapely import transform
from shapely.geometry import LineString, Point

LOCK_SOURCE_TOLERANCE_M = 25.0
_ROUND = 7
_TO_BNG = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
_TO_WGS84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)


def node_key(lat: float, lon: float) -> tuple[float, float]:
    return round(lat, _ROUND), round(lon, _ROUND)


def haversine_m(a, b) -> float:
    radius_m = 6_371_000.0
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius_m * math.asin(math.sqrt(h))


def project_point_to_line(
    line: object, lat: object, lon: object
) -> tuple[tuple[float, float], float] | None:
    """Project a finite WGS84 source point onto a line and return metric distance."""
    if (
        isinstance(lat, bool)
        or isinstance(lon, bool)
        or not isinstance(lat, (int, float))
        or not isinstance(lon, (int, float))
        or not isinstance(line, (tuple, list))
    ):
        return None
    try:
        source_lat = float(lat)
        source_lon = float(lon)
        if not math.isfinite(source_lat) or not math.isfinite(source_lon):
            return None
        coordinates = []
        for point in line:
            if not isinstance(point, (tuple, list)) or len(point) != 2:
                return None
            point_lat, point_lon = point
            if (
                isinstance(point_lat, bool)
                or isinstance(point_lon, bool)
                or not isinstance(point_lat, (int, float))
                or not isinstance(point_lon, (int, float))
            ):
                return None
            point_lat = float(point_lat)
            point_lon = float(point_lon)
            if not math.isfinite(point_lat) or not math.isfinite(point_lon):
                return None
            coordinates.append((point_lon, point_lat))
        if len(coordinates) < 2:
            return None
        edge = transform(LineString(coordinates), cast(Any, _TO_BNG.transform), interleaved=False)
        source = Point(*_TO_BNG.transform(source_lon, source_lat))
        if edge.is_empty or edge.length == 0:
            return None
        distance_m = float(source.distance(edge))
        projected = edge.interpolate(edge.project(source))
        if distance_m <= 1e-6:
            return (source_lat, source_lon), distance_m
        projected_wgs84 = transform(projected, cast(Any, _TO_WGS84.transform), interleaved=False)
        return (float(projected_wgs84.y), float(projected_wgs84.x)), distance_m
    except (TypeError, ValueError, RuntimeError, OverflowError):
        return None


def edge_line_wgs84(graph: nx.Graph, u: int, v: int, data: dict[str, Any]) -> LineString:
    coordinates = data.get("geometry")
    if not coordinates:
        coordinates = [
            (graph.nodes[u]["lat"], graph.nodes[u]["lon"]),
            (graph.nodes[v]["lat"], graph.nodes[v]["lon"]),
        ]
    return LineString([(lon, lat) for lat, lon in coordinates])
