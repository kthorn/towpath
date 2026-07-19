from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from pound.web.api import CanalRouteRequest


def _request(**changes):
    payload = {
        "start_uid": 1,
        "end_uid": 3,
        "artifact_revision": "revision-test",
        "hours_per_day": 6,
    }
    payload.update(changes)
    return payload


def test_route_http_model_has_contract_name():
    assert CanalRouteRequest.__name__ == "CanalRouteRequest"


def test_route_returns_geojson_and_route(web_client: TestClient):
    response = web_client.post("/api/canal-route", json=_request())

    assert response.status_code == 200
    assert response.json()["geometry"] == {
        "type": "LineString",
        "coordinates": [[-1.0, 51.0], [-1.001, 51.001], [-1.002, 51.002]],
    }
    assert response.json()["route"]["start"] == "Start"
    assert response.json()["route"]["end"] == "End"


@pytest.mark.parametrize(
    "changes",
    [
        {"start_uid": "one"},
        {"end_uid": None},
        {"days": 0},
        {"hours_per_day": 0},
        {"allow_derelict": False},
    ],
)
def test_route_leaves_body_type_errors_as_422(web_client: TestClient, changes: dict):
    assert web_client.post("/api/canal-route", json=_request(**changes)).status_code == 422


@pytest.mark.parametrize(
    "changes",
    [
        {"start_uid": "1"},
        {"end_uid": "3"},
        {"start_uid": True},
        {"hours_per_day": "6"},
        {"artifact_revision": 123},
    ],
)
def test_route_rejects_coercible_wrong_json_types(web_client: TestClient, changes: dict):
    assert web_client.post("/api/canal-route", json=_request(**changes)).status_code == 422


@pytest.mark.parametrize(
    "field", ["boat_length_m", "boat_beam_m", "boat_draft_m", "boat_height_m"]
)
@pytest.mark.parametrize("value", [0, -0.1])
def test_route_rejects_nonpositive_boat_dimensions(
    web_client: TestClient, field: str, value: float
):
    assert web_client.post("/api/canal-route", json=_request(**{field: value})).status_code == 422


def test_route_rejects_syntactically_malformed_json(web_client: TestClient):
    response = web_client.post(
        "/api/canal-route", content="{", headers={"content-type": "application/json"}
    )

    assert response.status_code == 422


def test_route_requires_exact_request_fields(web_client: TestClient):
    for field in ("start_uid", "end_uid", "artifact_revision"):
        payload = _request()
        del payload[field]
        assert web_client.post("/api/canal-route", json=payload).status_code == 422


def test_route_checks_revision_before_node_handles(web_client: TestClient):
    response = web_client.post(
        "/api/canal-route",
        json=_request(start_uid=999, end_uid=998, artifact_revision="stale"),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "artifact_revision_mismatch",
        "message": "The routing artifact has changed; refresh canal candidates.",
        "fields": ["artifact_revision"],
    }


@pytest.mark.parametrize(
    ("start_uid", "end_uid", "fields"),
    [
        (999, 3, ["start_uid"]),
        (1, 999, ["end_uid"]),
        (999, 998, ["start_uid", "end_uid"]),
        (999, 999, ["start_uid", "end_uid"]),
    ],
)
def test_route_collects_invalid_semantic_handles(
    web_client: TestClient, start_uid: int, end_uid: int, fields: list[str]
):
    response = web_client.post(
        "/api/canal-route", json=_request(start_uid=start_uid, end_uid=end_uid)
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "invalid_node_handle",
        "message": "One or more canal node handles do not exist.",
        "fields": fields,
    }


def test_route_same_existing_handle_is_valid(web_client: TestClient):
    response = web_client.post("/api/canal-route", json=_request(end_uid=1))

    assert response.status_code == 200
    assert response.json()["geometry"]["coordinates"] == [[-1.0, 51.0], [-1.0, 51.0]]


def test_route_calls_planner_once_with_resolved_constraints(web_client: TestClient):
    with patch("pound.web.api.plan_canal_route", wraps=__import__(
        "pound.route.plan", fromlist=["plan_canal_route"]
    ).plan_canal_route) as planner:
        response = web_client.post(
            "/api/canal-route",
            json=_request(days=2, boat_length_m=20, boat_beam_m=2.5),
        )

    assert response.status_code == 200
    planner.assert_called_once()
    constraints = planner.call_args.args[0]
    assert constraints.model_dump() == {
        "start_uid": 1,
        "end_uid": 3,
        "days": 2,
        "hours_per_day": 6.0,
        "boat_length_m": 20.0,
        "boat_beam_m": 2.5,
        "boat_draft_m": None,
        "boat_height_m": None,
    }


@pytest.mark.parametrize(
    ("changes", "message_fragment"),
    [
        ({"end_uid": 4}, "graph is not connected"),
        ({"boat_beam_m": 4}, "meets the boat's dimensions"),
    ],
)
def test_known_unavailable_routes_are_structured_422(
    web_client: TestClient, changes: dict, message_fragment: str
):
    response = web_client.post("/api/canal-route", json=_request(**changes))

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "route_unavailable"
    assert message_fragment in detail["message"]
    assert detail["fields"] == []


def test_route_does_not_swallow_programming_errors(web_client: TestClient):
    with patch("pound.web.api.plan_canal_route", side_effect=RuntimeError("bug")):
        with pytest.raises(RuntimeError, match="bug"):
            web_client.post("/api/canal-route", json=_request())


def test_route_does_not_treat_generic_value_error_as_unavailable(web_client: TestClient):
    with patch("pound.web.api.plan_canal_route", side_effect=ValueError("bad artifact data")):
        with pytest.raises(ValueError, match="bad artifact data"):
            web_client.post("/api/canal-route", json=_request())
