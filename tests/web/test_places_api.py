from pathlib import Path
from typing import cast

import pytest  # pyright: ignore[reportMissingImports]
from fastapi import FastAPI  # pyright: ignore[reportMissingImports]
from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

from pound.graph.artifact import save_artifact
from pound.web.app import create_app
from pound.web.config import WebSettings
from tests.web.conftest import artifact_metadata, write_boat_hire_enrichment


def valid_viewport_payload(**changes):
    payload = {
        "mode": "viewport",
        "kinds": ["pub"],
        "bounds": {"south": 50.9, "west": -1.1, "north": 51.1, "east": -0.9},
        "route_geometry": {
            "type": "LineString",
            "coordinates": [[-1.1, 51.0], [-0.9, 51.0]],
        },
        "policy": {"basis": "route", "radius_m": 1_000},
    }
    payload.update(changes)
    return payload


def valid_nearby_payload(**changes):
    payload = {
        "mode": "nearby",
        "kinds": ["pub"],
        "radius_m": 2_000,
        "targets": [
            {
                "id": "stop",
                "geometry": {"type": "Point", "coordinates": [-1.001, 51.0]},
            }
        ],
    }
    payload.update(changes)
    return payload


def test_old_catalog_path_is_removed(web_client: TestClient):
    assert web_client.post("/api/catalog-places", json={}).status_code == 405


def test_places_returns_normalized_places_and_distances(web_client: TestClient):
    response = web_client.post("/api/places", json=valid_viewport_payload())

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"places"}
    assert body["places"][0]["kind"] == "pub"
    assert body["places"][0]["coordinate"] == {"lat": 51.0, "lon": -1.0}
    assert body["places"][0]["distance_to_full_route_m"] < 10
    assert body["places"][0]["provenance"]["source"] == "osm"
    assert body["places"][0]["provenance"]["osm_id"] == 201
    assert body["places"][0]["provenance"]["metadata"]["name"] == "pub 201"


def test_places_returns_nearby_point_target(web_client: TestClient):
    response = web_client.post("/api/places", json=valid_nearby_payload())

    assert response.status_code == 200
    place = response.json()["places"][0]
    assert place["target_id"] == "stop"
    assert place["distance_to_target_m"] > 0
    assert place["distance_to_full_route_m"] is None


def test_places_returns_nearby_linestring_target(web_client: TestClient):
    response = web_client.post(
        "/api/places",
        json=valid_nearby_payload(
            targets=[
                {
                    "id": "segment",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[-1.1, 51.001], [-0.9, 51.001]],
                    },
                }
            ]
        ),
    )

    assert response.status_code == 200
    place = response.json()["places"][0]
    assert place["target_id"] == "segment"
    assert place["distance_to_target_m"] == pytest.approx(111, abs=10)


def test_places_returns_structured_query_validation_errors(web_client: TestClient):
    response = web_client.post(
        "/api/places",
        json=valid_viewport_payload(text="x" * 257),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "invalid_places_query",
        "message": "Invalid places query.",
        "fields": ["viewport.text"],
    }


@pytest.mark.parametrize(
    "payload",
    [
        valid_viewport_payload(extra=True),
        valid_viewport_payload(kinds=[1]),
        valid_viewport_payload(bounds={"south": 52, "west": 0, "north": 50, "east": -2}),
        valid_viewport_payload(route_geometry=None),
        valid_viewport_payload(
            route_geometry=None,
            day_geometry={"type": "LineString", "coordinates": [[-1, 51], [-0.9, 51]]},
        ),
    ],
)
def test_places_rejects_invalid_viewport_payloads_with_structured_error(
    web_client: TestClient, payload: dict
):
    response = web_client.post("/api/places", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_places_query"


def test_places_rejects_unknown_kind_with_structured_error(web_client: TestClient):
    response = web_client.post("/api/places", json=valid_viewport_payload(kinds=["unknown"]))

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "invalid_places_query",
        "message": "Invalid places query.",
        "fields": ["viewport.kinds"],
    }


def test_places_rejects_nearby_invalid_target_with_structured_error(web_client: TestClient):
    response = web_client.post(
        "/api/places",
        json=valid_nearby_payload(
            targets=[
                {
                    "id": "stop",
                    "geometry": {"type": "LineString", "coordinates": [[-1.0, 51.0]]},
                }
            ]
        ),
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_places_query"


def test_places_query_budget_is_structured_413(web_client: TestClient, monkeypatch):
    app = cast(FastAPI, web_client.app)
    monkeypatch.setattr(app.state.places_index, "max_vertices", 1)
    response = web_client.post("/api/places", json=valid_viewport_payload())

    assert response.status_code == 413
    assert response.json()["detail"] == {
        "code": "places_query_budget_exceeded",
        "message": "The places query exceeds its configured budget.",
        "fields": ["route_geometry", "day_geometry"],
    }


def test_places_result_limit_is_structured_413(web_client: TestClient, monkeypatch):
    app = cast(FastAPI, web_client.app)
    monkeypatch.setattr(app.state.places_index, "max_results", 0)
    response = web_client.post("/api/places", json=valid_viewport_payload())

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "places_result_limit_exceeded"


def test_places_returns_503_without_catalog(client_without_catalog: TestClient):
    response = client_without_catalog.post("/api/places", json=valid_viewport_payload())

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "places_unavailable",
        "message": "Places are unavailable.",
        "fields": [],
    }


def test_places_never_exposes_catalog_revision(web_client: TestClient):
    response = web_client.post("/api/places", json=valid_viewport_payload())

    assert response.status_code == 200
    assert "catalog_revision" not in response.json()
    assert "catalog_revision" not in response.request.content.decode()


def test_places_returns_mixed_sources(web_client: TestClient):
    response = web_client.post(
        "/api/places",
        json=valid_viewport_payload(kinds=["pub", "boat_hire"]),
    )

    assert response.status_code == 200
    assert [place["provenance"]["source"] for place in response.json()["places"]] == [
        "osm",
        "boat_hire",
    ]


def test_configured_catalog_failure_reports_degraded_health(tmp_path: Path, route_graph):
    artifact_path = tmp_path / "graph.pkl"
    catalog_path = tmp_path / "missing-catalog.pkl"
    save_artifact(route_graph, [], artifact_path, artifact_metadata("route-only"))
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
        catalog_path=catalog_path,
    )

    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health").json() == {
            "status": "degraded",
            "artifact_revision": "route-only",
            "places_status": "unavailable",
        }
