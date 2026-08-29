from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pound.web.app import create_app


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

    monkeypatch.setattr("pound.web.api.prepare_network_geometry", fail)
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/canal-network", json=_network_request())
        route_response = client.post(
            "/api/canal-route",
            json={
                "start_uid": 1,
                "end_uid": 3,
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
