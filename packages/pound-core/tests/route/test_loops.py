"""Closed circuits and retraced connections use the full journey budget."""

import copy

import networkx as nx
import pytest
from pound.models import WayDimensions
from pound.route.loops import discover_loops, plan_loop
from pound.route.project import project_handle
from pound.route.round_trip import RoundTripError
from pound.schemas import CanalPointHandle, LoopCandidatesRequest, LoopRouteRequest
from pydantic import ValidationError

from .test_round_trip import branch_graph


def request(**changes):
    return LoopCandidatesRequest(
        **(dict(artifact_revision="test", start_uid=0, days=1, hours_per_day=1) | changes)
    )


def paths(result):
    return [
        [r.journey.route.legs[0].from_place] + [leg.to_place for leg in r.journey.route.legs]
        for r in result.routes
    ]


def test_circuit_through_base_in_both_directions_without_turnaround_index():
    graph = branch_graph([(0, 1), (1, 2), (2, 0)], [])
    del graph.graph["turnarounds"]
    before = copy.deepcopy(graph)
    result = discover_loops(request(), graph=graph)
    assert paths(result) == [["0", "1", "2", "0"], ["0", "2", "1", "0"]]
    assert result.default_route_id == result.routes[0].route_id
    assert len({r.route_id for r in result.routes}) == 2
    for r in result.routes:
        assert r.journey_type == "loop"
        assert r.journey.route.is_ring
        assert r.loop_distance_km == pytest.approx(0.24)
        assert r.connecting_distance_km == 0
        assert r.journey.route.total_minutes == 3
        assert r.journey.route.start == r.journey.route.end == "0"
        assert r.journey.geometry.coordinates[0] == r.journey.geometry.coordinates[-1]
    assert nx.utils.graphs_equal(graph, before)


def test_connection_is_retraced_and_counted_twice():
    graph = branch_graph([(0, 1), (1, 2), (2, 3), (3, 4), (4, 2)], [])
    result = discover_loops(request(), graph=graph)
    assert paths(result) == [
        ["0", "1", "2", "3", "4", "2", "1", "0"],
        ["0", "1", "2", "4", "3", "2", "1", "0"],
    ]
    for r in result.routes:
        assert r.connecting_distance_km == pytest.approx(0.16)
        assert r.loop_distance_km == pytest.approx(0.24)
        assert r.journey.route.total_km == pytest.approx(0.56)
        assert r.budget.used_minutes == pytest.approx(7)


def test_distinct_circuits_connections_and_waypoints_are_preserved():
    # The same outer ring has two possible connecting branches from the base.
    graph = branch_graph([(0, 1), (0, 2), (1, 3), (2, 3), (3, 4), (4, 5), (5, 3)], [])
    result = discover_loops(request(waypoint_uid=4), graph=graph)
    assert len(result.routes) == 4
    assert all("4" in path for path in paths(result))
    assert {tuple(path[:3]) for path in paths(result)} == {("0", "1", "3"), ("0", "2", "3")}
    assert all(path.count("4") == 1 for path in paths(result))
    assert all(r.journey.route.total_minutes == 7 for r in result.routes)


@pytest.mark.parametrize("waypoint", [0, 1, 2, 3])
def test_visit_may_be_on_connection_or_circuit(waypoint):
    graph = branch_graph([(0, 1), (1, 2), (2, 3), (3, 1)], [])
    assert len(discover_loops(request(waypoint_uid=waypoint), graph=graph).routes) == 2


def test_tree_zero_distance_loop_and_unvisited_waypoint_are_not_trips():
    cases = [
        (branch_graph([(0, 1), (1, 2)], []), {}),
        (branch_graph([(0, 1), (1, 2), (2, 0), (0, 3)], []), {"waypoint_uid": 3}),
    ]
    zero = branch_graph([(0, 1), (1, 2), (2, 0)], [])
    for _, _, data in zero.edges(data=True):
        data["length_m"] = 0
    cases.append((zero, {}))
    for graph, changes in cases:
        with pytest.raises(RoundTripError) as error:
            discover_loops(request(**changes), graph=graph)
        assert error.value.code == "no_feasible_loop"


