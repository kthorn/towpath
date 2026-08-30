"""Pure projected-point route planning over a compact runtime artifact."""

import json
import math
from collections import Counter
from dataclasses import dataclass
from heapq import heappop, heappush
from typing import Any, cast

import networkx as nx
from pyproj import Transformer  # pyright: ignore[reportMissingImports]
from shapely import transform
from shapely.geometry import Point
from shapely.ops import substring

from pound.artifact import RuntimeArtifact
from pound.geometry import LOCK_SOURCE_TOLERANCE_M
from pound.geometry import haversine_m as _haversine_m
from pound.geometry import project_point_to_line as project_point_to_edge
from pound.models import WayDimensions
from pound.route.cost import (
    LOCK_MINUTES,
    partial_traversal_time_min,
    resolve_movable_bridge_delay,
    traversal_time_min,
)
from pound.route.cost import is_eligible as _is_eligible
from pound.route.project import canonical_edge_line_wgs84, metric_edge_line, project_handle
from pound.schemas import (
    CanalPointHandle,
    CanalRouteResponse,
    Coordinate,
    DayPlan,
    GeoJSONLineString,
    ProjectedRouteConstraints,
    RouteAccessSegment,
    RouteDayGeometry,
    RouteLeg,
    RouteLock,
    RouteResult,
)

_TO_BNG = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
_TO_WGS84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
_DAY_SEGMENT_M = 250.0


@dataclass(frozen=True, slots=True)
class TraversedEdge:
    """One source-edge traversal, fractions always measured low UID to high UID."""

    u: int
    v: int
    start_fraction: float
    end_fraction: float
    full: bool


@dataclass(frozen=True, slots=True)
class ComputedTraversal:
    edges: tuple[TraversedEdge, ...]
    cost_min: float


@dataclass(frozen=True, slots=True)
class _RouteCandidate:
    traversal: ComputedTraversal
    endpoint_ids: tuple[int, ...]
    path: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _ReportSegment:
    traversal_index: int
    edge: TraversedEdge
    cost_min: float
    locks: int
    unknown_dimensions: bool


@dataclass(frozen=True, slots=True)
class _ComputedRoute:
    route: RouteResult
    traversal: ComputedTraversal
    segments: tuple[_ReportSegment, ...]
    day_ranges: tuple[tuple[int, int], ...]


class RouteUnavailableError(ValueError):
    """Raised when valid route inputs cannot produce an eligible graph path."""


def plan_projected_route(
    constraints: ProjectedRouteConstraints, *, artifact: RuntimeArtifact
) -> CanalRouteResponse:
    """Plan a route between two immutable compact-edge handles without graph mutation."""
    graph = artifact.graph
    _validate_handle(constraints.start, graph, "start")
    _validate_handle(constraints.end, graph, "end")
    start_point = project_handle(constraints.start, graph).coordinate

    if constraints.start == constraints.end:
        route = RouteResult(
            start=_point_name(constraints.start.edge, constraints.start.fraction, graph),
            end=_point_name(constraints.end.edge, constraints.end.fraction, graph),
            is_ring=False,
            legs=[],
            days=[],
            total_km=0.0,
            total_locks=0,
            total_minutes=0,
            amenities=[],
            warnings=[],
            access_segments=[],
            graph_source_date=str(artifact.metadata.get("fetched_at", "")),
        )
        point = (start_point.lon, start_point.lat)
        return CanalRouteResponse(
            route=route, geometry=GeoJSONLineString(coordinates=[point, point])
        )

    computed = _compute_route(constraints, graph)
    all_geometry = _joined_geometry(computed.traversal.edges, graph)
    if not all_geometry:
        end_point = project_handle(constraints.end, graph).coordinate
        all_geometry = [(start_point.lat, start_point.lon), (end_point.lat, end_point.lon)]
    day_geometries = []
    for day, (start, end) in enumerate(computed.day_ranges, start=1):
        points = _joined_geometry((segment.edge for segment in computed.segments[start:end]), graph)
        day_geometries.append(
            RouteDayGeometry(
                day=day,
                geometry=_to_geojson(points),
                start=Coordinate(lat=points[0][0], lon=points[0][1]),
                end=Coordinate(lat=points[-1][0], lon=points[-1][1]),
            )
        )
    route = computed.route.model_copy(
        update={"graph_source_date": str(artifact.metadata.get("fetched_at", ""))}
    )
    return CanalRouteResponse(
        route=route,
        geometry=_to_geojson(all_geometry),
        day_geometries=day_geometries,
        locks=_route_locks(computed, graph),
    )


