"""Pure preparation of bounded display geometry for the canal network."""

import math

import networkx as nx
from pound.schemas import GeoJSONLineString
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge, unary_union

MAX_NETWORK_VERTICES = 100_000
_DISPLAY_SIMPLIFY_TOLERANCE = 1e-5


def prepare_network_geometry(
    graph: nx.Graph, max_vertices: int = MAX_NETWORK_VERTICES
) -> tuple[GeoJSONLineString, ...]:
    """Convert graph edge geometry to simplified, branch-preserving GeoJSON lines."""
    if isinstance(max_vertices, bool) or not isinstance(max_vertices, int) or max_vertices < 1:
        raise ValueError("max_vertices must be a positive integer")

    source_lines = []
    for u, v, data in graph.edges(data=True):
        try:
            coordinates = [(float(lon), float(lat)) for lat, lon in data["geometry"]]
            if len(coordinates) < 2 or any(
                not math.isfinite(value) for coordinate in coordinates for value in coordinate
            ):
                raise ValueError("expected at least two finite coordinates")
            line = LineString(coordinates)
            if line.is_empty or not line.is_valid:
                raise ValueError("expected valid line geometry")
            source_lines.append(line)
        except Exception as exc:
            raise ValueError(f"Could not convert geometry for graph edge {u!r}-{v!r}") from exc

    if not source_lines:
        return ()

    try:
        unioned = unary_union(source_lines)
        if isinstance(unioned, LineString):
            merged = unioned
        elif isinstance(unioned, MultiLineString):
            merged = linemerge(unioned)
        else:
            raise ValueError(f"union result {unioned.geom_type} is not line geometry")
    except Exception as exc:
        raise ValueError("Could not union canal network geometry") from exc

    if isinstance(merged, LineString):
        lines = (merged,)
    elif isinstance(merged, MultiLineString):
        lines = tuple(merged.geoms)
    else:
        raise ValueError(f"Could not convert union result {merged.geom_type} to line strings")

    if max_vertices < 2 * len(lines):
        raise ValueError("max_vertices is too small to retain every network line")

    tolerance = _DISPLAY_SIMPLIFY_TOLERANCE
    for _ in range(64):
        simplified_lines = tuple(
            line.simplify(tolerance, preserve_topology=False) for line in lines
        )
        if any(
            not isinstance(line, LineString) or line.is_empty or len(line.coords) < 2
            for line in simplified_lines
        ):
            raise ValueError("Simplification produced invalid network geometry")

        if sum(len(line.coords) for line in simplified_lines) <= max_vertices:
            return tuple(
                GeoJSONLineString(
                    coordinates=[(float(lon), float(lat)) for lon, lat in line.coords]
                )
                for line in simplified_lines
            )
        tolerance *= 2

    raise ValueError("Could not simplify network geometry to the requested vertex ceiling")
