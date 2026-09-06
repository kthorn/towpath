import copy
from dataclasses import dataclass
from typing import Any

import networkx as nx
import pytest  # pyright: ignore[reportMissingImports]
from pound.artifact import RuntimeArtifact
from pound.graph.spatial import CandidateSpatialIndex
from pound.models import AccessCaveat, WayDimensions
from pound.route.cost import (
    CRUISE_KMH,
    DEFAULT_MOVABLE_BRIDGE_DELAY_MIN,
    LOCK_MINUTES,
    time_min,
    traversal_time_min,
)
from pound.route.plan import plan_projected_route
from pound.route.resolve import resolve_place
from pound.schemas import CanalPointHandle, Coordinate, NamedRouteRequest, ProjectedRouteConstraints

from tests.fixtures import routing_test_graph


@dataclass(frozen=True)
class _NodeConstraints:
    start_node: int | CanalPointHandle
    end_node: int | CanalPointHandle
    options: dict[str, Any]


def _artifact(graph: nx.Graph, gazetteer: dict | None = None) -> RuntimeArtifact:
    return RuntimeArtifact(
        graph=graph,
        pois=(),
        gazetteer=gazetteer if gazetteer is not None else graph.graph.get("gazetteer", {}),
        metadata={"fetched_at": graph.graph.get("fetched_at", "")},
    )


def _node_handle(node: int, graph: nx.Graph) -> CanalPointHandle:
    neighbors = sorted(graph.neighbors(node))
    if not neighbors:
        raise ValueError(f"node {node} has no traversable edge")
    low, high = sorted((node, neighbors[0]))
    return CanalPointHandle(edge=(low, high), fraction=float(node == high))


def _as_handle(node: int | CanalPointHandle, graph: nx.Graph) -> CanalPointHandle:
    return node if isinstance(node, CanalPointHandle) else _node_handle(node, graph)


def _node_constraints(
    *, start_node: int | CanalPointHandle, end_node: int | CanalPointHandle, **options
) -> _NodeConstraints:
    return _NodeConstraints(start_node=start_node, end_node=end_node, options=options)


def _projected(constraints: _NodeConstraints | ProjectedRouteConstraints, graph: nx.Graph):
    if isinstance(constraints, ProjectedRouteConstraints):
        return constraints
    return ProjectedRouteConstraints(
        start=_as_handle(constraints.start_node, graph),
        end=_as_handle(constraints.end_node, graph),
        **constraints.options,
    )


def _route(constraints, *, graph: nx.Graph):
    return plan_projected_route(_projected(constraints, graph), artifact=_artifact(graph)).route


def _response(constraints, *, graph: nx.Graph):
    return plan_projected_route(_projected(constraints, graph), artifact=_artifact(graph))


def _access_caveat_graph():
    graph = nx.Graph(fetched_at="2026-08-23T00:00:00Z")
    for uid, lon, name in ((1, -1.0, "Start"), (2, -0.99, "Middle"), (3, -0.98, "End")):
        graph.add_node(uid, lat=51.0, lon=lon, name=name, movable_bridge_ids=())
    dimensions = WayDimensions()
    graph.add_edge(
        1,
        2,
        length_m=700.0,
        locks=0,
        dimensions=dimensions,
        osm_way_id=10,
        geometry=[(51.0, -1.0), (51.0, -0.99)],
        movable_bridge_ids=(),
        tunnel_restrictions=(),
        access_caveats=(AccessCaveat(10, "boat", "discouraged", "discouraged"),),
    )
    graph.add_edge(
        2,
        3,
        length_m=700.0,
        locks=0,
        dimensions=dimensions,
        osm_way_id=20,
        geometry=[(51.0, -0.99), (51.0, -0.98)],
        movable_bridge_ids=(),
        tunnel_restrictions=(),
        access_caveats=(AccessCaveat(20, "access", "customers", "unknown"),),
    )
    return graph


