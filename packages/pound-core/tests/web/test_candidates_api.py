from pathlib import Path
from typing import cast
from unittest.mock import patch

import networkx as nx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pound.web.api import CanalCandidatesRequest
from pound.web.app import create_app
from pound.web.config import WebSettings

from tests.fixtures import write_runtime_artifact as save_artifact
from tests.web.conftest import artifact_metadata, write_boat_hire_enrichment


def test_candidate_http_model_has_contract_name():
    assert CanalCandidatesRequest.__name__ == "CanalCandidatesRequest"


def test_candidates_returns_named_sorted_points_with_revision(web_client: TestClient):
    response = web_client.post("/api/canal-candidates", json={"lat": 51.0, "lon": -1.0})

    assert response.status_code == 200
    body = response.json()
    assert body["artifact_revision"] == "revision-test"
    assert [candidate["uid"] for candidate in body["candidates"]] == [1, 2]
    assert body["candidates"][0]["display_name"] == "Start"
    assert body["candidates"][0]["coordinate"] == {"lat": 51.0, "lon": -1.0}
    assert {candidate["artifact_revision"] for candidate in body["candidates"]} == {"revision-test"}


def test_candidates_uses_runtime_tuning(web_client: TestClient):
    app = cast(FastAPI, web_client.app)
    with (
        patch("pound.web.api.nearest_coord_candidates", return_value=[]) as nearest,
        patch("pound.web.api.select_spaced_candidates", return_value=[]) as spaced,
    ):
        response = web_client.post("/api/canal-candidates", json={"lat": 51, "lon": -1})

    assert response.status_code == 200
    nearest.assert_called_once_with(
        51.0,
        -1.0,
        app.state.graph,
        app.state.spatial_index,
        artifact_revision="revision-test",
        limit=3,
    )
    spaced.assert_called_once_with([], destination_limit=2, minimum_spacing_m=0)


def test_candidates_empty_graph_returns_empty_list(tmp_path: Path):
    artifact_path = tmp_path / "empty.pkl"
    save_artifact(nx.Graph(), [], artifact_path, artifact_metadata("empty-revision"))
    settings = WebSettings(
        artifact_path=artifact_path,
        static_dir=tmp_path / "static",
        boat_hire_enrichment_path=write_boat_hire_enrichment(
            tmp_path / "boat-hire.csv",
            rows=[
                {
                    "source_provider_id": "test-provider",
                    "location_id": "base:test",
                    "exclude": "true",
                }
            ],
        ),
    )

    with TestClient(create_app(settings)) as client:
        response = client.post("/api/canal-candidates", json={"lat": 0, "lon": 0})

    assert response.status_code == 200
    assert response.json() == {"artifact_revision": "empty-revision", "candidates": []}


def test_candidates_rejects_missing_coordinates(web_client: TestClient):
    response = web_client.post("/api/canal-candidates", json={"lat": 51})

    assert response.status_code == 422


def test_candidates_rejects_out_of_range_coordinates(web_client: TestClient):
    for payload in ({"lat": 91, "lon": 0}, {"lat": 0, "lon": -181}):
        assert web_client.post("/api/canal-candidates", json=payload).status_code == 422


def test_candidates_rejects_string_coordinates(web_client: TestClient):
    for payload in (
        {"lat": "51", "lon": -1},
        {"lat": 51, "lon": "-1"},
        {"lat": True, "lon": -1},
    ):
        assert web_client.post("/api/canal-candidates", json=payload).status_code == 422
