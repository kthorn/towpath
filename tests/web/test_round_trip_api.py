import copy
from typing import cast
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pound.schemas import OutAndBackRouteRequest, TurnaroundCandidatesRequest
from pound.web.api import (
    OutAndBackRouteRequest as WebOutAndBackRouteRequest,
)
from pound.web.api import (
    TurnaroundCandidatesRequest as WebTurnaroundCandidatesRequest,
)


def _request(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "artifact_revision": "revision-test",
        "start_uid": 1,
        "days": 3,
        "hours_per_day": 6,
    }
    payload.update(changes)
    return payload


def _install_turnarounds(web_client: TestClient) -> None:
    graph = web_client.app.state.graph
    graph.graph["turnarounds"] = [
        {
            "turnaround_id": "fixture:middle",
            "kind": "winding_hole",
            "node_uid": 2,
            "coordinate": {"lat": 51.001, "lon": -1.001},
            "display_name": "Middle Hole",
            "eligibility_basis": "mapped_winding_hole",
            "sources": [],
            "turning_limits": {},
        },
        {
            "turnaround_id": "fixture:end",
            "kind": "junction",
            "node_uid": 3,
            "coordinate": {"lat": 51.002, "lon": -1.002},
            "display_name": "End Junction",
            "eligibility_basis": "junction_assumption",
            "sources": [],
            "turning_limits": {},
        },
    ]


def test_round_trip_http_models_are_shared_schema_contracts():
    assert WebTurnaroundCandidatesRequest is TurnaroundCandidatesRequest
    assert WebOutAndBackRouteRequest is OutAndBackRouteRequest


@pytest.mark.parametrize(
    "field",
    ["artifact_revision", "start_uid", "days"],
)
def test_turnaround_candidates_requires_core_fields(web_client: TestClient, field: str):
    payload = _request()
    del payload[field]

    response = web_client.post("/api/turnaround-candidates", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "change",
    [
        {"days": 0},
        {"hours_per_day": 0},
        {"hours_per_day": "Infinity"},
        {"boat_length_m": 0},
        {"movable_bridge_delay_min": -1},
        {"unexpected": True},
        {"start_uid": "1"},
    ],
)
def test_turnaround_candidates_rejects_invalid_constraints(
    web_client: TestClient, change: dict[str, object]
):
    assert web_client.post("/api/turnaround-candidates", json=_request(**change)).status_code == 422


def test_turnaround_candidates_checks_revision_before_handles(web_client: TestClient):
    response = web_client.post(
        "/api/turnaround-candidates",
        json=_request(artifact_revision="stale", start_uid=999),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "artifact_revision_mismatch",
        "message": "The routing artifact has changed; refresh turnaround candidates.",
        "fields": ["artifact_revision"],
    }


def test_turnaround_candidates_reports_unknown_handle_after_revision_check(web_client: TestClient):
    _install_turnarounds(web_client)

    response = web_client.post(
        "/api/turnaround-candidates",
        json=_request(start_uid=999),
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_node_handle"
    assert response.json()["detail"]["fields"] == ["start_uid"]


def test_turnaround_candidates_returns_complete_ordered_collection(web_client: TestClient):
    _install_turnarounds(web_client)

    response = web_client.post("/api/turnaround-candidates", json=_request())

    assert response.status_code == 200
    body = response.json()
    assert body["artifact_revision"] == "revision-test"
    assert body["default_route_id"] == body["routes"][0]["route_id"]
    assert [route["turnaround"]["turnaround_id"] for route in body["routes"]] == [
        "fixture:end"
    ]
    route = body["routes"][0]
    assert route["journey_type"] == "out_and_back"
    assert route["journey"]["route"]["start"] == route["journey"]["route"]["end"]
    assert route["journey"]["route"]["is_ring"] is False


def test_out_and_back_route_replays_the_exact_discovered_route(web_client: TestClient):
    _install_turnarounds(web_client)
    discovery = web_client.post("/api/turnaround-candidates", json=_request()).json()
    selected = discovery["routes"][0]
    before = copy.deepcopy(web_client.app.state.graph)

    response = web_client.post(
        "/api/out-and-back-route",
        json=_request(route_id=selected["route_id"], request_id=discovery["request_id"]),
    )

    assert response.status_code == 200
    assert response.json() == selected | {"selection_basis": "user_selected"}
    assert web_client.app.state.graph.graph == before.graph
    assert dict(web_client.app.state.graph.nodes(data=True)) == dict(before.nodes(data=True))
    assert list(web_client.app.state.graph.edges(data=True)) == list(before.edges(data=True))


def test_out_and_back_route_requires_route_and_request_ids_together(web_client: TestClient):
    response = web_client.post(
        "/api/out-and-back-route",
        json=_request(route_id="route-1"),
    )

    assert response.status_code == 422


def test_out_and_back_route_checks_revision_before_handles(web_client: TestClient):
    response = web_client.post(
        "/api/out-and-back-route",
        json=_request(artifact_revision="stale", start_uid=999),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "artifact_revision_mismatch"


def test_round_trip_services_receive_typed_body_and_loaded_graph(web_client: TestClient):
    _install_turnarounds(web_client)
    app = cast(FastAPI, web_client.app)

    with patch(
        "pound.web.api.discover_round_trips",
        wraps=__import__("pound.route.round_trip", fromlist=["discover_round_trips"])
        .discover_round_trips,
    ) as discover:
        response = web_client.post("/api/turnaround-candidates", json=_request())

    assert response.status_code == 200
    discover.assert_called_once()
    body = discover.call_args.args[0]
    assert isinstance(body, TurnaroundCandidatesRequest)
    assert body.artifact_revision == "revision-test"
    assert discover.call_args.kwargs == {
        "graph": app.state.graph,
        "max_work": app.state.settings.round_trip_max_work,
        "max_routes": app.state.settings.round_trip_max_routes,
        "max_vertices": app.state.settings.round_trip_max_vertices,
    }


def test_round_trip_error_is_returned_in_structured_envelope(web_client: TestClient):
    from pound.route.round_trip import RoundTripError

    failure = RoundTripError(
        code="no_feasible_turnaround",
        message="No feasible turnaround was found.",
        fields=["days"],
        rejections=[{"code": "budget_exceeded", "turnaround_id": "wh:2"}],
        status=422,
    )
    with patch("pound.web.api.discover_round_trips", side_effect=failure):
        response = web_client.post("/api/turnaround-candidates", json=_request())

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "no_feasible_turnaround",
        "message": "No feasible turnaround was found.",
        "fields": ["days"],
        "rejections": [{"code": "budget_exceeded", "turnaround_id": "wh:2"}],
    }
