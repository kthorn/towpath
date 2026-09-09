"""Out-and-back endpoint positions follow the compact routing handle contract."""

import copy

import networkx as nx
import pytest
from pound.models import WayDimensions
from pound.route.project import project_handle
from pound.route.round_trip import RoundTripError, discover_round_trips, plan_out_and_back
from pound.schemas import CanalPointHandle, OutAndBackRouteRequest, TurnaroundCandidatesRequest


def graph_fixture():
    graph = nx.Graph(turnarounds=[])
    for uid in range(3):
        graph.add_node(uid, lat=51, lon=-1 + uid * 0.01, movable_bridge_ids=())
    for u, v in ((0, 1), (1, 2)):
        graph.add_edge(
            u,
            v,
            length_m=800,
            locks=0,
            dimensions=WayDimensions(),
            osm_way_id=1,
            kind="canal",
            name="Canal",
            candidate_eligible=True,
            geometry=[(51, -1 + u * 0.01), (51, -1 + v * 0.01)],
            movable_bridge_ids=(),
            tunnel_restrictions=(),
            access_caveats=(),
        )
    for uid in (0, 2):
        graph.graph["turnarounds"].append(
            dict(
                turnaround_id=f"test:{uid}",
                kind="winding_hole",
                node_uid=uid,
                coordinate=dict(lat=51, lon=-1 + uid * 0.01),
                display_name=f"Hole {uid}",
                eligibility_basis="mapped_winding_hole",
                sources=[],
                turning_limits={},
            )
        )
    return graph


def test_projected_start_retraces_exact_position_and_replays_without_mutation():
    graph = graph_fixture()
    before = copy.deepcopy(graph)
    start = CanalPointHandle(edge=(0, 1), fraction=0.25)
    request = TurnaroundCandidatesRequest(artifact_revision="test", start=start, days=1)
    result = discover_round_trips(request, graph=graph)
    assert len(result.routes) == 2
    assert result.routes[0].outbound_distance_km == pytest.approx(1.4)
    point = project_handle(start, graph).coordinate
    for route in result.routes:
        coords = route.journey.geometry.coordinates
        assert coords[0] == coords[-1] == (point.lon, point.lat)
    chosen = result.routes[-1]
    replay = plan_out_and_back(
        OutAndBackRouteRequest(
            **request.model_dump(), request_id=result.request_id, route_id=chosen.route_id
        ),
        graph=graph,
    )
    assert replay.journey == chosen.journey
    assert nx.utils.graphs_equal(graph, before)


def test_waypoint_on_same_edge_keeps_only_branch_that_visits_it():
    graph = graph_fixture()
    result = discover_round_trips(
        TurnaroundCandidatesRequest(
            artifact_revision="test",
            start=CanalPointHandle(edge=(0, 1), fraction=0.25),
            waypoint=CanalPointHandle(edge=(0, 1), fraction=0.75),
            days=1,
        ),
        graph=graph,
    )
    assert [r.turnaround.node_uid for r in result.routes] == [2]


def test_infrastructure_interior_handle_is_rejected():
    graph = graph_fixture()
    graph.edges[0, 1]["candidate_eligible"] = False
    with pytest.raises(RoundTripError) as error:
        discover_round_trips(
            TurnaroundCandidatesRequest(
                artifact_revision="test", start=CanalPointHandle(edge=(0, 1), fraction=0.5), days=1
            ),
            graph=graph,
        )
    assert error.value.status == 400
    assert error.value.fields == ["start"]


def test_long_compact_edge_can_be_split_across_cruising_days():
    graph = graph_fixture()
    graph.remove_node(2)
    graph.nodes[1]["lon"] = -0.9
    graph.edges[0, 1]["geometry"] = [(51, -1), (51, -0.9)]
    graph.edges[0, 1]["length_m"] = 6000
    graph.graph["turnarounds"] = [
        {
            **graph.graph["turnarounds"][0],
            "node_uid": 1,
            "coordinate": {"lat": 51, "lon": -0.9},
            "turnaround_id": "test:1",
        }
    ]
    result = discover_round_trips(
        TurnaroundCandidatesRequest(
            artifact_revision="test",
            start=CanalPointHandle(edge=(0, 1), fraction=0),
            days=3,
            hours_per_day=1,
        ),
        graph=graph,
    )
    assert len(result.routes) == 1
    journey = result.routes[0].journey
    assert journey.route.total_km == pytest.approx(12)
    assert len(journey.route.days) <= 3
    assert all(day.cruising_minutes <= 60 for day in journey.route.days)
    assert journey.geometry.coordinates[0] == journey.geometry.coordinates[-1]
