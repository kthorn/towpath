"""Adapt enumerated closed paths to the shared compact traversal renderer."""

import networkx as nx

from pound.route.cost import traversal_time_min
from pound.route.plan import (
    ComputedTraversal,
    _full_edge,
    _render_traversal,
    _report_segments,
)
from pound.route.plan import (
    _route_response as _shared_response,
)
from pound.schemas import CanalConstraints, CanalPointHandle, ProjectedRouteConstraints


def _traversal_time_min(graph, u, v, edge, bridge_delay_min: float) -> float:
    return traversal_time_min(
        edge,
        graph.nodes[v].get("movable_bridge_ids", ()),
        movable_bridge_delay_min=bridge_delay_min,
    )


def _constraints(path, constraints):
    low, high = sorted(path[:2])
    start = CanalPointHandle(edge=(low, high), fraction=float(path[0] == high))
    return ProjectedRouteConstraints(**constraints.model_dump(), start=start, end=start)


def _segment_costs(u, v, constraints, graph):
    traversal = ComputedTraversal((_full_edge(u, v),), 0)
    return [
        segment.cost_min
        for segment in _report_segments(traversal, _constraints([u, v], constraints), graph)
    ]


def _render_path(
    path: list[int],
    constraints: CanalConstraints,
    *,
    graph: nx.Graph,
    day_ranges: list[tuple[int, int]] | None = None,
):
    traversal = ComputedTraversal(
        tuple(_full_edge(u, v) for u, v in zip(path, path[1:], strict=False)), 0
    )
    computed = _render_traversal(
        traversal, _constraints(path, constraints), graph, day_ranges=day_ranges
    )

    # Retain explicit junction/place names on exact vertex endpoints.
    def name(edge, fraction, fallback):
        uid = edge.u if fraction == 0 else edge.v if fraction == 1 else None
        return graph.nodes[uid].get("name") or fallback if uid is not None else fallback

    for leg, segment in zip(computed.route.legs, computed.segments, strict=True):
        leg.from_place = name(segment.edge, segment.edge.start_fraction, leg.from_place)
        leg.to_place = name(segment.edge, segment.edge.end_fraction, leg.to_place)
    for day in computed.route.days:
        day.end_near = day.legs[-1].to_place
    computed.route.start = graph.nodes[path[0]].get("name") or computed.route.start
    computed.route.end = computed.route.start
    return computed


def _route_response(computed, graph: nx.Graph):
    return _shared_response(computed, graph, source_date=graph.graph.get("fetched_at", ""))