def _validate_handle(handle: CanalPointHandle, graph: nx.Graph, field: str) -> None:
    u, v = handle.edge
    if not graph.has_edge(u, v):
        raise ValueError(f"{field} edge {handle.edge!r} is absent from graph")
    if 0 < handle.fraction < 1 and graph.edges[u, v].get("candidate_eligible", True) is False:
        raise ValueError(f"{field} interior must use a candidate-eligible edge")


def _edge_record(
    edge: tuple[int, int], start_fraction: float, end_fraction: float
) -> TraversedEdge:
    u, v = edge
    return TraversedEdge(
        u=u,
        v=v,
        start_fraction=start_fraction,
        end_fraction=end_fraction,
        full={start_fraction, end_fraction} == {0.0, 1.0},
    )


def _full_edge(u: int, v: int) -> TraversedEdge:
    low, high = sorted((u, v))
    return _edge_record((low, high), float(u == high), float(v == high))


def _arrived_node(edge: TraversedEdge) -> int | None:
    if edge.end_fraction == 0:
        return edge.u
    if edge.end_fraction == 1:
        return edge.v
    return None


def _edge_data(edge: TraversedEdge, graph: nx.Graph) -> dict[str, Any]:
    return graph.edges[edge.u, edge.v]


def _traversal_cost(edge: TraversedEdge, graph: nx.Graph, bridge_delay_min: float) -> float:
    data = _edge_data(edge, graph)
    arrived = _arrived_node(edge)
    arrived_bridges = (
        graph.nodes[arrived].get("movable_bridge_ids", ()) if arrived is not None else ()
    )
    if edge.full:
        return traversal_time_min(
            data,
            arrived_bridges,
            movable_bridge_delay_min=bridge_delay_min,
        )
    return partial_traversal_time_min(
        data,
        abs(edge.end_fraction - edge.start_fraction),
        arrived_bridges,
        movable_bridge_delay_min=bridge_delay_min,
    )


def _edge_eligibility(
    edge: TraversedEdge, constraints: ProjectedRouteConstraints, graph: nx.Graph
) -> tuple[bool, bool]:
    dimensions = _edge_data(edge, graph).get("dimensions", WayDimensions())
    return _is_eligible(
        constraints.boat_length_m,
        constraints.boat_beam_m,
        constraints.boat_draft_m,
        constraints.boat_height_m,
        dimensions,
    )


def _eligible_traversal(
    edges: tuple[TraversedEdge, ...], constraints: ProjectedRouteConstraints, graph: nx.Graph
) -> bool:
    return all(_edge_eligibility(edge, constraints, graph)[0] for edge in edges)


