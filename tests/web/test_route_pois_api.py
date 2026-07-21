from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pound.graph.spatial import PoiSpatialIndex
from pound.ingest.ir import OsmElementType, PoiCategory, PointOfInterest


def _request(**changes):
    payload = {
        "artifact_revision": "revision-test",
        "kinds": ["pub"],
        "bounds": {"south": 50, "west": -2, "north": 52, "east": 0},
        "route_geometry": {
            "type": "LineString",
            "coordinates": [[-1.1, 51.0], [-0.9, 51.0]],
        },
    }
    payload.update(changes)
    return payload


def _poi(kind: str, lat: float, lon: float, osm_id: int) -> PointOfInterest:
    return PointOfInterest(
        osm_type=OsmElementType.NODE,
        osm_id=osm_id,
        category=PoiCategory.PROVISIONS,
        kind=kind,
        name=f"{kind} {osm_id}",
        lat=lat,
        lon=lon,
        source_tags={},
        geometry_source="point",
        nearest_waterway_distance_m=0,
        nearest_edge=(1, 2),
        nearest_node_uid=1,
        projected_lat=lat,
        projected_lon=lon,
    )


def test_route_pois_returns_selected_kinds_and_revision(web_client: TestClient):
    response = web_client.post("/api/route-pois", json=_request())

    assert response.status_code == 200
    body = response.json()
    assert body["day"] is None
    assert body["matching_count"] == 1
    assert all(item["kind"] == "pub" for item in body["pois"])
    assert body["pois"][0]["coordinate"] == {"lat": 51.0, "lon": -1.0}
    assert body["pois"][0]["distance_to_route_m"] < 10


def test_route_pois_with_no_selected_kinds_returns_empty_result(web_client: TestClient):
    response = web_client.post("/api/route-pois", json=_request(kinds=[]))

    assert response.status_code == 200
    assert response.json() == {
        "pois": [],
        "zoom_in_required": False,
        "matching_count": 0,
        "day": None,
    }


def test_route_pois_returns_selected_day(web_client: TestClient):
    response = web_client.post(
        "/api/route-pois",
        json=_request(
            day=2,
            day_geometry={
                "type": "LineString",
                "coordinates": [[-1.1, 51.0], [-1.001, 51.001]],
            },
        ),
    )

    assert response.status_code == 200
    assert response.json()["day"] == 2


def test_route_pois_rejects_stale_revision_with_structured_error(web_client: TestClient):
    response = web_client.post("/api/route-pois", json=_request(artifact_revision="stale"))

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "artifact_revision_mismatch",
        "message": "The routing artifact has changed; refresh the route.",
        "fields": ["artifact_revision"],
    }


def test_route_pois_rejects_invalid_bounds_with_structured_error(web_client: TestClient):
    response = web_client.post(
        "/api/route-pois",
        json=_request(bounds={"south": 52, "west": 0, "north": 50, "east": -2}),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "invalid_bounds",
        "message": "Bounds must be ordered south <= north and west <= east.",
        "fields": ["bounds"],
    }


def test_route_pois_rejects_unknown_kind_with_structured_error(web_client: TestClient):
    response = web_client.post("/api/route-pois", json=_request(kinds=["unknown"]))

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "invalid_poi_kind",
        "message": "One or more POI kinds do not exist in this artifact.",
        "fields": ["kinds"],
    }


def test_route_pois_rejects_empty_route_geometry(web_client: TestClient):
    response = web_client.post(
        "/api/route-pois",
        json=_request(route_geometry={"type": "LineString", "coordinates": []}),
    )

    assert response.status_code == 422


def test_route_pois_rejects_extra_fields_and_coercible_types(web_client: TestClient):
    assert web_client.post("/api/route-pois", json=_request(extra=True)).status_code == 422
    assert web_client.post("/api/route-pois", json=_request(kinds=[1])).status_code == 422
    assert web_client.post("/api/route-pois", json=_request(day="2")).status_code == 422


def test_route_pois_returns_over_cap_without_points(web_client: TestClient):
    client = cast(TestClient, web_client)
    pois = tuple(_poi("pub", 51.0 + index * 0.000001, -1.0, index + 1) for index in range(1001))
    app = cast(FastAPI, client.app)
    app.state.poi_spatial_index = PoiSpatialIndex(pois)

    response = client.post("/api/route-pois", json=_request())

    assert response.status_code == 200
    assert response.json()["pois"] == []
    assert response.json()["zoom_in_required"]
    assert response.json()["matching_count"] == 1001