def _graph_and_gaz():
    return routing_test_graph()


def resolve_first(name, graph):
    artifact = _artifact(graph, graph.graph.get("gazetteer", {}))
    return resolve_place(name, artifact, CandidateSpatialIndex(graph))


def _resolved(start="Oxford", end="Hayfield", **kwargs):
    graph, gazetteer = _graph_and_gaz()
    artifact = _artifact(graph, gazetteer)
    index = CandidateSpatialIndex(graph)
    return (
        ProjectedRouteConstraints(
            start=resolve_place(start, artifact, index),
            end=resolve_place(end, artifact, index),
            **kwargs,
        ),
        graph,
    )


def _named_route(constraints: NamedRouteRequest, *, graph: nx.Graph):
    if constraints.end is None:
        raise NotImplementedError("rings not yet supported")
    artifact = _artifact(graph, graph.graph.get("gazetteer", {}))
    index = CandidateSpatialIndex(graph)
    projected = ProjectedRouteConstraints(
        start=resolve_place(constraints.start, artifact, index),
        end=resolve_place(constraints.end, artifact, index),
        **constraints.model_dump(exclude={"start", "end"}),
    )
    return _route(projected, graph=graph)


def test_route_connects_oxford_to_hayfield():
    (rc, g) = _resolved(days=1)
    r = _route(rc, graph=g)
    assert r.start == "Oxford"
    assert r.end == "Hayfield"
    assert r.legs[0].from_place == "Oxford"
    assert r.legs[-1].to_place == "Hayfield"
    for i in range(len(r.legs) - 1):
        assert r.legs[i].to_place == r.legs[i + 1].from_place


def test_totals_equal_sum_of_legs():
    (rc, g) = _resolved(days=1)
    r = _route(rc, graph=g)
    assert r.total_km == pytest.approx(sum(leg.distance_km for leg in r.legs))
    assert r.total_locks == sum(leg.locks for leg in r.legs)
    assert r.total_minutes == sum(leg.est_minutes for leg in r.legs)


def test_per_leg_minutes_match_cost_formula():
    (rc, g) = _resolved(days=1)
    r = _route(rc, graph=g)
    for leg in r.legs:
        expected = round(leg.distance_km / CRUISE_KMH * 60 + leg.locks * LOCK_MINUTES)
        assert leg.est_minutes == expected


def test_total_minutes_matches_time_min_over_edges():
    (rc, g) = _resolved(days=1)
    r = _route(rc, graph=g)
    # rounding accumulates across the 4 legs; the existing Scope C test uses abs=1
    assert r.total_minutes == pytest.approx(
        round(
            time_min(
                r.total_km * 1000,
                r.total_locks,
                movable_bridge_delay_min=DEFAULT_MOVABLE_BRIDGE_DELAY_MIN,
            )
        ),
        abs=1,
    )


def _infrastructure_graph(node_count: int) -> nx.Graph:
    graph = nx.Graph()
    for uid in range(1, node_count + 1):
        graph.add_node(
            uid,
            lat=float(uid),
            lon=float(uid),
            name=str(uid),
            movable_bridge_ids=(),
        )
    return graph


def test_movable_bridge_delay_changes_selected_path():
    graph = _infrastructure_graph(4)
    for u, v, length_m, osm_way_id, movable_bridge_ids in (
        (1, 2, 500.0, 12, ("way:12",)),
        (2, 4, 500.0, 24, ()),
        (1, 3, 650.0, 13, ()),
        (3, 4, 650.0, 34, ()),
    ):
        graph.add_edge(
            u,
            v,
            length_m=length_m,
            locks=0,
            dimensions=WayDimensions(),
            osm_way_id=osm_way_id,
            movable_bridge_ids=movable_bridge_ids,
            tunnel_restrictions=(),
        )

    default_delay = _route(
        _node_constraints(start_node=1, end_node=4, movable_bridge_delay_min=None), graph=graph
    )
    zero_delay = _route(
        _node_constraints(start_node=1, end_node=4, movable_bridge_delay_min=0.0), graph=graph
    )

    assert [(leg.from_place, leg.to_place) for leg in default_delay.legs] == [
        ("1", "3"),
        ("3", "4"),
    ]
    assert [(leg.from_place, leg.to_place) for leg in zero_delay.legs] == [("1", "2"), ("2", "4")]