def test_full_budget_boundary_and_fractional_estimates():
    graph = branch_graph([(0, 1), (1, 2), (2, 3), (3, 1)], [])
    assert len(discover_loops(request(hours_per_day=5 / 60), graph=graph).routes) == 2
    with pytest.raises(RoundTripError) as error:
        discover_loops(request(hours_per_day=4.99 / 60), graph=graph)
    assert error.value.code == "no_feasible_loop"
    graph.edges[0, 1]["length_m"] = 80.1
    with pytest.raises(RoundTripError):
        discover_loops(request(hours_per_day=5 / 60), graph=graph)


def test_locks_bridges_and_day_plans_cover_every_traversal():
    graph = branch_graph([(0, 1), (1, 2), (2, 3), (3, 1)], [])
    graph.edges[0, 1]["locks"] = 1
    graph.edges[2, 3]["locks"] = 1
    graph.nodes[0]["movable_bridge_ids"] = ("base-bridge",)
    graph.nodes[1]["movable_bridge_ids"] = ("junction-bridge",)
    result = discover_loops(request(days=3, hours_per_day=0.5), graph=graph)
    for r in result.routes:
        journey = r.journey
        assert journey.route.total_locks == len(journey.locks) == 3
        assert journey.route.total_minutes == 56  # 5 cruise + 36 locks + 15 bridges
        assert journey.route.total_minutes == sum(d.cruising_minutes for d in journey.route.days)
        assert all(d.cruising_minutes <= 30 for d in journey.route.days)
        assert journey.day_geometries[0].start == journey.day_geometries[-1].end
        assert r.budget.used_minutes >= journey.route.total_minutes


@pytest.mark.parametrize("block", ["dimensions", "access", "routing_eligible"])
def test_ineligible_circuit_edges_cannot_be_used(block):
    graph = branch_graph([(0, 1), (1, 2), (2, 0)], [])
    graph.edges[1, 2][block] = {
        "dimensions": WayDimensions(max_length_m=10),
        "access": "private",
        "routing_eligible": False,
    }[block]
    with pytest.raises(RoundTripError) as error:
        discover_loops(request(boat_length_m=18), graph=graph)
    assert error.value.code == "no_feasible_loop"


def test_order_and_identity_are_insertion_independent_and_longest_first():
    graph = branch_graph([(0, 1), (1, 2), (2, 0), (0, 3), (3, 4), (4, 0)], [])
    graph.edges[3, 4]["length_m"] = 160
    reordered = nx.Graph()
    reordered.graph.update(copy.deepcopy(graph.graph))
    reordered.add_nodes_from(reversed(list(graph.nodes(data=True))))
    reordered.add_edges_from(reversed(list(graph.edges(data=True))))
    result = discover_loops(request(), graph=graph)
    assert result == discover_loops(request(), graph=reordered)
    assert [r.journey.route.total_km for r in result.routes] == [0.32, 0.32, 0.24, 0.24]


def test_exact_selection_and_stale_constraints():
    graph = branch_graph([(0, 1), (1, 2), (2, 0)], [])
    result = discover_loops(request(), graph=graph)
    assert plan_loop(LoopRouteRequest(**request().model_dump()), graph=graph) == result.routes[0]
    selected = result.routes[-1]
    body = LoopRouteRequest(
        **request().model_dump(), request_id=result.request_id, route_id=selected.route_id
    )
    assert plan_loop(body, graph=graph) == selected.model_copy(
        update={"selection_basis": "user_selected"}
    )
    for change in ({"days": 2}, {"route_id": "missing"}):
        with pytest.raises(RoundTripError) as error:
            plan_loop(body.model_copy(update=change), graph=graph)
        assert error.value.code == "stale_route_selection"
        assert error.value.status == 409
    with pytest.raises(ValidationError):
        LoopRouteRequest(**request().model_dump(), route_id="missing")


@pytest.mark.parametrize("limits", [{"max_work": 1}, {"max_routes": 1}, {"max_vertices": 1}])
def test_search_limits_never_return_partial_success(limits):
    graph = branch_graph([(0, 1), (1, 2), (2, 0)], [])
    with pytest.raises(RoundTripError) as error:
        discover_loops(request(), graph=graph, **limits)
    assert error.value.code == "candidate_search_limit"


def test_revision_and_node_validation():
    graph = branch_graph([(0, 1)], [])
    graph.graph["artifact_revision"] = "new"
    with pytest.raises(RoundTripError) as error:
        discover_loops(request(start_uid=99), graph=graph)
    assert error.value.code == "artifact_revision_mismatch"
    with pytest.raises(RoundTripError) as error:
        discover_loops(request(artifact_revision="new", start_uid=99), graph=graph)
    assert error.value.code == "invalid_node_handle"


