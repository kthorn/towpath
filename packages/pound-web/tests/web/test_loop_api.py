"""Loop discovery and exact replay are available to manual and tool clients."""

import copy
from types import SimpleNamespace

import pytest


def payload(**changes):
    return dict(artifact_revision="revision-test", start_uid=1, days=3, hours_per_day=6) | changes


def install_circuit(client):
    graph = client.app.state.graph
    data = copy.deepcopy(graph.edges[1, 2])
    data.update(
        length_m=80,
        locks=0,
        lock_points=(),
        movable_bridge_ids=(),
        geometry=[
            (graph.nodes[3]["lat"], graph.nodes[3]["lon"]),
            (graph.nodes[1]["lat"], graph.nodes[1]["lon"]),
        ],
    )
    graph.add_edge(3, 1, **data)
    graph.graph.pop("turnarounds", None)


def test_loop_candidates_returns_closed_previews_without_turnarounds(web_client):
    install_circuit(web_client)
    response = web_client.post("/api/loop-candidates", json=payload())
    assert response.status_code == 200
    result = response.json()
    assert len(result["routes"]) == 2
    assert result["default_route_id"] == result["routes"][0]["route_id"]
    for route in result["routes"]:
        assert route["journey_type"] == "loop"
        assert route["journey"]["route"]["is_ring"] is True
        assert route["connecting_distance_km"] == 0
        coordinates = route["journey"]["geometry"]["coordinates"]
        assert coordinates[0] == coordinates[-1]


def test_loop_route_replays_exact_selection(web_client):
    install_circuit(web_client)
    result = web_client.post("/api/loop-candidates", json=payload()).json()
    selected = result["routes"][-1]
    response = web_client.post(
        "/api/loop-route",
        json=payload(
            request_id=result["request_id"],
            route_id=selected["route_id"],
        ),
    )
    assert response.status_code == 200
    assert response.json() == selected | {"selection_basis": "user_selected"}
    response = web_client.post(
        "/api/loop-route",
        json=payload(
            days=4,
            request_id=result["request_id"],
            route_id=selected["route_id"],
        ),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_route_selection"


@pytest.mark.parametrize("endpoint", ["loop-candidates", "loop-route"])
def test_loop_revision_precedes_handle_validation(web_client, endpoint):
    response = web_client.post(
        f"/api/{endpoint}",
        json=payload(
            artifact_revision="stale",
            start_uid=999,
        ),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "artifact_revision_mismatch"


@pytest.mark.parametrize(
    "change",
    [
        {"days": 0},
        {"hours_per_day": 0},
        {"hours_per_day": "Infinity"},
        {"boat_length_m": -1},
        {"unexpected": True},
        {"start_uid": "1"},
    ],
)
def test_invalid_loop_constraints(web_client, change):
    assert web_client.post("/api/loop-candidates", json=payload(**change)).status_code == 422


def test_missing_visit_and_no_loop_have_actionable_errors(web_client):
    response = web_client.post("/api/loop-candidates", json=payload(waypoint_uid=999))
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_node_handle"
    response = web_client.post("/api/loop-candidates", json=payload())
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "no_feasible_loop"


def test_loop_search_limit_is_error_not_partial_collection(web_client):
    install_circuit(web_client)
    web_client.app.state.settings = SimpleNamespace(round_trip_max_routes=1)
    response = web_client.post("/api/loop-candidates", json=payload())
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "candidate_search_limit"
    assert "routes" not in response.json()


def test_loop_supports_projected_base_and_rejects_unpaired_selection(web_client):
    install_circuit(web_client)
    body = payload(start={"edge": [1, 2], "fraction": 0.5})
    del body["start_uid"]
    response = web_client.post("/api/loop-candidates", json=body)
    assert response.status_code == 200
    for route in response.json()["routes"]:
        assert route["journey"]["geometry"]["coordinates"][0] == pytest.approx([-1.0005, 51.0005])
    assert web_client.post("/api/loop-route", json=body | {"route_id": "test"}).status_code == 422
