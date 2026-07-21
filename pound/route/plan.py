"""Request-time entry point — pure plan_route over ResolvedConstraints (design §5, Scope D).

Routing runs Dijkstra by time-cost over the loaded graph (passed explicitly);
leg names come from the `name` node attribute PR1 attached (falling back to a
coordinate string). Zero network, zero LLM, hermetic by construction. Rings
(end_uid not applicable / CanalConstraints.end is None) raise
NotImplementedError. The Scope C `_graph`/`_features` test kwargs are retired;
tests inject an in-memory graph directly.

`plan_route_from_constraints` is the CanalConstraints -> resolve -> plan_route
bridge the CLI and Agent Core use.
"""

from dataclasses import dataclass

import networkx as nx
from networkx.exception import NetworkXNoPath

from pound.graph.build import _node_key
from pound.route.cost import is_eligible, time_min
from pound.route.resolve import resolve_place
from pound.schemas import (
    CanalConstraints,
    CanalRouteResponse,
    Coordinate,
    DayPlan,
    GeoJSONLineString,
    ResolvedConstraints,
    RouteDayGeometry,
    RouteLeg,
    RouteLock,
    RouteResult,
)


@dataclass(frozen=True)
class _ComputedRoute:
    route: RouteResult
    path: tuple[int, ...]
    day_ranges: tuple[tuple[int, int], ...]


class RouteUnavailableError(ValueError):
    """Raised when valid route inputs cannot produce an eligible graph path."""


def plan_route(constraints: ResolvedConstraints, *, graph: nx.Graph) -> RouteResult:
    """Plan a point-to-point canal route over `graph`. Pure."""
    return _compute_route(constraints, graph=graph).route


def plan_canal_route(constraints: ResolvedConstraints, *, graph: nx.Graph) -> CanalRouteResponse:
    """Plan a route and retain its traversed geometry for web clients."""
    computed = _compute_route(constraints, graph=graph)
    day_geometries = []
    for day, (start, end) in enumerate(computed.day_ranges, start=1):
        points = _path_geometry(computed.path[start : end + 1], graph)
        day_geometries.append(
            RouteDayGeometry(
                day=day,
                geometry=_to_geojson(points),
                start=Coordinate(lat=points[0][0], lon=points[0][1]),
                end=Coordinate(lat=points[-1][0], lon=points[-1][1]),
            )
        )
    return CanalRouteResponse(
        route=computed.route,
        geometry=_to_geojson(_path_geometry(computed.path, graph)),
        day_geometries=day_geometries,
        locks=_route_locks(computed.path, graph, computed.day_ranges),
    )


def _compute_route(constraints: ResolvedConstraints, *, graph: nx.Graph) -> _ComputedRoute:
    """Compute the public route result together with its selected graph path."""
    # ResolvedConstraints carries the graph's own node handles — no coord->uid
    # mapping, no name lookup, no graph mutation. Pure on the resolved uids.
    start, end = constraints.start_uid, constraints.end_uid

    def _name_attr(uid):
        n = graph.nodes[uid]
        return n.get("name") or f"{n['lat']},{n['lon']}"

    start_name = _name_attr(start)

    unknown_edges: list[str] = []

    def weight(u, v, d):
        eligible, unknown = is_eligible(
            constraints.boat_length_m,
            constraints.boat_beam_m,
            constraints.boat_draft_m,
            constraints.boat_height_m,
            d["dimensions"],
        )
        if not eligible:
            return None
        if unknown:
            unknown_edges.append(str(d["osm_way_id"]))
        return time_min(d["length_m"], d.get("locks", 0))

    try:
        path = nx.shortest_path(graph, start, end, weight=weight)
    except NetworkXNoPath:
        if nx.has_path(graph, start, end):
            raise RouteUnavailableError(
                f"no path between '{start_name}' and '{_name_attr(end)}' "
                f"meets the boat's dimensions"
            ) from None
        raise RouteUnavailableError(
            f"no path between '{start_name}' and '{_name_attr(end)}' "
            f"(graph is not connected between these nodes)"
        ) from None

    legs: list[RouteLeg] = []
    for u, v in zip(path, path[1:], strict=False):
        d = graph.edges[u, v]
        km = d["length_m"] / 1000.0
        locks = d.get("locks", 0)
        legs.append(
            RouteLeg(
                from_place=_name_attr(u),
                to_place=_name_attr(v),
                distance_km=round(km, 4),
                locks=locks,
                est_minutes=round(time_min(d["length_m"], locks)),
                flagged_unknown_dims=str(d["osm_way_id"]) in set(unknown_edges),
            )
        )

    total_km = round(sum(leg.distance_km for leg in legs), 4)
    total_locks = sum(leg.locks for leg in legs)
    total_minutes = sum(leg.est_minutes for leg in legs)

    warnings: list[str] = []
    if unknown_edges:
        warnings.append(f"draft/beam unknown on {len(set(unknown_edges))} segment(s)")

    day_ranges = _day_path_ranges(legs, constraints.hours_per_day, constraints.days)
    days = _chunk_days(legs, constraints.hours_per_day, constraints.days)
    budget = constraints.hours_per_day * 60
    if any(day.cruising_minutes > budget for day in days):
        warnings.append("one or more days exceed hours_per_day budget")

    return _ComputedRoute(
        route=RouteResult(
            start=start_name,
            end=_name_attr(end),
            is_ring=False,
            legs=legs,
            days=days,
            total_km=total_km,
            total_locks=total_locks,
            total_minutes=total_minutes,
            amenities=[],
            warnings=warnings,
            graph_source_date=graph.graph.get("fetched_at", ""),
        ),
        path=tuple(path),
        day_ranges=tuple(day_ranges),
    )


