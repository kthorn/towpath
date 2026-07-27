from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pound.web.app import create_app


def test_returns_prepared_network_with_artifact_revision(web_client: TestClient):
    response = web_client.get("/api/canal-network")

    assert response.status_code == 200
    body = response.json()
    assert body["artifact_revision"] == "revision-test"
    assert body["lines"]
    assert all(line["type"] == "LineString" for line in body["lines"])


def test_network_startup_failure_is_nonfatal(web_client: TestClient, monkeypatch):
    settings = cast(FastAPI, web_client.app).state.settings

    def fail(_graph):
        raise ValueError("network geometry failed")

    monkeypatch.setattr("pound.web.app.prepare_network_geometry", fail)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/canal-network")
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
    assert response.json()["detail"]["code"] == "network_unavailable"
    assert route_response.status_code == 200
