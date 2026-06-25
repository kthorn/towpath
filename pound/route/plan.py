"""Request-time entry point — real plan_route (design §5).

Loads the prebuilt graph artifact once (module-level cache), snaps start/end
to graph nodes via the offline gazetteer, filters edges by boat dimensions,
runs Dijkstra by time-cost, and assembles a RouteResult. Pure: no network,
no LLM. Point-to-point only in this scope; rings raise NotImplementedError.
Day budgeting is trivial cumulative-minute chunking (design §5.3): legs are
packed greedily into consecutive DayPlans within hours_per_day, emitting as
many non-empty days as the route needs (NOT padded to constraints.days —
OQ-8). Mooring-aware day placement is deferred to Scope D.
"""

import networkx as nx

from pound.ingest.ir import WaterwayFeatures
from pound.route.cost import is_eligible, time_min
from pound.route.snap import build_gazetteer, snap_place
from pound.schemas import CanalConstraints, DayPlan, RouteLeg, RouteResult


def plan_route(
    constraints: CanalConstraints,
    *,
    _graph: nx.Graph | None = None,
    _features: WaterwayFeatures | None = None,
) -> RouteResult:
    """Plan a point-to-point canal route.

    Production callers omit the underscore-prefixed kwargs; those are for
    hermetic testing (inject a graph + features built from the fixture without
    pickle IO). Rings (end is None) are not yet supported.
    """
    if constraints.end is None:
        raise NotImplementedError(
            "rings not yet supported (design §5.3; scope C is point-to-point)"
        )

    if _graph is None or _features is None:
        # Production path: load the artifact. Wired when the build CLI lands
        # the artifact; for now this branch is not exercised by tests.
        raise RuntimeError(
            "artifact loading not wired in this scope; pass _graph and _features for testing"
        )

    graph, features = _graph, _features
    gaz = build_gazetteer(features)
    start_node = snap_place(constraints.start, gaz, graph)
    end_node = snap_place(constraints.end, gaz, graph)

    if not nx.has_path(graph, start_node, end_node):
        raise ValueError(f"no path between {constraints.start!r} and {constraints.end!r}")

    # Build the weight function, applying dimension eligibility.
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
            return None  # NetworkX treats None as impassable
        if unknown:
            unknown_edges.append(str(d["osm_way_id"]))
        return time_min(
            d["length_m"],
            d.get("locks", 0),
        )

    path = nx.shortest_path(graph, start_node, end_node, weight=weight)

    # Assemble legs from consecutive path edges.
    legs: list[RouteLeg] = []
    for u, v in zip(path, path[1:], strict=False):
        d = graph.edges[u, v]
        km = d["length_m"] / 1000.0
        locks = d.get("locks", 0)
        legs.append(
            RouteLeg(
                from_place=_name_for(u, features, gaz),
                to_place=_name_for(v, features, gaz),
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

    days = _chunk_days(legs, constraints.hours_per_day, constraints.days)
    if len(days) > 1 and any(day.cruising_minutes > constraints.hours_per_day * 60 for day in days):
        warnings.append("one or more days exceed hours_per_day budget")

    return RouteResult(
        start=constraints.start,
        end=constraints.end,
        is_ring=False,
        legs=legs,
        days=days,
        total_km=total_km,
        total_locks=total_locks,
        total_minutes=total_minutes,
        amenities=[],  # amenities are design §5.4, out of scope
        warnings=warnings,
        graph_source_date=features.fetched_at,
    )


def _chunk_days(legs: list[RouteLeg], hours_per_day: float, max_days: int) -> list[DayPlan]:
    """Greedily pack legs into consecutive DayPlans within the per-day budget.

    Each day's cruising_minutes <= hours_per_day*60. Emits as many non-empty
    days as the route needs, up to max_days (OQ-8: no empty padding). A single
    leg longer than the budget forms its own day (overflows; caller warns).
    Mooring-aware placement is a Scope D concern; end_near is the day's last
    leg to_place for now.
    """
    budget = hours_per_day * 60.0
    days: list[DayPlan] = []
    current: list[RouteLeg] = []
    current_min = 0

    def flush():
        nonlocal current, current_min
        if current:
            days.append(
                DayPlan(
                    day=len(days) + 1,
                    legs=current,
                    end_near=current[-1].to_place,
                    cruising_minutes=current_min,
                )
            )
            current = []
            current_min = 0

    for leg in legs:
        # Start a new day when adding this leg would overflow the current one.
        if current and current_min + leg.est_minutes > budget:
            flush()
        # max_days cap: if we've already emitted max_days days, fold the
        # remaining legs into the last day instead of opening a new one.
        if len(days) >= max_days and not current and days:
            last = days[-1]
            last.legs.append(leg)
            last.cruising_minutes += leg.est_minutes
            last.end_near = leg.to_place
            continue
        current.append(leg)
        current_min += leg.est_minutes
    flush()
    return days


def _name_for(node_key, features, gazetteer) -> str:
    """Reverse-lookup a node key to a place name; fall back to coordinate string."""
    for name, key in gazetteer.items():
        if key == node_key:
            return name
    return f"{node_key[0]},{node_key[1]}"
