import copy

import networkx as nx
from pound.route.round_trip import discover_round_trips, plan_out_and_back

from pound.ingest.ir import WayDimensions
from pound.schemas import OutAndBackRouteRequest, TurnaroundCandidatesRequest


def _constraints(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "artifact_revision": "fixture-revision",
        "start_uid": 10,
        "waypoint_uid": 20,
        "days": 3,
        "hours_per_day": 6,
        "boat_length_m": 18,
        "boat_beam_m": 2.1,
        "boat_draft_m": 1.0,
        "boat_height_m": 3.0,
        "movable_bridge_delay_min": 4,
    }
    payload.update(changes)
    return payload


def _fake_tool_discover(payload: dict[str, object], graph: nx.Graph):
    return discover_round_trips(TurnaroundCandidatesRequest.model_validate(payload), graph=graph)


def _fake_tool_plan(payload: dict[str, object], graph: nx.Graph):
    return plan_out_and_back(OutAndBackRouteRequest.model_validate(payload), graph=graph)


def _branched_graph() -> nx.Graph:
    graph = nx.Graph(fetched_at="2026-09-05", turnarounds=[])
    for uid in range(4):
        graph.add_node(uid, lat=51 + uid * 0.001, lon=-1, name=str(uid), movable_bridge_ids=())
    for left, right in ((0, 1), (1, 2), (1, 3)):
        graph.add_edge(
            left,
            right,
            length_m=80,
            locks=0,
            dimensions=WayDimensions(),
            osm_way_id=left * 100 + right,
            name="Canal",
            kind="canal",
            geometry=[(graph.nodes[left]["lat"], -1), (graph.nodes[right]["lat"], -1)],
            movable_bridge_ids=(),
            tunnel_restrictions=(),
            access_caveats=(),
        )
    for uid in (2, 3):
        graph.graph["turnarounds"].append(
            {
                "turnaround_id": f"fixture:{uid}",
                "kind": "winding_hole",
                "node_uid": uid,
                "coordinate": {"lat": graph.nodes[uid]["lat"], "lon": -1},
                "display_name": f"Hole {uid}",
                "eligibility_basis": "mapped_winding_hole",
                "sources": [],
                "turning_limits": {},
            }
        )
    return graph


def test_fake_tool_request_uses_the_same_validated_discovery_contract():
    request = TurnaroundCandidatesRequest.model_validate(_constraints())

    assert request.model_dump() == _constraints()


def test_fake_tool_request_can_select_an_exact_discovered_route():
    request = OutAndBackRouteRequest.model_validate(
        _constraints(route_id="route-2", request_id="request-1")
    )

    assert request.route_id == "route-2"
    assert request.request_id == "request-1"
    assert request.start_uid == 10
    assert request.waypoint_uid == 20


def test_fake_tool_request_rejects_route_selection_without_discovery_identity():
    try:
        OutAndBackRouteRequest.model_validate(_constraints(route_id="route-2"))
    except ValueError as exc:
        assert "request_id" in str(exc)
    else:
        raise AssertionError("route selection without request identity was accepted")


def test_fake_tool_returns_every_branch_and_replays_the_selected_route():
    graph = _branched_graph()
    before = copy.deepcopy(graph)
    payload = {
        "artifact_revision": "fixture-revision",
        "start_uid": 0,
        "days": 1,
        "hours_per_day": 1,
    }

    candidates = _fake_tool_discover(payload, graph)
    selected = candidates.routes[-1]
    selected_payload = {
        **payload,
        "route_id": selected.route_id,
        "request_id": candidates.request_id,
    }
    route = _fake_tool_plan(selected_payload, graph)

    assert len(candidates.routes) == 2
    assert candidates.default_route_id == candidates.routes[0].route_id
    assert route.route_id == selected.route_id
    assert route.journey == selected.journey
    assert nx.utils.graphs_equal(graph, before)
