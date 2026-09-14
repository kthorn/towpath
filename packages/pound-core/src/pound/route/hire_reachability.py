"""Bounded directional reachability from a projected canal waypoint."""

import math
from dataclasses import dataclass
from heapq import heapify, heappop, heappush
from typing import Any

import networkx as nx

from pound.models import WayDimensions
from pound.route.cost import is_eligible, resolve_movable_bridge_delay, traversal_time_min
from pound.route.plan import _edge_record, _traversal_cost
from pound.route.round_trip import _routing_eligible
from pound.schemas import CanalPointHandle

MAX_WORK = 200_000


class HireReachabilityError(ValueError):
    """Raised when bounded directional reachability cannot finish safely."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class HireBaseReachability:
    """The two directional costs for one validated hire-base anchor."""

    anchor: Any
    one_way_minutes: float
    return_minutes: float

    @property
    def identity(self) -> str:
        return self.anchor.seed.identity


def _dimensions_allowed(
    data: dict[str, Any],
    boat_length_m: float | None,
    boat_beam_m: float | None,
    boat_draft_m: float | None,
    boat_height_m: float | None,
) -> bool:
    return _routing_eligible(data) and is_eligible(
        boat_length_m,
        boat_beam_m,
        boat_draft_m,
        boat_height_m,
        data.get("dimensions", WayDimensions()),
    )[0]


def _validate_handle(handle: CanalPointHandle, graph: nx.Graph) -> None:
    if not graph.has_edge(*handle.edge):
        raise ValueError(f"handle edge {handle.edge!r} is absent from graph")
    if (
        0 < handle.fraction < 1
        and graph.edges[handle.edge].get("candidate_eligible", True) is False
    ):
        raise ValueError("interior handle must use a candidate-eligible edge")


def _partial_cost(
    edge: tuple[int, int],
    start_fraction: float,
    end_fraction: float,
    *,
    graph: nx.Graph,
    bridge_delay_min: float,
    boat_length_m: float | None,
    boat_beam_m: float | None,
    boat_draft_m: float | None,
    boat_height_m: float | None,
) -> float | None:
    if start_fraction == end_fraction:
        return 0.0
    data = graph.edges[edge]
    if not _dimensions_allowed(
        data, boat_length_m, boat_beam_m, boat_draft_m, boat_height_m
    ):
        return None
    record = _edge_record(edge, start_fraction, end_fraction)
    return _traversal_cost(record, graph, bridge_delay_min)


def _seed_costs(
    target: CanalPointHandle,
    *,
    graph: nx.Graph,
    bridge_delay_min: float,
    boat_length_m: float | None,
    boat_beam_m: float | None,
    boat_draft_m: float | None,
    boat_height_m: float | None,
    reverse: bool,
) -> dict[int, float]:
    start, end = target.edge
    seeds: dict[int, float] = {}
    for node, endpoint_fraction in ((start, 0.0), (end, 1.0)):
        if reverse:
            cost = _partial_cost(
                target.edge,
                endpoint_fraction,
                target.fraction,
                graph=graph,
                bridge_delay_min=bridge_delay_min,
                boat_length_m=boat_length_m,
                boat_beam_m=boat_beam_m,
                boat_draft_m=boat_draft_m,
                boat_height_m=boat_height_m,
            )
        else:
            cost = _partial_cost(
                target.edge,
                target.fraction,
                endpoint_fraction,
                graph=graph,
                bridge_delay_min=bridge_delay_min,
                boat_length_m=boat_length_m,
                boat_beam_m=boat_beam_m,
                boat_draft_m=boat_draft_m,
                boat_height_m=boat_height_m,
            )
        if cost is not None:
            seeds[node] = cost
    return seeds


def _directional_costs(
    seeds: dict[int, float],
    *,
    graph: nx.Graph,
    cutoff_min: float,
    bridge_delay_min: float,
    boat_length_m: float | None,
    boat_beam_m: float | None,
    boat_draft_m: float | None,
    boat_height_m: float | None,
    reverse: bool,
    max_work: int,
) -> dict[int, float]:
    distances = dict(seeds)
    queue = [(cost, node) for node, cost in seeds.items()]
    heapify(queue)
    work = 0
    while queue:
        cost, node = heappop(queue)
        if cost != distances.get(node):
            continue
        if cost > cutoff_min:
            continue
        for neighbor in sorted(graph.neighbors(node)):
            work += 1
            if work > max_work:
                raise HireReachabilityError(
                    "reachability_search_limit",
                    "Hire-base reachability exceeds its work limit; reduce the budget.",
                )
            data = graph.edges[node, neighbor]
            if not _dimensions_allowed(
                data, boat_length_m, boat_beam_m, boat_draft_m, boat_height_m
            ):
                continue
            if reverse:
                edge_cost = traversal_time_min(
                    data,
                    graph.nodes[node].get("movable_bridge_ids", ()),
                    movable_bridge_delay_min=bridge_delay_min,
                )
            else:
                edge_cost = traversal_time_min(
                    data,
                    graph.nodes[neighbor].get("movable_bridge_ids", ()),
                    movable_bridge_delay_min=bridge_delay_min,
                )
            candidate = cost + edge_cost
            if candidate > cutoff_min:
                continue
            if candidate < distances.get(neighbor, math.inf):
                distances[neighbor] = candidate
                heappush(queue, (candidate, neighbor))
    return distances


def _base_to_target(
    base: CanalPointHandle,
    target: CanalPointHandle,
    endpoint_costs: dict[int, float],
    *,
    graph: nx.Graph,
    bridge_delay_min: float,
    boat_length_m: float | None,
    boat_beam_m: float | None,
    boat_draft_m: float | None,
    boat_height_m: float | None,
) -> float | None:
    candidates: list[float] = []
    if base.edge == target.edge:
        direct = _partial_cost(
            base.edge,
            base.fraction,
            target.fraction,
            graph=graph,
            bridge_delay_min=bridge_delay_min,
            boat_length_m=boat_length_m,
            boat_beam_m=boat_beam_m,
            boat_draft_m=boat_draft_m,
            boat_height_m=boat_height_m,
        )
        if direct is not None:
            candidates.append(direct)

    for endpoint, endpoint_fraction in zip(base.edge, (0.0, 1.0), strict=True):
        partial = _partial_cost(
            base.edge,
            base.fraction,
            endpoint_fraction,
            graph=graph,
            bridge_delay_min=bridge_delay_min,
            boat_length_m=boat_length_m,
            boat_beam_m=boat_beam_m,
            boat_draft_m=boat_draft_m,
            boat_height_m=boat_height_m,
        )
        if partial is not None and endpoint in endpoint_costs:
            candidates.append(partial + endpoint_costs[endpoint])
    return min(candidates) if candidates else None


def _target_to_base(
    target: CanalPointHandle,
    base: CanalPointHandle,
    endpoint_costs: dict[int, float],
    *,
    graph: nx.Graph,
    bridge_delay_min: float,
    boat_length_m: float | None,
    boat_beam_m: float | None,
    boat_draft_m: float | None,
    boat_height_m: float | None,
) -> float | None:
    candidates: list[float] = []
    if target.edge == base.edge:
        direct = _partial_cost(
            target.edge,
            target.fraction,
            base.fraction,
            graph=graph,
            bridge_delay_min=bridge_delay_min,
            boat_length_m=boat_length_m,
            boat_beam_m=boat_beam_m,
            boat_draft_m=boat_draft_m,
            boat_height_m=boat_height_m,
        )
        if direct is not None:
            candidates.append(direct)

    for endpoint, endpoint_fraction in zip(base.edge, (0.0, 1.0), strict=True):
        partial = _partial_cost(
            base.edge,
            endpoint_fraction,
            base.fraction,
            graph=graph,
            bridge_delay_min=bridge_delay_min,
            boat_length_m=boat_length_m,
            boat_beam_m=boat_beam_m,
            boat_draft_m=boat_draft_m,
            boat_height_m=boat_height_m,
        )
        if partial is not None and endpoint in endpoint_costs:
            candidates.append(endpoint_costs[endpoint] + partial)
    return min(candidates) if candidates else None


def compute_hire_base_reachability(
    target: CanalPointHandle,
    anchors,
    *,
    graph: nx.Graph,
    cutoff_min: float,
    boat_length_m: float | None,
    boat_beam_m: float | None,
    boat_draft_m: float | None,
    boat_height_m: float | None,
    movable_bridge_delay_min: float | None,
    max_work: int = MAX_WORK,
) -> tuple[HireBaseReachability, ...]:
    """Find anchors reachable from a target in both directions within a cutoff."""
    if not math.isfinite(cutoff_min) or cutoff_min < 0:
        raise ValueError("cutoff_min must be finite and non-negative")
    if max_work <= 0:
        raise HireReachabilityError(
            "reachability_search_limit", "Hire-base reachability work limit must be positive."
        )
    _validate_handle(target, graph)
    for anchor in anchors:
        _validate_handle(anchor.handle, graph)

    bridge_delay = resolve_movable_bridge_delay(movable_bridge_delay_min)
    forward = _directional_costs(
        _seed_costs(
            target,
            graph=graph,
            bridge_delay_min=bridge_delay,
            boat_length_m=boat_length_m,
            boat_beam_m=boat_beam_m,
            boat_draft_m=boat_draft_m,
            boat_height_m=boat_height_m,
            reverse=False,
        ),
        graph=graph,
        cutoff_min=cutoff_min,
        bridge_delay_min=bridge_delay,
        boat_length_m=boat_length_m,
        boat_beam_m=boat_beam_m,
        boat_draft_m=boat_draft_m,
        boat_height_m=boat_height_m,
        reverse=False,
        max_work=max_work,
    )
    reverse = _directional_costs(
        _seed_costs(
            target,
            graph=graph,
            bridge_delay_min=bridge_delay,
            boat_length_m=boat_length_m,
            boat_beam_m=boat_beam_m,
            boat_draft_m=boat_draft_m,
            boat_height_m=boat_height_m,
            reverse=True,
        ),
        graph=graph,
        cutoff_min=cutoff_min,
        bridge_delay_min=bridge_delay,
        boat_length_m=boat_length_m,
        boat_beam_m=boat_beam_m,
        boat_draft_m=boat_draft_m,
        boat_height_m=boat_height_m,
        reverse=True,
        max_work=max_work,
    )

    matches = []
    for anchor in anchors:
        one_way = _base_to_target(
            anchor.handle,
            target,
            reverse,
            graph=graph,
            bridge_delay_min=bridge_delay,
            boat_length_m=boat_length_m,
            boat_beam_m=boat_beam_m,
            boat_draft_m=boat_draft_m,
            boat_height_m=boat_height_m,
        )
        return_way = _target_to_base(
            target,
            anchor.handle,
            forward,
            graph=graph,
            bridge_delay_min=bridge_delay,
            boat_length_m=boat_length_m,
            boat_beam_m=boat_beam_m,
            boat_draft_m=boat_draft_m,
            boat_height_m=boat_height_m,
        )
        if one_way is not None and return_way is not None:
            if one_way <= cutoff_min and return_way <= cutoff_min:
                matches.append(HireBaseReachability(anchor, one_way, return_way))
    return tuple(sorted(matches, key=lambda match: (match.one_way_minutes, match.identity)))
