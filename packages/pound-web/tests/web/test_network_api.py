from typing import cast

import pytest  # pyright: ignore[reportMissingImports]
from fastapi import FastAPI  # pyright: ignore[reportMissingImports]
from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]
from pound_web.app import create_app


def _network_request(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {"days": 7, "hours_per_day": 6}
    payload.update(changes)
    return payload


def test_network_post_returns_lines_and_ordered_bases(web_client: TestClient):
    response = web_client.post("/api/canal-network", json=_network_request())

    assert response.status_code == 200
    assert response.json()["bases"] == [
        {
            "identity": "test-provider/base:test",
            "operator": "test-provider",
            "name": "base:test",
            "coordinate": {"lat": 51.0, "lon": -1.0},
        }
    ]
    assert response.json()["lines"]
    assert response.json()["highlight_lines"] == []


def test_selected_base_returns_union_and_focused_lines(web_client: TestClient):
    baseline = web_client.post("/api/canal-network", json=_network_request()).json()
    response = web_client.post(
        "/api/canal-network",
        json=_network_request(selected_base_identity="test-provider/base:test"),
    )

    assert response.status_code == 200
    assert response.json()["lines"] == baseline["lines"]
    assert response.json()["highlight_lines"]


def test_unknown_selected_base_is_structured_422(web_client: TestClient):
    response = web_client.post(
        "/api/canal-network",
        json=_network_request(selected_base_identity="missing/base"),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "selected_base_not_found"
    assert response.json()["detail"]["fields"] == ["selected_base_identity"]


@pytest.mark.parametrize("selected_base_identity", ["", 1])
def test_invalid_selected_base_is_request_validation_422(
    web_client: TestClient, selected_base_identity: object
):
    response = web_client.post(
        "/api/canal-network",
        json=_network_request(selected_base_identity=selected_base_identity),
    )

    assert response.status_code == 422
    assert any(
        error["loc"] == ["body", "selected_base_identity"] for error in response.json()["detail"]
    )


def test_ineligible_selected_base_returns_empty_highlight(web_client: TestClient):
    response = web_client.post(
        "/api/canal-network",
        json=_network_request(
            selected_base_identity="test-provider/base:test",
            boat_beam_m=99,
        ),
    )

    assert response.status_code == 200
    assert response.json()["highlight_lines"] == []


def test_unknown_selected_base_does_not_override_network_unavailable(
    web_client: TestClient,
):
    app = cast(FastAPI, web_client.app)
    app.state.network_unavailable = True
    response = web_client.post(
        "/api/canal-network",
        json=_network_request(selected_base_identity="missing/base"),
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "network_unavailable"


def test_unknown_selected_base_does_not_override_network_budget(web_client: TestClient):
    response = web_client.post(
        "/api/canal-network",
        json=_network_request(
            selected_base_identity="missing/base",
            days=8,
            hours_per_day=24,
        ),
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "network_query_budget_exceeded"


def test_network_omits_unturnable_terminal_reach_but_keeps_base_marker(
    web_client: TestClient,
):
    response = web_client.post("/api/canal-network", json=_network_request())

    assert response.status_code == 200
    coordinates = [
        coordinate for line in response.json()["lines"] for coordinate in line["coordinates"]
    ]
    assert [-1.0, 51.0] in coordinates
    assert [-1.002, 51.002] not in coordinates
    assert response.json()["bases"]


def test_network_uses_half_the_schedule_as_outward_return_trip_reach(
    web_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    captured: dict[str, object] = {}

    def select(graph, _anchors, **kwargs):
        captured.update(kwargs)
        return graph.edge_subgraph(())

    monkeypatch.setattr("pound_web.api.select_boat_hire_reachability", select)

    response = web_client.post("/api/canal-network", json=_network_request())

    assert response.status_code == 200
    assert captured["cutoff_min"] == 7 * 6 * 60 / 2


def test_network_query_over_168_hours_is_rejected(web_client: TestClient):
    response = web_client.post(
        "/api/canal-network",
        json={**_network_request(), "days": 8, "hours_per_day": 24},
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "network_query_budget_exceeded"
    assert response.json()["detail"]["fields"] == ["days", "hours_per_day"]


def test_no_eligible_anchor_returns_empty_lines_but_bases(web_client: TestClient):
    response = web_client.post(
        "/api/canal-network",
        json={**_network_request(), "boat_beam_m": 99},
    )

    assert response.status_code == 200
    assert response.json()["lines"] == []
    assert response.json()["bases"]


def test_network_request_requires_hours_per_day(web_client: TestClient):
    response = web_client.post("/api/canal-network", json={"days": 7})

    assert response.status_code == 422
    assert any(error["loc"] == ["body", "hours_per_day"] for error in response.json()["detail"])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("days", 0),
        ("days", 366),
        ("hours_per_day", 0),
        ("hours_per_day", 25),
    ],
)
def test_network_request_rejects_schedule_outside_field_bounds(
    web_client: TestClient, field: str, value: int
):
    response = web_client.post(
        "/api/canal-network",
        json={**_network_request(), field: value},
    )

    assert response.status_code == 422


def test_network_geometry_failure_is_nonfatal_to_routing(
    web_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    settings = cast(FastAPI, web_client.app).state.settings

    def fail(_graph):
        raise ValueError("network geometry failed")

    monkeypatch.setattr("pound_web.api.prepare_network_geometry", fail)
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/canal-network", json=_network_request())
        route_response = client.post(
            "/api/canal-route",
            json={
                "start": {"edge": [1, 2], "fraction": 0},
                "end": {"edge": [2, 3], "fraction": 1},
                "artifact_revision": "revision-test",
                "hours_per_day": 6,
            },
        )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "network_unavailable",
        "message": "The canal network overlay is unavailable.",
        "fields": [],
    }
    assert route_response.status_code == 200