def test_arrived_at_movable_bridge_node_costs_once():
    graph = _infrastructure_graph(3)
    graph.nodes[2]["movable_bridge_ids"] = ("node:2",)
    for u, v, osm_way_id in ((1, 2, 12), (2, 3, 23)):
        graph.add_edge(
            u,
            v,
            length_m=0.0,
            locks=0,
            dimensions=WayDimensions(),
            osm_way_id=osm_way_id,
            movable_bridge_ids=(),
            tunnel_restrictions=(),
        )

    route = _route(
        _node_constraints(start_node=1, end_node=3, movable_bridge_delay_min=None), graph=graph
    )

    assert [leg.est_minutes for leg in route.legs] == [DEFAULT_MOVABLE_BRIDGE_DELAY_MIN, 0]
    assert route.total_minutes == DEFAULT_MOVABLE_BRIDGE_DELAY_MIN


def test_traversal_time_min_unions_edge_and_arrived_node_bridges():
    edge = {"length_m": 0.0, "locks": 0, "movable_bridge_ids": ("edge:1",)}

    assert (
        traversal_time_min(
            edge,
            ("node:2",),
            movable_bridge_delay_min=DEFAULT_MOVABLE_BRIDGE_DELAY_MIN,
        )
        == 2 * DEFAULT_MOVABLE_BRIDGE_DELAY_MIN
    )


def test_selected_tunnel_restrictions_are_warnings():
    graph = _infrastructure_graph(2)
    graph.add_edge(
        1,
        2,
        length_m=100.0,
        locks=0,
        dimensions=WayDimensions(),
        osm_way_id=77,
        has_tunnel=True,
        movable_bridge_ids=(),
        tunnel_restrictions=(
            (77, "oneway:boat", "yes"),
            (77, "opening_hours", "Mo-Fr 09:00-17:00"),
        ),
    )

    route = _route(_node_constraints(start_node=1, end_node=2), graph=graph)

    assert route.warnings == [
        'tunnel way 77: unmodeled restriction oneway:boat="yes"',
        'tunnel way 77: unmodeled restriction opening_hours="Mo-Fr 09:00-17:00"',
    ]


def test_access_caveats_suppress_duplicate_tunnel_warnings():
    graph = _infrastructure_graph(2)
    graph.add_edge(
        1,
        2,
        length_m=100.0,
        locks=0,
        dimensions=WayDimensions(),
        osm_way_id=77,
        has_tunnel=True,
        movable_bridge_ids=(),
        tunnel_restrictions=(
            (77, "boat", "discouraged"),
            (77, "access", "permissive"),
        ),
        access_caveats=(AccessCaveat(77, "boat", "discouraged", "discouraged"),),
    )

    route = _route(_node_constraints(start_node=1, end_node=2), graph=graph)

    assert route.warnings == [
        "Route uses 1 segment(s) tagged boat=discouraged; verify local access.",
        'tunnel way 77: unmodeled restriction access="permissive"',
    ]