def _path_geometry(path: tuple[int, ...], graph: nx.Graph) -> list[tuple[float, float]]:
    """Return edge geometry in path traversal order as internal (lat, lon) pairs."""
    if len(path) == 1:
        node = graph.nodes[path[0]]
        point = (node["lat"], node["lon"])
        return [point, point]

    joined: list[tuple[float, float]] = []
    for u, v in zip(path, path[1:], strict=False):
        segment = [tuple(point) for point in graph.edges[u, v]["geometry"]]
        u_key = _node_key(graph.nodes[u]["lat"], graph.nodes[u]["lon"])
        if _node_key(*segment[0]) == u_key:
            pass
        elif _node_key(*segment[-1]) == u_key:
            segment.reverse()
        else:
            raise ValueError(f"edge geometry for {u!r}-{v!r} does not meet node {u!r}")
        if joined and joined[-1] == segment[0]:
            joined.extend(segment[1:])
        else:
            joined.extend(segment)
    return joined


def _to_geojson(points: list[tuple[float, float]]) -> GeoJSONLineString:
    """Convert internal (lat, lon) coordinates to GeoJSON (lon, lat)."""
    return GeoJSONLineString(coordinates=[(lon, lat) for lat, lon in points])


def _route_locks(
    path: tuple[int, ...], graph: nx.Graph, day_ranges: tuple[tuple[int, int], ...]
) -> list[RouteLock]:
    """Extract lock points from traversed edges and assign them to route days."""
    route_locks: list[RouteLock] = []
    for edge_index, (u, v) in enumerate(zip(path, path[1:], strict=False)):
        edge = graph.edges[u, v]
        lock_points = edge.get("lock_points", [])
        approximate = not lock_points
        if not lock_points and edge.get("locks", 0):
            geometry = edge.get("geometry", [])
            if geometry:
                lock_points = [
                    (
                        (geometry[0][0] + geometry[-1][0]) / 2,
                        (geometry[0][1] + geometry[-1][1]) / 2,
                    )
                ]
            else:
                lock_points = [
                    (
                        (graph.nodes[u]["lat"] + graph.nodes[v]["lat"]) / 2,
                        (graph.nodes[u]["lon"] + graph.nodes[v]["lon"]) / 2,
                    )
                ]
        if not lock_points:
            continue
        day = next(
            (
                day_index
                for day_index, (start, end) in enumerate(day_ranges, start=1)
                if start <= edge_index < end
            ),
            None,
        )
        if day is None:
            continue
        edge_name = edge.get("name")
        for lat, lon in lock_points:
            name = edge_name
            if name is None:
                named_nodes = [
                    (
                        (lat - graph.nodes[uid]["lat"]) ** 2 + (lon - graph.nodes[uid]["lon"]) ** 2,
                        graph.nodes[uid].get("name"),
                    )
                    for uid in (u, v)
                    if graph.nodes[uid].get("name")
                ]
                if named_nodes:
                    name = min(named_nodes)[1]
            route_locks.append(
                RouteLock(
                    coordinate=Coordinate(lat=lat, lon=lon),
                    name=name,
                    day=day,
                    approximate=approximate,
                )
            )
    return route_locks


def plan_route_from_constraints(
    c: CanalConstraints,
    *,
    graph: nx.Graph,
    snap_tolerance_m: float = 50.0,
) -> RouteResult:
    """CanalConstraints -> resolve -> plan_route. The CLI/Agent Core path."""
    if c.end is None:
        raise NotImplementedError("rings not yet supported (design §5.3)")
    resolved = ResolvedConstraints(
        start_uid=resolve_place(c.start, graph, snap_tolerance_m=snap_tolerance_m),
        end_uid=resolve_place(c.end, graph, snap_tolerance_m=snap_tolerance_m),
        days=c.days,
        hours_per_day=c.hours_per_day,
        boat_length_m=c.boat_length_m,
        boat_beam_m=c.boat_beam_m,
        boat_draft_m=c.boat_draft_m,
        boat_height_m=c.boat_height_m,
    )
    return plan_route(resolved, graph=graph)


def _day_path_ranges(legs, hours_per_day, max_days) -> list[tuple[int, int]]:
    """Return half-open path-edge ranges matching ``_chunk_days`` grouping."""
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


def _chunk_days(legs, hours_per_day, max_days) -> list[DayPlan]:
    """Greedy cumulative-minute packing. max_days=None => no cap (infer)."""
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
