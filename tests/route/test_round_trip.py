"""Complete branch enumeration, retraced geometry, and conservative budgets."""

import copy

import networkx as nx
import pytest
from pydantic import ValidationError

from pound.ingest.ir import WayDimensions
from pound.route.round_trip import RoundTripError, discover_round_trips, plan_out_and_back
from pound.schemas import OutAndBackRouteRequest, TurnaroundCandidatesRequest


def branch_graph(edges, turnarounds):
    graph = nx.Graph(fetched_at="2026-09-05", turnarounds=[])
    for u, v in edges:
        for uid in (u, v):
            graph.add_node(
                uid,
                lat=51 + uid * 0.001,
                lon=-1,
                name=str(uid),
                movable_bridge_ids=(),
                osm_node_ids={str(uid)},
            )
        graph.add_edge(
            u,
            v,
            length_m=80,
            locks=0,
            dimensions=WayDimensions(),
            osm_way_id=u * 100 + v,
            name="Canal",
            kind="canal",
            geometry=[(graph.nodes[u]["lat"], -1), (graph.nodes[v]["lat"], -1)],
            movable_bridge_ids=(),
            tunnel_restrictions=(),
            access_caveats=(),
        )
    for uid in turnarounds:
        graph.graph["turnarounds"].append(
            dict(
                turnaround_id=f"test:{uid}",
                kind="winding_hole",
                node_uid=uid,
                coordinate=dict(lat=graph.nodes[uid]["lat"], lon=-1),
                display_name=f"Hole {uid}",
                eligibility_basis="mapped_winding_hole",
                sources=[],
                turning_limits={},
            )
        )
    return graph


def request(**kwargs):
    return TurnaroundCandidatesRequest(
        artifact_revision="test", start_uid=0, days=1, hours_per_day=1, **kwargs
    )


def test_two_level_fork_returns_four_furthest_routes():
    graph = branch_graph(
        [(0, 1), (1, 2), (1, 3), (2, 4), (2, 5), (3, 6), (3, 7)], [1, 2, 3, 4, 5, 6, 7]
    )
    before = copy.deepcopy(graph)
    result = discover_round_trips(request(), graph=graph)
    assert {r.turnaround.node_uid for r in result.routes} == {4, 5, 6, 7}
    assert result.default_route_id == result.routes[0].route_id
    for route in result.routes:
        coords = route.journey.geometry.coordinates
        assert coords == coords[::-1]
        assert route.journey.route.start == route.journey.route.end == "0"
        assert route.journey.route.is_ring is False
        assert route.journey.route.total_minutes == 6
    assert nx.utils.graphs_equal(graph, before)


def test_rejoined_branches_keep_distinct_paths_to_same_hole():
    graph = branch_graph([(0, 1), (1, 2), (1, 3), (2, 4), (3, 4), (4, 5)], [5])
    result = discover_round_trips(request(), graph=graph)
    assert len(result.routes) == 2
    assert len({r.route_id for r in result.routes}) == 2
    assert len({r.turnaround.turnaround_id for r in result.routes}) == 1
    assert result.routes[0].journey.geometry != result.routes[1].journey.geometry
    # Stable regardless of adjacency insertion order.
    reordered = nx.Graph()
    reordered.graph.update(copy.deepcopy(graph.graph))
    reordered.add_nodes_from(reversed(list(graph.nodes(data=True))))
    reordered.add_edges_from(reversed(list(graph.edges(data=True))))
    assert discover_round_trips(request(), graph=reordered) == result


def test_budget_falls_back_to_last_feasible_turn_and_deduplicates():
    graph = branch_graph([(0, 1), (1, 2), (1, 3)], [1, 2, 3])
    graph.edges[1, 2]["length_m"] = graph.edges[1, 3]["length_m"] = 8000
    result = discover_round_trips(request(), graph=graph)
    assert [r.turnaround.node_uid for r in result.routes] == [1]
    assert any(r.code == "budget_exceeded" for r in result.rejections)


def test_waypoint_search_finds_non_shortest_branch_and_excludes_other():
    graph = branch_graph([(0, 1), (0, 2), (1, 3), (2, 3), (3, 4)], [4])
    result = discover_round_trips(request(waypoint_uid=2), graph=graph)
    assert len(result.routes) == 1
    assert result.routes[0].journey.route.legs[0].to_place == "2"


def test_return_counts_locks_and_directional_bridges_and_days():
    graph = branch_graph([(0, 1), (1, 2)], [2])
    graph.edges[0, 1]["locks"] = 1
    graph.nodes[0]["movable_bridge_ids"] = ("start-bridge",)
    graph.nodes[2]["movable_bridge_ids"] = ("turn-bridge",)
    result = discover_round_trips(request(), graph=graph).routes[0]
    assert result.journey.route.total_locks == 2
    assert result.journey.route.total_minutes == 38
    assert len(result.journey.locks) == 2
    assert result.budget.used_minutes == 38
    assert sum(d.cruising_minutes for d in result.journey.route.days) == 38
    assert result.journey.day_geometries[0].geometry == result.journey.geometry


def test_exact_override_selects_branch_and_stale_constraints_rejected():
    graph = branch_graph([(0, 1), (0, 2), (1, 3), (2, 3)], [3])
    body = request()
    collection = discover_round_trips(body, graph=graph)
    selected = collection.routes[-1]
    override = OutAndBackRouteRequest(
        **body.model_dump(), request_id=collection.request_id, route_id=selected.route_id
    )
    assert plan_out_and_back(override, graph=graph).journey == selected.journey
    changed = override.model_copy(update={"days": 2})
    with pytest.raises(RoundTripError, match="changed") as error:
        plan_out_and_back(changed, graph=graph)
    assert error.value.code == "stale_route_selection"


