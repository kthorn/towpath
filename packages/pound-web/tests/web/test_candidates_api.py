from pathlib import Path
from typing import cast
from unittest.mock import patch

import networkx as nx
from fastapi import FastAPI  # pyright: ignore[reportMissingImports]
from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]
from pound_web.api import CanalCandidatesRequest
from pound_web.app import create_app
from pound_web.config import WebSettings

from .conftest import artifact_metadata, write_boat_hire_enrichment
from .fixtures import write_runtime_artifact as save_artifact


def test_candidate_http_model_has_contract_name():
    assert CanalCandidatesRequest.__name__ == "CanalCandidatesRequest"


def test_candidates_returns_projected_points_with_revision(web_client: TestClient):
    response = web_client.post("/api/canal-candidates", json={"lat": 51.0, "lon": -1.0})

    assert response.status_code == 200
    body = response.json()
    assert body["artifact_revision"] == "revision-test"
    assert [candidate["candidate_id"] for candidate in body["candidates"]] == [
        "1:2:0.000000000000",
        "2:3:1.000000000000",
    ]
    assert body["candidates"][0] == {
        "candidate_id": "1:2:0.000000000000",
        "handle": {"edge": [1, 2], "fraction": 0.0},
        "coordinate": {"lat": 51.0, "lon": -1.0},
        "straight_line_distance_m": 0.0,
        "display_name": "Start",
    }
    assert all("uid" not in candidate for candidate in body["candidates"])
    assert all("artifact_revision" not in candidate for candidate in body["candidates"])


def test_candidates_uses_shared_index_and_runtime_ceilings(web_client: TestClient):
    app = cast(FastAPI, web_client.app)
    with patch("pound_web.api.nearest_candidates", return_value=[]) as nearest:
        response = web_client.post("/api/canal-candidates", json={"lat": 51, "lon": -1})

    assert response.status_code == 200
    nearest.assert_called_once_with(
        51.0,
        -1.0,
        app.state.candidate_index,
        limit=3,
    )


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
