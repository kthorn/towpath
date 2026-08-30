from unittest.mock import patch

import pytest  # pyright: ignore[reportMissingImports]
from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]
from pound_web.api import CanalRouteRequest


def _request(**changes):
    payload = {
        "start": {"edge": [1, 2], "fraction": 0.0},
        "end": {"edge": [2, 3], "fraction": 1.0},
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
    assert response.json()["route"]["start"] == "First reach"
    assert response.json()["route"]["end"] == "Second reach"
    assert response.json()["route"]["access_segments"] == []


@pytest.mark.parametrize("changes", [{"start": "one"}, {"end": None}])
def test_route_rejects_malformed_handles_with_400(web_client: TestClient, changes: dict):
    assert web_client.post("/api/canal-route", json=_request(**changes)).status_code == 400


@pytest.mark.parametrize("changes", [{"days": 0}, {"hours_per_day": 0}, {"allow_derelict": False}])
def test_route_leaves_constraint_type_errors_as_422(web_client: TestClient, changes: dict):
    assert web_client.post("/api/canal-route", json=_request(**changes)).status_code == 422


@pytest.mark.parametrize(
    "changes",
    [
        {"start": {"edge": ["1", 2], "fraction": 0}},
        {"end": {"edge": [2, 3], "fraction": "1"}},
        {"hours_per_day": "6"},
        {"artifact_revision": 123},
    ],
)
def test_route_rejects_coercible_wrong_json_types(web_client: TestClient, changes: dict):
    expected_status = 400 if "start" in changes or "end" in changes else 422
    assert (
        web_client.post("/api/canal-route", json=_request(**changes)).status_code == expected_status
    )


@pytest.mark.parametrize("field", ["boat_length_m", "boat_beam_m", "boat_draft_m", "boat_height_m"])
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
    for field in ("start", "end", "artifact_revision"):
        payload = _request()
        del payload[field]
        assert web_client.post("/api/canal-route", json=payload).status_code == 422
    assert (
        web_client.post("/api/canal-route", json=_request(start_uid=1, end_uid=3)).status_code
        == 422
    )


def test_route_checks_revision_before_handles(web_client: TestClient):
    response = web_client.post(
        "/api/canal-route",
        json=_request(
            start={"edge": [999, 1000], "fraction": 0},
            end={"edge": [998, 999], "fraction": 0},
            artifact_revision="stale",
        ),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "artifact_revision_mismatch",
        "message": "The routing artifact has changed; refresh canal candidates.",
        "fields": ["artifact_revision"],
    }


@pytest.mark.parametrize(
    ("start", "end", "fields"),
    [
        ({"edge": [999, 1000], "fraction": 0}, _request()["end"], ["start"]),
        (_request()["start"], {"edge": [999, 1000], "fraction": 0}, ["end"]),
        (
            {"edge": [999, 1000], "fraction": 0},
            {"edge": [998, 999], "fraction": 0},
            ["start", "end"],
        ),
        (
            {"edge": [999, 1000], "fraction": 0},
            {"edge": [999, 1000], "fraction": 0},
            ["start", "end"],
        ),
    ],
)
def test_route_collects_invalid_semantic_handles(
    web_client: TestClient, start: dict, end: dict, fields: list[str]
):
    response = web_client.post("/api/canal-route", json=_request(start=start, end=end))

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "invalid_node_handle",
        "message": "One or more canal node handles do not exist.",
        "fields": fields,
    }


def test_route_same_existing_handle_is_valid(web_client: TestClient):
    response = web_client.post(
        "/api/canal-route",
        json=_request(end={"edge": [1, 2], "fraction": 0}),
    )

    assert response.status_code == 200
    assert response.json()["geometry"]["coordinates"] == [[-1.0, 51.0], [-1.0, 51.0]]


def test_route_calls_planner_once_with_resolved_constraints(web_client: TestClient):
    with patch(
        "pound_web.api.plan_projected_route",
        wraps=__import__(
            "pound.route.plan", fromlist=["plan_projected_route"]
        ).plan_projected_route,
    ) as planner:
        response = web_client.post(
            "/api/canal-route",
            json=_request(days=2, boat_length_m=20, boat_beam_m=2.5, movable_bridge_delay_min=0),
        )

    assert response.status_code == 200
    planner.assert_called_once()
    constraints = planner.call_args.args[0]
    assert constraints.start.edge == (1, 2)
    assert constraints.start.fraction == 0.0
    assert constraints.end.edge == (2, 3)
    assert constraints.end.fraction == 1.0
    assert constraints.days == 2
    assert constraints.hours_per_day == 6.0
    assert constraints.boat_length_m == 20.0
    assert constraints.boat_beam_m == 2.5
    assert constraints.movable_bridge_delay_min == 0.0


@pytest.mark.parametrize(
    ("changes", "message_fragment"),
    [
        ({"boat_beam_m": 4}, "no path between the selected canal points"),
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
    with patch("pound_web.api.plan_projected_route", side_effect=RuntimeError("bug")):
        with pytest.raises(RuntimeError, match="bug"):
            web_client.post("/api/canal-route", json=_request())


def test_route_does_not_treat_generic_value_error_as_unavailable(web_client: TestClient):
    with patch("pound_web.api.plan_projected_route", side_effect=ValueError("bad artifact data")):
        with pytest.raises(ValueError, match="bad artifact data"):
            web_client.post("/api/canal-route", json=_request())