def test_projected_base_and_visit_on_same_edge_keep_exact_position():
    graph = branch_graph([(0, 1), (1, 2), (2, 0)], [])
    before = copy.deepcopy(graph)
    start = CanalPointHandle(edge=(0, 1), fraction=0.25)
    visit = CanalPointHandle(edge=(0, 1), fraction=0.75)
    body = request(start_uid=None, start=start, waypoint=visit)
    result = discover_loops(body, graph=graph)
    coordinate = project_handle(start, graph).coordinate
    visit_coordinate = project_handle(visit, graph).coordinate
    assert len(result.routes) == 2
    for r in result.routes:
        coordinates = r.journey.geometry.coordinates
        assert coordinates[0] == coordinates[-1] == (coordinate.lon, coordinate.lat)
        assert (visit_coordinate.lon, visit_coordinate.lat) in coordinates
        assert r.journey.route.total_km == pytest.approx(0.24)
    assert nx.utils.graphs_equal(before, graph)


def test_return_lower_bound_does_not_require_retracing_outbound_route():
    graph = branch_graph([(0, 1), (1, 2), (2, 0)], [])
    graph.edges[0, 1]["length_m"] = 80 * 8
    result = discover_loops(request(hours_per_day=10 / 60), graph=graph)
    assert len(result.routes) == 2  # 8 + 1 + 1 fits; twice the outbound 8 does not.


def test_fractional_minute_exact_boundary_is_not_rejected_by_float_accumulation():
    graph = branch_graph([(0, 1), (1, 2), (2, 0)], [])
    for _, _, data in graph.edges(data=True):
        data["length_m"] = 8
    result = discover_loops(request(hours_per_day=0.3 / 60), graph=graph)
    assert len(result.routes) == 2
    assert all(r.budget.used_minutes == pytest.approx(0.3) for r in result.routes)


def test_long_cycle_uses_iterative_search():
    edges = [(uid, uid + 1) for uid in range(1100)] + [(1100, 0)]
    graph = branch_graph(edges, [])
    result = discover_loops(request(days=4, hours_per_day=6), graph=graph)
    assert len(result.routes) == 2
    assert all(len(r.journey.route.legs) >= 1101 for r in result.routes)
    assert all(r.journey.route.total_km == pytest.approx(88.08) for r in result.routes)


def test_dead_end_branches_do_not_exhaust_search_for_small_circuit_network():
    circuit_edges = [(u, v) for u in range(4) for v in range(u + 1, 4)]
    graph = branch_graph(circuit_edges + [(3, leaf) for leaf in range(4, 304)], [])
    result = discover_loops(request(), graph=graph, max_work=4000)
    expected = discover_loops(request(), graph=branch_graph(circuit_edges, []))
    assert {tuple(path) for path in paths(result)} == {tuple(path) for path in paths(expected)}


def test_directional_bridge_deduplication_changes_orientation_cost_and_order():
    graph = branch_graph([(0, 1), (1, 2), (2, 0)], [])
    graph.edges[0, 1]["movable_bridge_ids"] = ("bridge",)
    graph.nodes[1]["movable_bridge_ids"] = ("bridge",)
    result = discover_loops(request(), graph=graph)
    assert paths(result) == [["0", "1", "2", "0"], ["0", "2", "1", "0"]]
    assert [r.journey.route.total_minutes for r in result.routes] == [8, 13]
    assert [r.budget.used_minutes for r in result.routes] == [8, 13]
    # Only the cheaper direction fits this budget.
    tight = discover_loops(request(hours_per_day=10 / 60), graph=graph)
    assert paths(tight) == [["0", "1", "2", "0"]]


def test_peeling_preserves_stem_across_articulations_and_multiple_circuits():
    edges = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 2), (4, 5), (5, 6), (6, 7), (7, 8), (8, 6)]
    original = branch_graph(edges, [])
    with_leaves = branch_graph(edges + [(1, 9), (5, 10), (10, 11)], [])
    assert paths(discover_loops(request(), graph=with_leaves)) == paths(
        discover_loops(request(), graph=original)
    )
    assert any(
        r.connecting_distance_km > 0.3
        for r in discover_loops(
            request(),
            graph=with_leaves,
        ).routes
    )