def _network_path(
    start: int,
    end: int,
    constraints: ProjectedRouteConstraints,
    graph: nx.Graph,
    bridge_delay_min: float,
) -> tuple[int, ...] | None:
    def weight(u: int, v: int, data: dict[str, Any]) -> float | None:
        eligible, _ = _is_eligible(
            constraints.boat_length_m,
            constraints.boat_beam_m,
            constraints.boat_draft_m,
            constraints.boat_height_m,
            data.get("dimensions", WayDimensions()),
        )
        if not eligible:
            return None
        return traversal_time_min(
            data,
            graph.nodes[v].get("movable_bridge_ids", ()),
            movable_bridge_delay_min=bridge_delay_min,
        )

    paths: dict[int, tuple[float, tuple[int, ...]]] = {start: (0.0, (start,))}
    queue: list[tuple[float, tuple[int, ...], int]] = [(0.0, (start,), start)]
    while queue:
        cost, path, node = heappop(queue)
        if paths.get(node) != (cost, path):
            continue
        if node == end:
            return path
        for neighbor in sorted(graph.neighbors(node)):
            edge_cost = weight(node, neighbor, graph.edges[node, neighbor])
            if edge_cost is None:
                continue
            candidate = (cost + edge_cost, path + (neighbor,))
            if candidate < paths.get(neighbor, (math.inf, ())):
                paths[neighbor] = candidate
                entry: tuple[float, tuple[int, ...], int] = (*candidate, neighbor)
                heappush(queue, entry)
    return None


def _candidate_for_endpoints(
    constraints: ProjectedRouteConstraints,
    graph: nx.Graph,
    bridge_delay_min: float,
    start_endpoint: tuple[int, float],
    end_endpoint: tuple[int, float],
) -> _RouteCandidate | None:
    start_node, start_fraction = start_endpoint
    end_node, end_fraction = end_endpoint
    path = _network_path(start_node, end_node, constraints, graph, bridge_delay_min)
    if path is None:
        return None

    records: list[TraversedEdge] = []
    if constraints.start.fraction != start_fraction:
        records.append(
            _edge_record(constraints.start.edge, constraints.start.fraction, start_fraction)
        )
    records.extend(_full_edge(u, v) for u, v in zip(path, path[1:], strict=False))
    if end_fraction != constraints.end.fraction:
        records.append(_edge_record(constraints.end.edge, end_fraction, constraints.end.fraction))
    edges = tuple(records)
    if not _eligible_traversal(edges, constraints, graph):
        return None
    return _RouteCandidate(
        traversal=ComputedTraversal(
            edges=edges,
            cost_min=sum(_traversal_cost(edge, graph, bridge_delay_min) for edge in edges),
        ),
        endpoint_ids=(start_node, end_node),
        path=path,
    )


def _compute_traversal(
    constraints: ProjectedRouteConstraints, graph: nx.Graph
) -> ComputedTraversal:
    bridge_delay_min = resolve_movable_bridge_delay(constraints.movable_bridge_delay_min)
    candidates: list[_RouteCandidate] = []

    if constraints.start.edge == constraints.end.edge:
        direct = _edge_record(
            constraints.start.edge,
            constraints.start.fraction,
            constraints.end.fraction,
        )
        if _eligible_traversal((direct,), constraints, graph):
            candidates.append(
                _RouteCandidate(
                    traversal=ComputedTraversal(
                        edges=(direct,),
                        cost_min=_traversal_cost(direct, graph, bridge_delay_min),
                    ),
                    endpoint_ids=(),
                    path=(),
                )
            )

    for start_endpoint in zip(constraints.start.edge, (0.0, 1.0), strict=True):
        for end_endpoint in zip(constraints.end.edge, (0.0, 1.0), strict=True):
            candidate = _candidate_for_endpoints(
                constraints,
                graph,
                bridge_delay_min,
                start_endpoint,
                end_endpoint,
            )
            if candidate is not None:
                candidates.append(candidate)

    if not candidates:
        raise RouteUnavailableError(
            "no path between the selected canal points meets the boat constraints"
        )
    return min(
        candidates,
        key=lambda candidate: (
            candidate.traversal.cost_min,
            candidate.endpoint_ids,
            candidate.path,
        ),
    ).traversal