def test_empty_oneway_value_warns():
    graph = nx.Graph()
    graph.add_node(
        1,
        lat=51.0,
        lon=-1.0,
        name="Start",
        osm_node_ids={"1"},
        movable_bridge_ids=(),
        turning_point=False,
        turning_max_length_m=None,
    )
    graph.add_node(
        2,
        lat=51.0,
        lon=-0.98,
        name="End",
        osm_node_ids={"2"},
        movable_bridge_ids=(),
        turning_point=False,
        turning_max_length_m=None,
    )
    graph.add_edge(
        1,
        2,
        osm_way_id=77,
        name="Tunnel",
        kind="canal",
        length_m=100.0,
        dimensions=WayDimensions(),
        has_tunnel=True,
        has_movable_bridge=False,
        locks=0,
        geometry=[(51.0, -1.0), (51.0, -0.98)],
        movable_bridge_ids=(),
        tunnel_restrictions=((77, "oneway", ""),),
        access_caveats=(),
    )
    route = _route(_node_constraints(start_node=1, end_node=2), graph=graph)
    assert 'tunnel way 77: unmodeled restriction oneway=""' in route.warnings


def test_locks_counted_on_lock_edge():
    (rc, g) = _resolved(days=1)
    r = _route(rc, graph=g)
    assert r.total_locks == 1


def test_warnings_flag_unknown_dims():
    (rc, g) = _resolved(days=1, boat_beam_m=2.0, boat_draft_m=0.8)
    r = _route(rc, graph=g)
    assert any("unknown" in w.lower() for w in r.warnings)


def test_route_reports_selected_access_caveats_without_mutating_graph():
    graph = _access_caveat_graph()
    before = copy.deepcopy({(u, v): data for u, v, data in graph.edges(data=True)})
    route = _route(_node_constraints(start_node=1, end_node=3), graph=graph)
    assert [segment.model_dump() for segment in route.access_segments] == [
        {
            "osm_way_id": 10,
            "kind": "discouraged",
            "tag": "boat",
            "value": "discouraged",
        },
        {
            "osm_way_id": 20,
            "kind": "unknown",
            "tag": "access",
            "value": "customers",
        },
    ]
    assert route.warnings == [
        "Route uses 1 segment(s) tagged boat=discouraged; verify local access.",
        'Route uses 1 segment(s) with unrecognized access="customers"; verify local access.',
    ]
    assert {(u, v): data for u, v, data in graph.edges(data=True)} == before


def test_route_omits_caveats_from_unselected_edges():
    graph = _infrastructure_graph(3)
    dimensions = WayDimensions()
    graph.add_edge(
        1,
        3,
        length_m=100.0,
        locks=0,
        dimensions=dimensions,
        osm_way_id=13,
        movable_bridge_ids=(),
        tunnel_restrictions=(),
        access_caveats=(),
    )
    graph.add_edge(
        1,
        2,
        length_m=1_000.0,
        locks=0,
        dimensions=dimensions,
        osm_way_id=12,
        movable_bridge_ids=(),
        tunnel_restrictions=(),
        access_caveats=(AccessCaveat(12, "boat", "discouraged", "discouraged"),),
    )
    graph.add_edge(
        2,
        3,
        length_m=1_000.0,
        locks=0,
        dimensions=dimensions,
        osm_way_id=23,
        movable_bridge_ids=(),
        tunnel_restrictions=(),
        access_caveats=(),
    )

    route = _route(_node_constraints(start_node=1, end_node=3), graph=graph)

    assert [(leg.from_place, leg.to_place) for leg in route.legs] == [("1", "3")]
    assert route.access_segments == []
    assert route.warnings == []


def test_route_uses_available_indirect_path():
    graph = _infrastructure_graph(3)
    for u, v, osm_way_id in ((1, 2, 10), (2, 3, 20)):
        graph.add_edge(
            u,
            v,
            length_m=1_000.0,
            locks=0,
            dimensions=WayDimensions(),
            osm_way_id=osm_way_id,
            movable_bridge_ids=(),
            tunnel_restrictions=(),
            access_caveats=(),
        )

    route = _route(_node_constraints(start_node=1, end_node=3), graph=graph)

    assert [(leg.from_place, leg.to_place) for leg in route.legs] == [("1", "2"), ("2", "3")]
    assert route.access_segments == []


