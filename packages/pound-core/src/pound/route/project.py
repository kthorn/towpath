"""Projection helpers for canonical compact-graph edge handles."""

import math
from typing import Any, cast

import networkx as nx
from pyproj import Transformer
from shapely import transform
from shapely.geometry import LineString, Point

from pound.geometry import edge_line_wgs84 as _edge_line_wgs84
from pound.schemas import CanalPointHandle, Coordinate, ProjectedCanalPoint

_TO_BNG = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
_TO_WGS84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)


def _same_coordinate(first: tuple[float, float], second: tuple[float, float]) -> bool:
    return first == second or (
        round(first[0], 7) == round(second[0], 7) and round(first[1], 7) == round(second[1], 7)
    )


def canonical_edge_line_wgs84(graph: nx.Graph, edge: tuple[int, int]) -> LineString:
    """Return one edge's WGS84 geometry oriented from its lower UID to its higher UID."""
    u, v = edge
    if u >= v:
        raise ValueError("edge must be in canonical order")
    if not graph.has_edge(u, v):
        raise ValueError(f"edge {edge!r} is absent from graph")
    line = _edge_line_wgs84(graph, u, v, graph.edges[u, v])
    coordinates = list(line.coords)
    if len(coordinates) < 2:
        raise ValueError(f"edge {edge!r} has invalid geometry")
    low_coordinate = (graph.nodes[u]["lon"], graph.nodes[u]["lat"])
    if _same_coordinate((float(coordinates[0][0]), float(coordinates[0][1])), low_coordinate):
        return line
    if _same_coordinate((float(coordinates[-1][0]), float(coordinates[-1][1])), low_coordinate):
        return LineString(tuple(reversed(coordinates)))
    raise ValueError(f"edge {edge!r} geometry does not meet node {u!r}")


def metric_edge_line(graph: nx.Graph, edge: tuple[int, int]) -> LineString:
    """Return a canonical edge transformed to metric British National Grid coordinates."""
    return cast(
        LineString,
        transform(
            canonical_edge_line_wgs84(graph, edge),
            cast(Any, _TO_BNG.transform),
            interleaved=False,
        ),
    )


def _coordinate_from_metric_point(point: Point) -> Coordinate:
    projected = transform(point, cast(Any, _TO_WGS84.transform), interleaved=False)
    return Coordinate(lat=float(projected.y), lon=float(projected.x))


def project_handle(handle: CanalPointHandle, graph: nx.Graph) -> ProjectedCanalPoint:
    """Project a canonical edge handle onto the edge's metric polyline."""
    handle = CanalPointHandle.model_validate(handle)
    u, v = handle.edge
    line = metric_edge_line(graph, handle.edge)
    if line.is_empty or not math.isfinite(line.length) or line.length <= 0:
        raise ValueError(f"edge {handle.edge!r} has no measurable geometry")
    if handle.fraction == 0:
        coordinate = Coordinate(lat=graph.nodes[u]["lat"], lon=graph.nodes[u]["lon"])
    elif handle.fraction == 1:
        coordinate = Coordinate(lat=graph.nodes[v]["lat"], lon=graph.nodes[v]["lon"])
    else:
        coordinate = _coordinate_from_metric_point(line.interpolate(handle.fraction * line.length))
    return ProjectedCanalPoint(handle=handle, coordinate=coordinate)


# Explicit alias for callers that prefer the domain name.
project_canal_point = project_handle