def _split_edge(
    edge: TraversedEdge,
    graph: nx.Graph,
    event_fractions: tuple[float, ...] = (),
) -> tuple[TraversedEdge, ...]:
    if not _edge_data(edge, graph).get("geometry"):
        return (edge,)
    line = metric_edge_line(graph, (edge.u, edge.v))
    if line.length <= 0:
        return (edge,)
    low, high = sorted((edge.start_fraction, edge.end_fraction))
    fractions = [low]
    boundary = math.floor(low * line.length / _DAY_SEGMENT_M + 1) * _DAY_SEGMENT_M
    while boundary < high * line.length - 1e-9:
        fractions.append(boundary / line.length)
        boundary += _DAY_SEGMENT_M
    fractions.extend(fraction for fraction in event_fractions if low < fraction < high)
    fractions = sorted(set(fractions))
    fractions.append(high)
    if edge.start_fraction > edge.end_fraction:
        fractions.reverse()
    return tuple(
        TraversedEdge(edge.u, edge.v, start, end, False)
        for start, end in zip(fractions, fractions[1:], strict=False)
    )


def _contains_fraction(edge: TraversedEdge, fraction: float) -> bool:
    return (
        min(edge.start_fraction, edge.end_fraction) - 1e-9
        <= fraction
        <= max(edge.start_fraction, edge.end_fraction) + 1e-9
    )


def _lock_event_fractions(edge: TraversedEdge, graph: nx.Graph) -> tuple[float, ...]:
    lock_count = int(_edge_data(edge, graph).get("locks", 0))
    if not lock_count:
        return ()
    fractions = sorted(
        min(1.0, max(0.0, _coordinate_fraction((edge.u, edge.v), coordinate, graph)))
        for coordinate, _ in _lock_points(edge, graph)
    )
    if not fractions:
        fractions = [0.5]
    fractions.extend([fractions[-1]] * (lock_count - len(fractions)))
    return tuple(fractions[:lock_count])


def _lock_counts(
    pieces: tuple[TraversedEdge, ...], event_fractions: tuple[float, ...]
) -> list[int]:
    counts = [0] * len(pieces)
    for fraction in event_fractions:
        for index, piece in enumerate(pieces):
            if _contains_fraction(piece, fraction):
                counts[index] += 1
                break
    return counts


def _report_segments(
    traversal: ComputedTraversal, constraints: ProjectedRouteConstraints, graph: nx.Graph
) -> tuple[_ReportSegment, ...]:
    bridge_delay_min = resolve_movable_bridge_delay(constraints.movable_bridge_delay_min)
    segments: list[_ReportSegment] = []
    for traversal_index, edge in enumerate(traversal.edges):
        lock_events = _lock_event_fractions(edge, graph) if edge.full else ()
        pieces = _split_edge(edge, graph, lock_events)
        lock_counts = _lock_counts(pieces, lock_events)
        cruise_costs = [
            partial_traversal_time_min(
                _edge_data(piece, graph),
                abs(piece.end_fraction - piece.start_fraction),
                (),
                movable_bridge_delay_min=bridge_delay_min,
            )
            for piece in pieces
        ]
        final_cost = (
            _traversal_cost(edge, graph, bridge_delay_min)
            - sum(cruise_costs)
            - sum(lock_counts) * LOCK_MINUTES
        )
        _, unknown = _edge_eligibility(edge, constraints, graph)
        for index, (piece, cost) in enumerate(zip(pieces, cruise_costs, strict=True)):
            is_last = index == len(pieces) - 1
            segments.append(
                _ReportSegment(
                    traversal_index=traversal_index,
                    edge=piece,
                    cost_min=cost
                    + lock_counts[index] * LOCK_MINUTES
                    + (final_cost if is_last else 0),
                    locks=lock_counts[index],
                    unknown_dimensions=unknown,
                )
            )
    return tuple(segments)