def test_graph_source_date_from_metadata():
    (rc, g) = _resolved(days=1)
    r = _route(rc, graph=g)
    assert r.graph_source_date == "2026-06-21T12:00:00Z"


def test_ring_raises_not_implemented():
    # NamedRouteRequest(end=None) remains unsupported by the diagnostic adapter.
    g, _ = _graph_and_gaz()
    with pytest.raises(NotImplementedError, match="rings not yet supported"):
        _named_route(NamedRouteRequest(start="Oxford", end=None, days=1), graph=g)


def test_single_day_plan_wraps_legs():
    (rc, g) = _resolved(days=1)
    r = _route(rc, graph=g)
    assert len(r.days) == 1
    assert r.days[0].legs == r.legs
    assert r.days[0].cruising_minutes == r.total_minutes


def test_no_path_under_dimensions_raises_valueerror_not_traceback():
    g, _ = _graph_and_gaz()
    rc = _node_constraints(
        start_node=resolve_first("Oxford", g),
        end_node=resolve_first("Hayfield", g),
        days=1,
        boat_beam_m=99.0,
        boat_draft_m=99.0,  # bigger than any edge
    )
    with pytest.raises(ValueError, match="no path between"):
        _route(rc, graph=g)


def test_single_day_over_budget_warns():
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0  # ~162 min leg, ~3 h budget at 1 h/day
    rc = _node_constraints(
        start_node=resolve_first("Oxford", g),
        end_node=resolve_first("Hayfield", g),
        days=1,
        hours_per_day=1.0,
    )
    r = _route(rc, graph=g)
    assert len(r.days) == 1  # forced single day via max_days cap
    assert r.days[0].cruising_minutes > 1.0 * 60
    assert any("exceed hours_per_day" in w for w in r.warnings)


def _long_resolved(days, hours_per_day, g):
    return _node_constraints(
        start_node=resolve_first("Oxford", g),
        end_node=resolve_first("Hayfield", g),
        days=days,
        hours_per_day=hours_per_day,
    )


def test_multiday_splits_legs_within_budget():
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0
    # 4 edges ~162 min each; hours_per_day=3 -> 180 min budget. Greedy emits
    # one edge per day (each +next would exceed 180) -> 4 days, each in budget.
    rc = _long_resolved(days=4, hours_per_day=3.0, g=g)
    r = _route(rc, graph=g)
    assert len(r.days) == 4
    for day in r.days:
        assert day.cruising_minutes <= 3.0 * 60
        assert day.legs


def test_days_partition_legs_exactly():
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0
    rc = _long_resolved(days=4, hours_per_day=3.0, g=g)
    r = _route(rc, graph=g)
    flat = [leg for day in r.days for leg in day.legs]
    assert flat == r.legs


def test_days_not_padded_beyond_route():
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0
    rc = _long_resolved(days=5, hours_per_day=3.0, g=g)
    r = _route(rc, graph=g)
    assert len(r.days) == 4  # 4 edges need 4 days; days=5 does not pad with empties
    assert all(day.legs for day in r.days)


def test_days_count_never_exceeds_constraints_days():
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0
    rc = _long_resolved(days=2, hours_per_day=3.0, g=g)
    r = _route(rc, graph=g)
    assert len(r.days) <= 2


def test_day_index_sequential():
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0
    rc = _long_resolved(days=4, hours_per_day=3.0, g=g)
    r = _route(rc, graph=g)
    assert [d.day for d in r.days] == [1, 2, 3, 4]


def test_projected_route_emits_day_geometries_and_route_locks():
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0
    rc = _long_resolved(days=None, hours_per_day=6.0, g=g)

    response = _response(rc, graph=g)

    assert [item.day for item in response.day_geometries] == [1, 2]
    assert response.day_geometries[0].start == Coordinate(lat=51.75, lon=-1.26)
    assert response.day_geometries[0].end == response.day_geometries[1].start
    assert [lock.day for lock in response.locks] == [2]
    assert response.locks[0].coordinate == Coordinate(lat=51.754, lon=-1.264)
    assert not response.locks[0].approximate


