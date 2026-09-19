"""Bounded discovery of one circuit, optionally reached by a retraced connection.

Every search path is simple until one edge closes a circuit onto an ancestor.
The prefix before that ancestor is the connection and is reversed to get home.
Both circuit directions are retained: event costs and day packing can differ.
"""

import heapq
import math
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass

import networkx as nx

from pound.route._round_trip_render import _render_path, _route_response, _segment_costs
from pound.route.cost import is_eligible, resolve_movable_bridge_delay
from pound.route.round_trip import (
    BOAT_FIELDS,
    MAX_ROUTES,
    MAX_VERTICES,
    MAX_WORK,
    RoundTripError,
    _check_inputs,
    _digest,
    _fits_budget,
    _projected_graph,
    _request_values,
    _routing_eligible,
    _schedule,
    _traversal_time_min,
)
from pound.schemas import (
    BranchChoice,
    CanalConstraints,
    JourneyBudget,
    LoopCandidatesRequest,
    LoopCandidatesResponse,
    LoopRoute,
    LoopRouteRequest,
)

POLICY_VERSION = "single-circuit-with-connection-v1"


@dataclass
class _Frame:
    neighbors: Iterator[int]
    forward: float
    reverse: float
    distance: float
    waypoint_seen: bool


@dataclass
class _Choice:
    path: tuple[int, ...]
    loop_distance: float
    connection_distance: float
    raw_minutes: float
    used_minutes: float
    day_ranges: list[tuple[int, int]]


def _request_id(body: LoopCandidatesRequest) -> str:
    return _digest([POLICY_VERSION, _request_values(body)])