def _compute_route(constraints: ProjectedRouteConstraints, graph: nx.Graph) -> _ComputedRoute:
    traversal = _compute_traversal(constraints, graph)
    segments = _report_segments(traversal, constraints, graph)
    legs = [
        RouteLeg(
            from_place=_point_name(
                (segment.edge.u, segment.edge.v), segment.edge.start_fraction, graph
            ),
            to_place=_point_name(
                (segment.edge.u, segment.edge.v), segment.edge.end_fraction, graph
            ),
            distance_km=round(
                float(_edge_data(segment.edge, graph)["length_m"])
                * abs(segment.edge.end_fraction - segment.edge.start_fraction)
                / 1000.0,
                4,
            ),
            locks=segment.locks,
            est_minutes=round(segment.cost_min),
            flagged_unknown_dims=segment.unknown_dimensions,
        )
        for segment in segments
    ]
    day_ranges = _day_path_ranges(legs, constraints.hours_per_day, constraints.days)
    access_segments = _access_segments(traversal, graph)
    unknown_edges = {
        str(_edge_data(edge, graph).get("osm_way_id"))
        for edge in traversal.edges
        if _edge_eligibility(edge, constraints, graph)[1]
    }
    warnings: list[str] = []
    if unknown_edges:
        warnings.append(f"draft/beam unknown on {len(unknown_edges)} segment(s)")
    warnings.extend(_access_warnings(access_segments))
    warnings.extend(_tunnel_warnings(traversal, graph, access_segments))
    days = _chunk_days(legs, constraints.hours_per_day, constraints.days)
    if any(day.cruising_minutes > constraints.hours_per_day * 60 for day in days):
        warnings.append("one or more days exceed hours_per_day budget")
    return _ComputedRoute(
        route=RouteResult(
            start=_point_name(constraints.start.edge, constraints.start.fraction, graph),
            end=_point_name(constraints.end.edge, constraints.end.fraction, graph),
            is_ring=False,
            legs=legs,
            days=days,
            total_km=round(
                sum(
                    float(_edge_data(edge, graph)["length_m"])
                    * abs(edge.end_fraction - edge.start_fraction)
                    / 1000.0
                    for edge in traversal.edges
                ),
                4,
            ),
            total_locks=sum(
                int(_edge_data(edge, graph).get("locks", 0))
                for edge in traversal.edges
                if edge.full
            ),
            total_minutes=sum(leg.est_minutes for leg in legs),
            amenities=[],
            warnings=warnings,
            access_segments=access_segments,
            graph_source_date="",
        ),
        traversal=traversal,
        segments=segments,
        day_ranges=tuple(day_ranges),
    )


def _coordinate_at_fraction(edge: tuple[int, int], fraction: float, graph: nx.Graph) -> Coordinate:
    return project_handle(CanalPointHandle(edge=edge, fraction=fraction), graph).coordinate


def _point_name(edge: tuple[int, int], fraction: float, graph: nx.Graph) -> str:
    data = graph.edges[edge]
    if isinstance(data.get("name"), str) and data["name"].strip():
        return data["name"].strip()
    options = [
        (abs(fraction - endpoint_fraction), str(graph.nodes[uid]["name"]))
        for uid, endpoint_fraction in zip(edge, (0.0, 1.0), strict=True)
        if graph.nodes[uid].get("name")
    ]
    if options:
        return min(options)[1]
    coordinate = _coordinate_at_fraction(edge, fraction, graph)
    return f"{coordinate.lat:.6f},{coordinate.lon:.6f}"


def _edge_geometry(edge: TraversedEdge, graph: nx.Graph) -> list[tuple[float, float]]:
    if edge.full:
        coordinates = [
            (float(y), float(x))
            for x, y in canonical_edge_line_wgs84(graph, (edge.u, edge.v)).coords
        ]
    else:
        line = metric_edge_line(graph, (edge.u, edge.v))
        low, high = sorted((edge.start_fraction, edge.end_fraction))
        sliced = substring(line, low * line.length, high * line.length)
        projected = transform(sliced, cast(Any, _TO_WGS84.transform), interleaved=False)
        coordinates = [(float(y), float(x)) for x, y in projected.coords]
    if edge.start_fraction > edge.end_fraction:
        coordinates.reverse()
    if not edge.full:
        start = _coordinate_at_fraction((edge.u, edge.v), edge.start_fraction, graph)
        end = _coordinate_at_fraction((edge.u, edge.v), edge.end_fraction, graph)
        coordinates[0] = (start.lat, start.lon)
        coordinates[-1] = (end.lat, end.lon)
    return coordinates