def test_far_source_lock_point_falls_back_to_approximate_midpoint():
    graph = nx.Graph()
    graph.add_node(1, lat=51.0, lon=-1.0, name="Start", movable_bridge_ids=())
    graph.add_node(2, lat=51.0, lon=-0.98, name="End", movable_bridge_ids=())
    graph.add_edge(
        1,
        2,
        geometry=[(51.0, -1.0), (51.0, -0.98)],
        length_m=1400.0,
        locks=1,
        lock_points=[(52.0, -1.0)],
        dimensions=WayDimensions(),
        osm_way_id=1,
        movable_bridge_ids=(),
        tunnel_restrictions=(),
    )

    response = _response(_node_constraints(start_node=1, end_node=2), graph=graph)

    assert response.locks[0].coordinate.lat == pytest.approx(51.0, abs=1e-7)
    assert response.locks[0].coordinate.lon == pytest.approx(-0.99, abs=1e-7)
    assert response.locks[0].approximate


def test_approximate_lock_uses_midpoint_along_curved_geometry():
    graph = nx.Graph()
    graph.add_node(1, lat=0, lon=0, name="Start", movable_bridge_ids=())
    graph.add_node(2, lat=0, lon=2, name="End", movable_bridge_ids=())
    graph.add_edge(
        1,
        2,
        geometry=[(0, 0), (1, 1), (0, 2)],
        length_m=200_000,
        locks=1,
        dimensions=WayDimensions(),
        osm_way_id=1,
        movable_bridge_ids=(),
        tunnel_restrictions=(),
    )

    response = _response(_node_constraints(start_node=1, end_node=2), graph=graph)

    assert response.locks[0].coordinate == Coordinate(lat=1, lon=1)
    assert response.locks[0].approximate


def test_named_route_adapter_resolves_through_projected_planner():
    g, _ = _graph_and_gaz()
    r = _named_route(NamedRouteRequest(start="Oxford", end="Hayfield", days=1), graph=g)
    assert r.start == "Oxford"
    assert r.end == "Hayfield"
    assert r.legs  # non-empty


def test_days_none_infers_no_cap():
    # days omitted (None) => hours_per_day alone drives chunking; no cap.
    # 4 ~162-min edges at 3 h/day => 4 days; None cap behaves like max_days=inf.
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0
    rc = _node_constraints(
        start_node=resolve_first("Oxford", g),
        end_node=resolve_first("Hayfield", g),
        days=None,
        hours_per_day=3.0,
    )
    r = _route(rc, graph=g)
    assert len(r.days) == 4  # uncapped -> one day per edge, no folding


def test_days_none_with_more_time_fits_in_fewer_days():
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 1000.0  # tiny edges; whole route fits one day
    rc = _node_constraints(
        start_node=resolve_first("Oxford", g),
        end_node=resolve_first("Hayfield", g),
        days=None,
        hours_per_day=6.0,
    )
    r = _route(rc, graph=g)
    assert len(r.days) == 1


@pytest.mark.parametrize("planner", [_route, _response])
def test_same_handle_returns_an_empty_route_with_valid_labels(planner):
    constraints, graph = _resolved(start="Oxford", end="Oxford")

    response = planner(constraints, graph=graph)
    route = response.route if hasattr(response, "route") else response

    assert route.start == "Oxford"
    assert route.end == "Oxford"
    assert route.total_km == 0
    assert route.total_locks == 0
    assert route.total_minutes == 0
    assert route.legs == []
    assert route.days == []
    if hasattr(response, "geometry"):
        endpoint = (
            constraints.start.edge[0]
            if constraints.start.fraction == 0
            else constraints.start.edge[1]
        )
        node = graph.nodes[endpoint]
        point = (node["lon"], node["lat"])
        assert response.geometry.coordinates == [point, point]
