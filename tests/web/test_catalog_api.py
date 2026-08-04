from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pound.catalog.spatial import CatalogSpatialIndex
from pound.graph.artifact import save_artifact
from pound.web.app import create_app
from pound.web.config import WebSettings
from tests.web.conftest import catalog_place


def _request(client: TestClient, **changes):
    payload = {
        "catalog_revision": client.app.state.catalog_revision,
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


def test_catalog_places_returns_normalized_places_and_distances(web_client: TestClient):
    response = web_client.post("/api/catalog-places", json=_request(web_client))

    assert response.status_code == 200
    body = response.json()
    assert body["catalog_revision"] == web_client.app.state.catalog_revision
    assert body["matching_count"] == 1
    assert body["over_cap"] is False
    assert body["day"] is None
    assert body["places"][0]["identity"] == "node/201/pub"
    assert body["places"][0]["coordinate"] == {"lat": 51.0, "lon": -1.0}
    assert body["places"][0]["distance_to_full_route_m"] < 10
    assert body["places"][0]["metadata"]["name"] == "pub 201"


def test_catalog_places_returns_segment_distance(web_client: TestClient):
    response = web_client.post(
        "/api/catalog-places",
        json=_request(
            web_client,
            route_geometry=None,
            segment_geometry={
                "type": "LineString",
                "coordinates": [[-1.1, 51.0], [-0.9, 51.0]],
            },
            policy={"basis": "segment", "radius_m": 2_000},
        ),
    )

    assert response.status_code == 200
    place = response.json()["places"][0]
    assert place["distance_to_segment_m"] == pytest.approx(0, abs=10)
    assert place["distance_to_full_route_m"] is None


@pytest.mark.parametrize(
    ("changes", "fields"),
    [
        ({"text": "x" * 257}, ["text"]),
        (
            {
                "route_geometry": None,
                "segment_geometry": {
                    "type": "LineString",
                    "coordinates": [["bad", 51.0], [-0.9, 51.0]],
                },
                "policy": {"basis": "segment", "radius_m": 2_000},
            },
            ["segment_geometry"],
        ),
        (
            {
                "route_geometry": None,
                "policy": {"basis": "segment", "radius_m": 2_000},
            },
            ["body"],
        ),
    ],
)
def test_catalog_places_returns_structured_query_validation_errors(
    web_client: TestClient,
    changes,
    fields,
):
    response = web_client.post(
        "/api/catalog-places",
        json=_request(web_client, **changes),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "invalid_catalog_query",
        "message": "Invalid catalog query.",
        "fields": fields,
    }


def test_catalog_places_returns_selected_day_context(web_client: TestClient):
    response = web_client.post(
        "/api/catalog-places",
        json=_request(
            web_client,
            day=2,
            day_geometry={
                "type": "LineString",
                "coordinates": [[-1.1, 51.002], [-0.9, 51.002]],
            },
        ),
    )

    assert response.status_code == 200
    assert response.json()["day"] == 2
    assert response.json()["places"][0]["distance_to_selected_geometry_m"] > 0


def test_catalog_places_rejects_unknown_kind_with_structured_error(web_client: TestClient):
    response = web_client.post("/api/catalog-places", json=_request(web_client, kinds=["unknown"]))

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_catalog_kind"
    assert response.json()["detail"]["fields"] == ["kinds"]


def test_catalog_places_rejects_invalid_bounds_with_structured_error(web_client: TestClient):
    response = web_client.post(
        "/api/catalog-places",
        json=_request(web_client, bounds={"south": 52, "west": 0, "north": 50, "east": -2}),
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_bounds"


def test_catalog_places_rejects_invalid_policy_with_structured_error(web_client: TestClient):
    response = web_client.post(
        "/api/catalog-places",
        json=_request(web_client, route_geometry=None),
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_catalog_policy"


def test_catalog_places_rejects_invalid_geometry_consistency(web_client: TestClient):
    response = web_client.post(
        "/api/catalog-places",
        json=_request(web_client, day=2),
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_catalog_geometry"


def test_catalog_places_rejects_strict_body_types_and_extra_fields(web_client: TestClient):
    for payload in (
        _request(web_client, extra=True),
        _request(web_client, kinds=[1]),
        _request(web_client, catalog_revision=123),
    ):
        response = web_client.post("/api/catalog-places", json=payload)
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "invalid_catalog_query"


def test_catalog_places_rejects_geometry_budget_with_structured_error(web_client: TestClient):
    response = web_client.post(
        "/api/catalog-places",
        json=_request(
            web_client,
            route_geometry={
                "type": "LineString",
                "coordinates": [[-1.0, 51.0], [-1.0, 51.0]] * 5_001,
            },
        ),
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "catalog_query_budget_exceeded"


def test_catalog_places_rejects_stale_revision(web_client: TestClient):
    response = web_client.post(
        "/api/catalog-places", json=_request(web_client, catalog_revision="stale")
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "catalog_revision_mismatch",
        "message": "The place catalog has changed; refresh catalog layers.",
        "fields": ["catalog_revision"],
    }


def test_catalog_places_returns_503_when_catalog_is_unavailable(tmp_path: Path, route_graph):
    artifact_path = tmp_path / "graph.pkl"
    save_artifact(
        route_graph,
        [],
        artifact_path,
        {
            "artifact_revision": "route-only",
            "source": "test",
            "fetched_at": "2026-07-11T00:00:00Z",
            "built_at": "2026-07-12T00:00:00Z",
            "validation": {},
            "poi_summary": {},
        },
    )
    settings = WebSettings(artifact_path=artifact_path, static_dir=tmp_path / "static")

    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/catalog-places",
            json={
                "catalog_revision": "none",
                "kinds": ["pub"],
                "bounds": {"south": 50, "west": -2, "north": 52, "east": 0},
                "policy": {"basis": "none", "radius_m": None},
            },
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "catalog_unavailable"


def test_catalog_places_returns_over_cap_without_partial_records(web_client: TestClient):
    client = cast(TestClient, web_client)
    app = cast(FastAPI, client.app)
    app.state.catalog_spatial_index = CatalogSpatialIndex(
        tuple(
            catalog_place("pub", index + 1, 51.0 + index * 0.000001, -1.0) for index in range(1001)
        ),
        app.state.spatial_index,
    )

    response = client.post("/api/catalog-places", json=_request(client))

    assert response.status_code == 200
    assert response.json()["places"] == []
    assert response.json()["matching_count"] == 1001
    assert response.json()["over_cap"] is True