def _joined_geometry(edges: Any, graph: nx.Graph) -> list[tuple[float, float]]:
    joined: list[tuple[float, float]] = []
    for edge in edges:
        points = _edge_geometry(edge, graph)
        if joined and _same_coordinate(joined[-1], points[0]):
            joined.extend(points[1:])
        else:
            joined.extend(points)
    return joined


def _same_coordinate(first: tuple[float, float], second: tuple[float, float]) -> bool:
    return round(first[0], 7) == round(second[0], 7) and round(first[1], 7) == round(second[1], 7)


def _to_geojson(points: list[tuple[float, float]]) -> GeoJSONLineString:
    """Convert internal (lat, lon) coordinates to GeoJSON (lon, lat)."""
    return GeoJSONLineString(coordinates=[(lon, lat) for lat, lon in points])


def _access_segments(traversal: ComputedTraversal, graph: nx.Graph) -> list[RouteAccessSegment]:
    records = {
        (caveat.osm_way_id, caveat.kind, caveat.tag, caveat.value)
        for edge in traversal.edges
        for caveat in _edge_data(edge, graph).get("access_caveats", ())
    }
    return [
        RouteAccessSegment(osm_way_id=way_id, kind=kind, tag=tag, value=value)
        for way_id, kind, tag, value in sorted(records)
    ]


def _access_warnings(segments: list[RouteAccessSegment]) -> list[str]:
    counts = Counter((segment.kind, segment.tag, segment.value) for segment in segments)
    warnings = []
    for (kind, tag, value), count in sorted(counts.items()):
        if kind == "discouraged":
            warnings.append(
                f"Route uses {count} segment(s) tagged {tag}=discouraged; verify local access."
            )
        else:
            warnings.append(
                f"Route uses {count} segment(s) with unrecognized {tag}={json.dumps(value)}; "
                "verify local access."
            )
    return warnings


def _tunnel_warnings(
    traversal: ComputedTraversal,
    graph: nx.Graph,
    access_segments: list[RouteAccessSegment],
) -> list[str]:
    surfaced_access = {
        (segment.osm_way_id, segment.tag, segment.value) for segment in access_segments
    }
    restrictions = {
        item
        for edge in traversal.edges
        for item in _edge_data(edge, graph).get("tunnel_restrictions", ())
        if item not in surfaced_access
    }
    return [
        f"tunnel way {way_id}: unmodeled restriction {key}={json.dumps(value)}"
        for way_id, key, value in sorted(restrictions)
    ]


def _lock_points(edge: TraversedEdge, graph: nx.Graph) -> tuple[tuple[Coordinate, bool], ...]:
    data = _edge_data(edge, graph)
    geometry = data.get("geometry", ())
    points: list[tuple[Coordinate, bool]] = []
    for source_point in data.get("lock_points", ()):
        try:
            source_lat, source_lon = source_point
        except (TypeError, ValueError):
            continue
        projection = project_point_to_edge(geometry, source_lat, source_lon)
        if projection is not None and projection[1] <= LOCK_SOURCE_TOLERANCE_M:
            lat, lon = projection[0]
            points.append((Coordinate(lat=lat, lon=lon), False))
    if points or not data.get("locks", 0):
        return tuple(points)
    return ((_approximate_lock_coordinate(edge, graph), True),)