def discover_loops(
    body: LoopCandidatesRequest,
    *,
    graph: nx.Graph,
    max_work: int = MAX_WORK,
    max_routes: int = MAX_ROUTES,
    max_vertices: int = MAX_VERTICES,
) -> LoopCandidatesResponse:
    """Return all feasible single-circuit journeys or an explicit search-limit error."""
    _check_inputs(body, graph, require_turnarounds=False)
    if min(max_work, max_routes, max_vertices) <= 0:
        raise ValueError("Search limits must be positive")
    request_id = _request_id(body)
    body, graph = _projected_graph(body, graph)
    available = body.days * body.hours_per_day * 60
    bridge_delay = resolve_movable_bridge_delay(body.movable_bridge_delay_min)
    dimensions = [getattr(body, field) for field in BOAT_FIELDS]
    constraints = CanalConstraints(
        **{
            key: value
            for key, value in _request_values(body).items()
            if key not in {"artifact_revision", "start_uid", "waypoint_uid", "start", "waypoint"}
        }
    )
    work = 0

    def charge(amount: int = 1) -> None:
        nonlocal work
        work += amount
        if work > max_work:
            raise RoundTripError(
                "candidate_search_limit", "Loop search exceeds its work limit; reduce the budget."
            )

    costs: dict[tuple[int, int], float | None] = {}

    def edge_cost(u: int, v: int) -> float | None:
        if (u, v) not in costs:
            data = graph.edges[u, v]
            eligible = _routing_eligible(data) and is_eligible(*dimensions, data["dimensions"])[0]
            costs[u, v] = _traversal_time_min(graph, u, v, data, bridge_delay) if eligible else None
        return costs[u, v]

    # Reverse Dijkstra gives an optimistic cost home. Do not use twice the
    # outbound cost: a circuit may return by a substantially shorter route.
    home = {body.start_uid: 0.0}
    queue = [(0.0, body.start_uid)]
    while queue:
        minutes, u = heapq.heappop(queue)
        charge()
        if minutes != home[u]:
            continue
        for v in sorted(graph[u]):
            charge()
            cost = edge_cost(v, u)
            if cost is None:
                continue
            candidate = minutes + cost
            if _fits_budget(candidate, available) and candidate < home.get(v, math.inf):
                home[v] = candidate
                heapq.heappush(queue, (candidate, v))

    # A journey cannot enter a dead-end branch and return without retracing
    # beyond its connection. Peel such branches, preserving the base so its
    # unique connection to the remaining circuits is retained.
    neighbors: dict[int, set[int]] = {}
    for u in sorted(home):
        neighbors[u] = set()
        for v in graph[u]:
            charge()
            if v in home and edge_cost(u, v) is not None:
                neighbors[u].add(v)
    leaves = deque(u for u in neighbors if u != body.start_uid and len(neighbors[u]) <= 1)
    while leaves:
        u = leaves.popleft()
        charge()
        for v in neighbors.pop(u, ()):
            neighbors[v].discard(u)
            if v != body.start_uid and len(neighbors[v]) == 1:
                leaves.append(v)
    adjacency = {u: tuple(sorted(values)) for u, values in neighbors.items()}

    segment_cache: dict[tuple[int, int], list[float]] = {}

    def segment_costs(u: int, v: int) -> list[float]:
        if (u, v) not in segment_cache:
            segment_cache[u, v] = _segment_costs(u, v, constraints, graph)
            charge(len(segment_cache[u, v]))
        return segment_cache[u, v]

    path = [body.start_uid]
    positions = {body.start_uid: 0}
    stack = [
        _Frame(
            iter(adjacency[body.start_uid]),
            0,
            0,
            0,
            body.waypoint_uid in (None, body.start_uid),
        )
    ]
    choices: dict[tuple[int, ...], _Choice] = {}
    while stack:
        frame = stack[-1]
        v = next(frame.neighbors, None)
        if v is None:
            stack.pop()
            del positions[path.pop()]
            continue
        charge()
        u = path[-1]
        cost = edge_cost(u, v)
        if cost is None:
            continue
        forward = frame.forward + cost
        if not _fits_budget(forward + home.get(v, math.inf), available):
            continue
        if v in positions:
            index = positions[v]
            if len(path) - index < 3 or not frame.waypoint_seen:
                continue
            ancestor = stack[index]
            raw_minutes = forward + ancestor.reverse
            loop_distance = frame.distance + graph.edges[u, v]["length_m"] - ancestor.distance
            if not _fits_budget(raw_minutes, available) or loop_distance <= 0:
                continue
            closed = (*path, v, *reversed(path[:index]))
            charge(len(closed))
            ranges, used, fits = _schedule(
                [c for a, b in zip(closed, closed[1:], strict=False) for c in segment_costs(a, b)],
                body.hours_per_day,
            )
            if not fits or len(ranges) > body.days or not _fits_budget(used, available):
                continue
            choices[closed] = _Choice(
                closed, loop_distance, ancestor.distance, raw_minutes, min(used, available), ranges
            )
            if len(choices) > max_routes:
                raise RoundTripError(
                    "candidate_search_limit", "Complete loop collection exceeds its result limit."
                )
            continue
        reverse_cost = edge_cost(v, u)
        assert reverse_cost is not None  # Runtime artifacts are undirected eligible graphs.
        positions[v] = len(path)
        path.append(v)
        stack.append(
            _Frame(
                iter(adjacency[v]),
                forward,
                frame.reverse + reverse_cost,
                frame.distance + graph.edges[u, v]["length_m"],
                frame.waypoint_seen or v == body.waypoint_uid,
            )
        )

    if not choices:
        raise RoundTripError(
            "no_feasible_loop",
            "No circuit returning to this base fits the cruising budget, boat constraints"
            " and required visit. Increase the budget or choose another base or visit.",
            fields=["days", "hours_per_day"]
            + (["waypoint"] if body.waypoint_uid is not None else []),
        )
    ordered = sorted(
        choices.values(),
        key=lambda c: (-(c.loop_distance + 2 * c.connection_distance), c.raw_minutes, c.path),
    )
    routes = []
    vertices = 0
    for choice in ordered:
        edges = list(zip(choice.path, choice.path[1:], strict=False))
        charge(len(edges))
        vertices += 2 * sum(
            len(graph.edges[u, v]["geometry"]) + len(segment_costs(u, v)) for u, v in edges
        )
        if vertices > max_vertices:
            raise RoundTripError(
                "candidate_search_limit", "Complete loop geometry exceeds its response limit."
            )
        computed = _render_path(
            list(choice.path), constraints, graph=graph, day_ranges=choice.day_ranges
        )
        computed.route.is_ring = True
        routes.append(
            LoopRoute(
                artifact_revision=body.artifact_revision,
                request_id=request_id,
                route_id=_digest([request_id, choice.path]),
                branch_choices=[
                    BranchChoice(
                        junction_uid=u,
                        next_uid=v,
                        junction_name=graph.nodes[u].get("name")
                        or (
                            f"Junction at {graph.nodes[u]['lat']:.5f}, {graph.nodes[u]['lon']:.5f}"
                        ),
                        continuation_name=graph.edges[u, v].get("name")
                        or (
                            graph.nodes[v].get("name")
                            or f"Toward {graph.nodes[v]['lat']:.5f}, {graph.nodes[v]['lon']:.5f}"
                        ),
                    )
                    for u, v in edges
                    if graph.degree(u) >= 3 or (u == body.start_uid and graph.degree(u) > 1)
                ],
                loop_distance_km=choice.loop_distance / 1000,
                connecting_distance_km=choice.connection_distance / 1000,
                budget=JourneyBudget(
                    available_minutes=available,
                    used_minutes=choice.used_minutes,
                    remaining_minutes=max(0, available - choice.used_minutes),
                    days_used=len(choice.day_ranges),
                ),
                journey=_route_response(computed, graph),
            )
        )
    return LoopCandidatesResponse(
        artifact_revision=body.artifact_revision,
        request_id=request_id,
        default_route_id=routes[0].route_id,
        routes=routes,
    )


def plan_loop(
    body: LoopRouteRequest,
    *,
    graph: nx.Graph,
    max_work: int = MAX_WORK,
    max_routes: int = MAX_ROUTES,
    max_vertices: int = MAX_VERTICES,
) -> LoopRoute:
    """Return the default loop or revalidate the exact selected journey."""
    _check_inputs(body, graph, require_turnarounds=False)
    if body.request_id is not None and body.request_id != _request_id(body):
        raise RoundTripError(
            "stale_route_selection",
            "Constraints changed; refresh loop choices.",
            fields=["request_id"],
            status=409,
        )
    result = discover_loops(
        body, graph=graph, max_work=max_work, max_routes=max_routes, max_vertices=max_vertices
    )
    if body.route_id is None:
        return result.routes[0]
    for route in result.routes:
        if route.route_id == body.route_id:
            return route.model_copy(update={"selection_basis": "user_selected"})
    raise RoundTripError(
        "stale_route_selection",
        "The selected loop changed; refresh choices.",
        fields=["route_id"],
        status=409,
    )
