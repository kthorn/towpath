import json
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from .conftest import build_web_client


@pytest.fixture
def hire_client(tmp_path, route_graph) -> Generator[TestClient, None, None]:
    rows = [
        {
            "source_provider_id": "provider",
            "source_provider_name": "Canal Co",
            "source_provider_website": "https://provider.test",
            "location_id": "far",
            "location_name": "Far Base",
            "latitude": "51.003",
            "longitude": "-1.0",
            "booking_url": "https://provider.test/book/far",
            "evidence_url": "https://provider.test/evidence/far",
            "osm_url": "https://www.openstreetmap.org/node/2",
        },
        {
            "source_provider_id": "provider",
            "source_provider_name": "Canal Co",
            "source_provider_website": "https://provider.test",
            "location_id": "near",
            "location_name": "Near Base",
            "latitude": "51.001",
            "longitude": "-1.0",
            "booking_url": "https://provider.test/book/near",
            "evidence_url": "https://provider.test/evidence/near",
            "osm_url": "https://www.openstreetmap.org/node/1",
        },
        {
            "source_provider_id": "provider",
            "location_id": "review",
            "record_type": "review_positive",
            "latitude": "51.002",
            "longitude": "-1.0",
        },
    ]
    yield from build_web_client(tmp_path, route_graph, boat_hire_rows=rows)


def test_hire_bases_returns_public_bases_sorted_and_bounded(hire_client: TestClient):
    response = hire_client.post(
        "/api/hire-bases",
        json={"lat": 51.0, "lon": -1.0, "radius_km": 10, "limit": 1},
    )

    assert response.status_code == 200
    assert response.json() == {
        "artifact_revision": "revision-test",
        "total_matches": 2,
        "truncated": True,
        "next_offset": 1,
        "budget_minutes": None,
        "cutoff_minutes": None,
        "ranking_basis": "straight_line_distance",
        "bases": [
            {
                "base_ref": "provider/near",
                "name": "Near Base",
                "provider_name": "Canal Co",
                "provider_id": "provider",
                "coordinate": {"lat": 51.001, "lon": -1.0},
                "straight_line_distance_m": pytest.approx(111.2, abs=1.0),
                "one_way_minutes": None,
                "return_minutes": None,
                "handle": {"edge": [1, 2], "fraction": pytest.approx(0.7152, abs=0.001)},
                "canal_coordinate": {
                    "lat": pytest.approx(51.000715, abs=0.000001),
                    "lon": pytest.approx(-1.000715, abs=0.000001),
                },
                "snap_distance_m": pytest.approx(59.3, abs=1.0),
                "provider_url": "https://provider.test",
                "evidence_url": "https://provider.test/evidence/near",
                "booking_url": "https://provider.test/book/near",
            }
        ],
    }


def test_hire_bases_rejects_strict_invalid_values(hire_client: TestClient):
    for payload in (
        {"lat": "51", "lon": -1},
        {"lat": 51, "lon": -1, "limit": True},
        {"lat": 51, "lon": -1, "limit": 0},
        {"lat": 51, "lon": -1, "limit": 21},
        {"lat": 51, "lon": -1, "offset": -1},
        {"lat": 51, "lon": -1, "offset": 1001},
        {"lat": 51, "lon": -1, "radius_km": 0},
        {"lat": 51, "lon": -1, "radius_km": 251},
    ):
        response = hire_client.post("/api/hire-bases", json=payload)
        assert response.status_code == 422, payload

    response = hire_client.post(
        "/api/hire-bases",
        content=json.dumps({"lat": float("nan"), "lon": -1}),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422

    for field in ("hours_per_day", "movable_bridge_delay_min", "boat_beam_m"):
        response = hire_client.post(
            "/api/hire-bases",
            content=json.dumps({"lat": 51, "lon": -1, field: float("nan")}),
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 422, field


def test_hire_bases_offset_pages_after_distance_sort(hire_client: TestClient):
    response = hire_client.post(
        "/api/hire-bases",
        json={"lat": 51.0, "lon": -1.0, "radius_km": 10, "limit": 1, "offset": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_matches"] == 2
    assert body["truncated"] is False
    assert body["next_offset"] is None
    assert [base["base_ref"] for base in body["bases"]] == ["provider/far"]


def test_hire_bases_network_mode_ignores_radius_and_reports_route_costs(
    hire_client: TestClient,
):
    response = hire_client.post(
        "/api/hire-bases",
        json={
            "lat": 0.0,
            "lon": 0.0,
            "target": {"edge": [1, 2], "fraction": 0.0},
            "artifact_revision": "revision-test",
            "days": 1,
            "hours_per_day": 1.0,
            "limit": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ranking_basis"] == "canal_travel_time"
    assert body["budget_minutes"] == 60.0
    assert body["cutoff_minutes"] == 30.0
    assert body["total_matches"] == 2
    assert body["truncated"] is True
    assert body["bases"][0]["base_ref"] == "provider/near"
    assert body["bases"][0]["one_way_minutes"] is not None
    assert body["bases"][0]["return_minutes"] is not None


def test_hire_bases_network_mode_rejects_stale_artifact_revision(hire_client: TestClient):
    response = hire_client.post(
        "/api/hire-bases",
        json={
            "lat": 0.0,
            "lon": 0.0,
            "target": {"edge": [1, 2], "fraction": 0.0},
            "artifact_revision": "stale",
            "days": 1,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "artifact_revision_mismatch"


def test_hire_bases_network_mode_rejects_invalid_target(hire_client: TestClient):
    response = hire_client.post(
        "/api/hire-bases",
        json={
            "lat": 0.0,
            "lon": 0.0,
            "target": {"edge": [999, 1000], "fraction": 0.0},
            "artifact_revision": "revision-test",
            "days": 1,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_hire_target"


def test_hire_bases_with_no_anchors_returns_empty_without_network_overlay(
    hire_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    hire_client.app.state.boat_hire_anchors = ()
    monkeypatch.setattr(
        "pound_web.api.select_boat_hire_reachability",
        lambda *_args, **_kwargs: pytest.fail("network reachability must not be invoked"),
    )

    response = hire_client.post("/api/hire-bases", json={"lat": 51.0, "lon": -1.0})

    assert response.status_code == 200
    assert response.json() == {
        "artifact_revision": "revision-test",
        "total_matches": 0,
        "truncated": False,
        "next_offset": None,
        "budget_minutes": None,
        "cutoff_minutes": None,
        "ranking_basis": "straight_line_distance",
        "bases": [],
    }