def _approximate_lock_coordinate(edge: TraversedEdge, graph: nx.Graph) -> Coordinate:
    geometry = _edge_data(edge, graph).get("geometry", ())
    if len(geometry) < 2:
        return _coordinate_at_fraction((edge.u, edge.v), 0.5, graph)
    lengths = [_haversine_m(start, end) for start, end in zip(geometry, geometry[1:], strict=False)]
    midpoint = sum(lengths) / 2
    distance = 0.0
    for start, end, length in zip(geometry, geometry[1:], lengths, strict=True):
        if distance + length >= midpoint:
            fraction = (midpoint - distance) / length if length else 0.0
            return Coordinate(
                lat=start[0] + fraction * (end[0] - start[0]),
                lon=start[1] + fraction * (end[1] - start[1]),
            )
        distance += length
    lat, lon = geometry[-1]
    return Coordinate(lat=lat, lon=lon)


def _coordinate_fraction(edge: tuple[int, int], coordinate: Coordinate, graph: nx.Graph) -> float:
    line = metric_edge_line(graph, edge)
    point = Point(*_TO_BNG.transform(coordinate.lon, coordinate.lat))
    return float(line.project(point) / line.length) if line.length else 0.5


def _route_locks(computed: _ComputedRoute, graph: nx.Graph) -> list[RouteLock]:
    day_by_segment = {
        segment_index: day
        for day, (start, end) in enumerate(computed.day_ranges, start=1)
        for segment_index in range(start, end)
    }
    route_locks: list[RouteLock] = []
    for traversal_index, edge in enumerate(computed.traversal.edges):
        if not edge.full:
            continue
        matching_segments = [
            (index, segment)
            for index, segment in enumerate(computed.segments)
            if segment.traversal_index == traversal_index
        ]
        for coordinate, approximate in _lock_points(edge, graph):
            fraction = _coordinate_fraction((edge.u, edge.v), coordinate, graph)
            selected = next(
                (
                    (index, segment)
                    for index, segment in matching_segments
                    if min(segment.edge.start_fraction, segment.edge.end_fraction) - 1e-9
                    <= fraction
                    <= max(segment.edge.start_fraction, segment.edge.end_fraction) + 1e-9
                ),
                matching_segments[-1] if matching_segments else None,
            )
            if selected is None:
                continue
            segment_index, _ = selected
            day = day_by_segment.get(segment_index)
            if day is None:
                continue
            route_locks.append(
                RouteLock(
                    coordinate=coordinate,
                    name=_point_name((edge.u, edge.v), fraction, graph),
                    day=day,
                    approximate=approximate,
                )
            )
    return route_locks


def _day_path_ranges(
    legs: list[RouteLeg], hours_per_day: float, max_days: int | None
) -> list[tuple[int, int]]:
    budget = hours_per_day * 60.0
    ranges: list[tuple[int, int]] = []
    current_start: int | None = None
    current_min = 0
    for edge_index, leg in enumerate(legs):
        if current_start is not None and current_min + leg.est_minutes > budget:
            ranges.append((current_start, edge_index))
            current_start = None
            current_min = 0
        if max_days is not None and len(ranges) >= max_days and current_start is None and ranges:
            start, _ = ranges[-1]
            ranges[-1] = (start, edge_index + 1)
            continue
        if current_start is None:
            current_start = edge_index
        current_min += leg.est_minutes
    if current_start is not None:
        ranges.append((current_start, len(legs)))
    return ranges


def _chunk_days(legs: list[RouteLeg], hours_per_day: float, max_days: int | None) -> list[DayPlan]:
    return [
        DayPlan(
            day=day_index,
            legs=legs[start:end],
            end_near=legs[end - 1].to_place,
            cruising_minutes=sum(leg.est_minutes for leg in legs[start:end]),
        )
        for day_index, (start, end) in enumerate(
            _day_path_ranges(legs, hours_per_day, max_days), start=1
        )
    ]
