"""Bounded, complete enumeration of simple out-and-back branch journeys.

The shared graph is immutable during requests. A search limit is an error, never
permission to return a partial set of routes or a misleading default.
"""

import hashlib
import json
import math
from collections.abc import Iterator
from dataclasses import dataclass

import networkx as nx

from pound.graph.pois import _routing_eligible
from pound.route.cost import is_eligible, resolve_movable_bridge_delay
from pound.route.plan import _render_path, _route_response, _traversal_time_min
from pound.schemas import (
    BranchChoice,
    JourneyBudget,
    OutAndBackRoute,
    OutAndBackRouteRequest,
    ResolvedConstraints,
    Turnaround,
    TurnaroundCandidatesRequest,
    TurnaroundCandidatesResponse,
    TurnaroundRejection,
)

POLICY_VERSION = "out-and-back-branches-v1"
MAX_WORK = 100_000
MAX_ROUTES = 1_000
MAX_VERTICES = 200_000
BOAT_FIELDS = ("boat_length_m", "boat_beam_m", "boat_draft_m", "boat_height_m")


class RoundTripError(ValueError):
    """Actionable service error shared by HTTP and deterministic tool clients."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        fields: list[str] | None = None,
        rejections: list[TurnaroundRejection] | None = None,
        status: int = 422,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = fields or []
        self.rejections = rejections or []
        self.status = status


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _request_values(body: TurnaroundCandidatesRequest) -> dict:
    values = {field: getattr(body, field) for field in TurnaroundCandidatesRequest.model_fields}
    values["movable_bridge_delay_min"] = resolve_movable_bridge_delay(
        body.movable_bridge_delay_min,
    )
    return values


def _request_id(body: TurnaroundCandidatesRequest) -> str:
    return _digest([POLICY_VERSION, _request_values(body)])


def _check_inputs(body: TurnaroundCandidatesRequest, graph: nx.Graph) -> None:
    # HTTP also checks the app's artifact envelope. Honor a graph revision when supplied.
    revision = graph.graph.get("artifact_revision")
    if revision is not None and revision != body.artifact_revision:
        raise RoundTripError(
            "artifact_revision_mismatch",
            "The artifact changed; refresh choices.",
            fields=["artifact_revision"],
            status=409,
        )
    missing = [
        field
        for field in ("start_uid", "waypoint_uid")
        if getattr(body, field) is not None and getattr(body, field) not in graph
    ]
    if missing:
        raise RoundTripError(
            "invalid_node_handle", "Select valid canal endpoints again.", fields=missing, status=400
        )
    if "turnarounds" not in graph.graph:
        raise RoundTripError(
            "turnarounds_unavailable", "Rebuild the artifact with turnarounds.", status=503
        )


def _turning_rejection(turn: Turnaround, body: TurnaroundCandidatesRequest):
    limits = turn.turning_limits
    if limits.get("prohibited"):
        return TurnaroundRejection(
            turnaround_id=turn.turnaround_id,
            code="turning_prohibited",
            message="Turning is prohibited at this location.",
        )
    for field in BOAT_FIELDS:
        limit = limits.get(field)
        if limit is None:
            continue
        value = getattr(body, field)
        if value is None:
            return TurnaroundRejection(
                turnaround_id=turn.turnaround_id,
                code="turning_dimension_required",
                message=f"Supply {field}; the turning limit is {limit:g} m.",
                fields=[field],
            )
        if value > limit:
            return TurnaroundRejection(
                turnaround_id=turn.turnaround_id,
                code="turnaround_dimensions",
                message=f"{field} exceeds the {limit:g} m turning limit.",
                fields=[field],
            )
    return None


def _schedule(costs: list[float], hours: float) -> tuple[list[tuple[int, int]], float, bool]:
    """Uncapped greedy packing using conservative per-traversal estimates."""
    budget = hours * 60
    ranges = []
    start, current = 0, 0.0
    weights = [max(cost, round(cost)) for cost in costs]
    for index, minutes in enumerate(weights):
        if index > start and current + minutes > budget:
            ranges.append((start, index))
            start, current = index, 0.0
        current += minutes
    if weights:
        ranges.append((start, len(weights)))
    return ranges, math.fsum(weights), all(minutes <= budget for minutes in weights)


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
    turnaround: Turnaround
    day_ranges: list[tuple[int, int]]
    used_minutes: float
    distance: float
    raw_minutes: float


def discover_round_trips(
    body: TurnaroundCandidatesRequest,
    *,
    graph: nx.Graph,
    max_work: int = MAX_WORK,
    max_routes: int = MAX_ROUTES,
    max_vertices: int = MAX_VERTICES,
) -> TurnaroundCandidatesResponse:
    """Return every maximal feasible turnaround path, including rejoined branches."""
    _check_inputs(body, graph)
    if min(max_work, max_routes, max_vertices) <= 0:
        raise ValueError("Search limits must be positive")
    request_id = _request_id(body)
    turns = [Turnaround.model_validate(t) for t in graph.graph["turnarounds"]]
    turns = sorted(
        (t for t in turns if t.node_uid != body.start_uid),
        key=lambda t: (t.kind != "winding_hole", t.turnaround_id),
    )
    if not turns:
        raise RoundTripError("no_turnaround_candidates", "No turnaround destinations in this area.")
    # Validated build artifacts have one merged record per node. Stable choice also helps fixtures.
    by_node: dict[int, Turnaround] = {}
    rejections: dict[tuple, TurnaroundRejection] = {}

    def reject(item: TurnaroundRejection) -> None:
        rejections[(item.turnaround_id or "", item.code, item.message)] = item

    for turn in turns:
        problem = _turning_rejection(turn, body)
        if problem:
            reject(problem)
        else:
            by_node.setdefault(turn.node_uid, turn)

    work = 0

    def charge(amount: int = 1) -> None:
        nonlocal work
        work += amount
        if work > max_work:
            raise RoundTripError(
                "candidate_search_limit", "Branch search exceeds its work limit; reduce the budget."
            )

    available = body.days * body.hours_per_day * 60
    bridge_delay = resolve_movable_bridge_delay(body.movable_bridge_delay_min)
    dimensions = [getattr(body, f) for f in BOAT_FIELDS]
    edge_cache: dict[tuple[int, int], tuple[float, float, float] | None] = {}

    def edge_cost(u: int, v: int):
        key = (u, v)
        if key not in edge_cache:
            data = graph.edges[u, v]
            eligible = _routing_eligible(data) and is_eligible(*dimensions, data["dimensions"])[0]
            edge_cache[key] = (
                (
                    _traversal_time_min(graph, u, v, data, bridge_delay),
                    _traversal_time_min(graph, v, u, data, bridge_delay),
                    data["length_m"],
                )
                if eligible
                else None
            )
        return edge_cache[key]

    path = [body.start_uid]
    visited = {body.start_uid}
    forward_costs: list[float] = []
    reverse_costs: list[float] = []
    choices: dict[tuple[int, ...], _Choice] = {}
    reached: set[int] = set()
    stack = [
        _Frame(
            iter(sorted(graph[body.start_uid])),
            0,
            0,
            0,
            body.waypoint_uid in (None, body.start_uid),
        )
    ]
    while stack:
        frame = stack[-1]
        uid = next(frame.neighbors, None)
        if uid is None:
            stack.pop()
            visited.remove(path.pop())
            if forward_costs:
                forward_costs.pop()
                reverse_costs.pop()
            continue
        charge()
        if uid in visited:
            continue
        costs = edge_cost(path[-1], uid)
        if costs is None:
            continue
        outward, backward, distance = costs
        forward, reverse = frame.forward + outward, frame.reverse + backward
        if forward + reverse > available:
            reject(
                TurnaroundRejection(
                    turnaround_id=by_node[uid].turnaround_id if uid in by_node else None,
                    code="budget_exceeded",
                    fields=["days", "hours_per_day"],
                    message=f"Continuing here requires at least {forward + reverse:g} minutes.",
                )
            )
            continue
        path.append(uid)
        visited.add(uid)
        forward_costs.append(outward)
        reverse_costs.append(backward)
        seen = frame.waypoint_seen or uid == body.waypoint_uid
        total_distance = frame.distance + distance
        turn = by_node.get(uid)
        if turn is not None:
            reached.add(uid)
        if turn is not None and seen:
            charge(len(path))
            ranges, used, legs_fit = _schedule(
                forward_costs + reverse_costs[::-1],
                body.hours_per_day,
            )
            if legs_fit and len(ranges) <= body.days:
                signature = tuple(path)
                # Remove only ancestor routes, never another history reaching the same vertex.
                for prefix in list(choices):
                    charge()
                    if len(prefix) < len(signature) and signature[: len(prefix)] == prefix:
                        del choices[prefix]
                choices[signature] = _Choice(
                    signature, turn, ranges, used, total_distance, forward + reverse
                )
                if len(choices) > max_routes:
                    raise RoundTripError(
                        "candidate_search_limit",
                        "Complete route collection exceeds its result limit.",
                    )
            else:
                reject(
                    TurnaroundRejection(
                        turnaround_id=turn.turnaround_id,
                        code="budget_exceeded",
                        fields=["days", "hours_per_day"],
                        message=(
                            f"Journey needs {len(ranges)} days and {used:g} minutes; "
                            "every traversal must fit a day."
                        ),
                    )
                )
        stack.append(_Frame(iter(sorted(graph[uid])), forward, reverse, total_distance, seen))

    for uid, turn in by_node.items():
        if uid not in reached:
            reject(
                TurnaroundRejection(
                    turnaround_id=turn.turnaround_id,
                    code="no_eligible_path",
                    message="No public-network path within the boat constraints and total budget.",
                )
            )
    ordered_rejections = [rejections[key] for key in sorted(rejections)]
    if not choices:
        if body.waypoint_uid is not None:
            ordered_rejections.append(
                TurnaroundRejection(
                    code="waypoint_unreachable_within_constraints",
                    fields=["waypoint_uid"],
                    message="No feasible simple outbound journey visits the required waypoint.",
                )
            )
        raise RoundTripError(
            "no_feasible_turnaround",
            "No complete turnaround journey fits.",
            rejections=ordered_rejections,
        )
    ordered = sorted(
        choices.values(),
        key=lambda c: (
            -c.distance,
            c.raw_minutes,
            c.turnaround.turnaround_id,
            c.path,
        ),
    )
    constraints = ResolvedConstraints(
        start_uid=body.start_uid,
        end_uid=body.start_uid,
        **{
            key: value
            for key, value in _request_values(body).items()
            if key not in {"artifact_revision", "start_uid", "waypoint_uid"}
        },
    )
    routes = []
    vertices = 0
    for choice in ordered:
        closed = list(choice.path) + list(choice.path[-2::-1])
        # Bound geometry before allocating full per-route and per-day responses.
        count = sum(
            len(graph.edges[u, v]["geometry"]) for u, v in zip(closed, closed[1:], strict=False)
        )
        vertices += 2 * count  # both complete and day geometry
        if vertices > max_vertices:
            raise RoundTripError(
                "candidate_search_limit", "Complete journey geometry exceeds its response limit."
            )
        charge(len(closed))
        computed = _render_path(closed, constraints, graph=graph, day_ranges=choice.day_ranges)
        route_id = _digest([request_id, choice.turnaround.turnaround_id, choice.path])
        routes.append(
            OutAndBackRoute(
                artifact_revision=body.artifact_revision,
                request_id=request_id,
                route_id=route_id,
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
                    for u, v in zip(choice.path, choice.path[1:], strict=False)
                    if graph.degree(u) >= 3 or (u == body.start_uid and graph.degree(u) > 1)
                ],
                turnaround=choice.turnaround,
                outbound_distance_km=choice.distance / 1000,
                budget=JourneyBudget(
                    available_minutes=available,
                    used_minutes=choice.used_minutes,
                    remaining_minutes=max(0, available - choice.used_minutes),
                    days_used=len(choice.day_ranges),
                ),
                journey=_route_response(computed, graph),
            )
        )
    return TurnaroundCandidatesResponse(
        artifact_revision=body.artifact_revision,
        request_id=request_id,
        default_route_id=routes[0].route_id,
        routes=routes,
        rejections=ordered_rejections,
    )


def plan_out_and_back(
    body: OutAndBackRouteRequest,
    *,
    graph: nx.Graph,
    max_work: int = MAX_WORK,
    max_routes: int = MAX_ROUTES,
    max_vertices: int = MAX_VERTICES,
) -> OutAndBackRoute:
    """Return the deterministic default or the exact current branch-route override."""
    _check_inputs(body, graph)
    if body.request_id is not None and body.request_id != _request_id(body):
        raise RoundTripError(
            "stale_route_selection",
            "Constraints changed; refresh route choices.",
            fields=["request_id"],
            status=409,
        )
    result = discover_round_trips(
        body, graph=graph, max_work=max_work, max_routes=max_routes, max_vertices=max_vertices
    )
    if body.route_id is None:
        return result.routes[0]
    for route in result.routes:
        if route.route_id == body.route_id:
            return route.model_copy(update={"selection_basis": "user_selected"})
    raise RoundTripError(
        "stale_route_selection",
        "The selected route changed; refresh choices.",
        fields=["route_id"],
        status=409,
    )