@pytest.mark.parametrize("kwargs", [dict(max_work=1), dict(max_routes=1), dict(max_vertices=1)])
def test_caps_never_return_partial_success(kwargs):
    graph = branch_graph([(0, 1), (0, 2)], [1, 2])
    with pytest.raises(RoundTripError) as error:
        discover_round_trips(request(), graph=graph, **kwargs)
    assert error.value.code == "candidate_search_limit"


def test_missing_index_and_empty_index_are_distinct():
    graph = branch_graph([(0, 1)], [])
    with pytest.raises(RoundTripError) as error:
        discover_round_trips(request(), graph=graph)
    assert error.value.code == "no_turnaround_candidates"
    del graph.graph["turnarounds"]
    with pytest.raises(RoundTripError) as error:
        discover_round_trips(request(), graph=graph)
    assert error.value.code == "turnarounds_unavailable"


def test_known_turning_limit_requires_dimension_but_unknown_does_not():
    graph = branch_graph([(0, 1), (0, 2)], [1, 2])
    graph.graph["turnarounds"][0]["turning_limits"] = {"boat_length_m": 12}
    result = discover_round_trips(request(), graph=graph)
    assert [r.turnaround.node_uid for r in result.routes] == [2]
    assert result.rejections[0].code == "turning_dimension_required"
    assert len(discover_round_trips(request(boat_length_m=10), graph=graph).routes) == 2


def test_fractional_budget_and_indivisible_leg():
    graph = branch_graph([(0, 1)], [1])
    graph.edges[0, 1]["length_m"] = 80 * 30.1
    with pytest.raises(RoundTripError) as error:
        discover_round_trips(request(), graph=graph)
    assert error.value.code == "no_feasible_turnaround"
    graph.edges[0, 1]["length_m"] = 80 * 30
    assert discover_round_trips(request(), graph=graph).routes[0].budget.remaining_minutes == 0


def test_request_validation_and_override_pair():
    with pytest.raises(ValidationError):
        TurnaroundCandidatesRequest(artifact_revision="r", start_uid=1)
    with pytest.raises(ValidationError):
        request(unknown=True)
    with pytest.raises(ValidationError):
        OutAndBackRouteRequest(**request().model_dump(), route_id="without-request")


def test_cyclic_zero_cost_graph_has_all_simple_routes_without_repeating_vertices():
    graph = branch_graph([(0, 1), (0, 2), (1, 2), (1, 3), (2, 3)], [3])
    for _, _, edge in graph.edges(data=True):
        edge["length_m"] = 0
    result = discover_round_trips(request(), graph=graph)
    assert len(result.routes) == 4
    for route in result.routes:
        legs = route.journey.route.legs
        outward = legs[: len(legs) // 2]
        nodes = [outward[0].from_place, *(leg.to_place for leg in outward)]
        assert len(nodes) == len(set(nodes))


def test_boat_access_filter_and_traversed_only_unknown_dimension_warnings():
    graph = branch_graph([(0, 1), (0, 2), (0, 3)], [1, 2, 3])
    graph.edges[0, 1]["dimensions"] = WayDimensions(max_beam_m=3)
    graph.edges[0, 2]["dimensions"] = WayDimensions(max_beam_m=1)
    graph.edges[0, 3]["tags"] = {"boat": "private"}
    result = discover_round_trips(request(boat_beam_m=2), graph=graph)
    assert [route.turnaround.node_uid for route in result.routes] == [1]
    assert not any("unknown" in w for w in result.routes[0].journey.route.warnings)


def test_day_geometry_covers_conservative_schedule_on_both_traversals():
    graph = branch_graph([(0, 1), (1, 2)], [2])
    for _, _, edge in graph.edges(data=True):
        edge["length_m"] = 80 * 20.1
    body = request().model_copy(update={"days": 4, "hours_per_day": 0.5})
    journey = discover_round_trips(body, graph=graph).routes[0]
    assert journey.budget.days_used == 4
    assert len(journey.journey.day_geometries) == 4
    assert all(d.cruising_minutes == 20 for d in journey.journey.route.days)
    assert journey.journey.day_geometries[-1].end == journey.journey.day_geometries[0].start


def test_oversized_single_traversal_cannot_be_folded_into_last_day():
    graph = branch_graph([(0, 1)], [1])
    graph.edges[0, 1]["length_m"] = 80 * 61
    body = request().model_copy(update={"days": 3})
    with pytest.raises(RoundTripError) as error:
        discover_round_trips(body, graph=graph)
    assert error.value.code == "no_feasible_turnaround"
    assert error.value.rejections[0].code == "budget_exceeded"


def test_null_bridge_delay_and_explicit_default_share_identity():
    graph = branch_graph([(0, 1)], [1])
    first = discover_round_trips(request(), graph=graph)
    second = discover_round_trips(request(movable_bridge_delay_min=5), graph=graph)
    assert first == second


def test_branch_choices_have_user_facing_names():
    graph = branch_graph([(0, 1), (1, 2), (1, 3)], [2, 3])
    graph.nodes[1]["name"] = "Canal junction"
    graph.edges[1, 2]["name"] = "North canal"
    graph.edges[1, 3]["name"] = "South canal"
    routes = discover_round_trips(request(), graph=graph).routes
    assert {r.branch_choices[0].continuation_name for r in routes} == {"North canal", "South canal"}
    assert all(r.branch_choices[0].junction_name == "Canal junction" for r in routes)
