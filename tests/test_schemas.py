import pytest
from pydantic import ValidationError

from pound import schemas
from pound.catalog.metadata import CatalogMetadata
from pound.schemas import (
    Amenity,
    CanalConstraints,
    CanalRouteResponse,
    CatalogPlaceResponse,
    CatalogPlacesRequest,
    Coordinate,
    DayPlan,
    GeoJSONLineString,
    ResolvedConstraints,
    RouteAccessSegment,
    RouteDayGeometry,
    RouteLeg,
    RouteLock,
    RouteResult,
)
from pound.web.api import CanalRouteRequest


def test_canal_constraints_defaults():
    c = CanalConstraints(start="Oxford", end="Heyford", days=1)
    assert c.start == "Oxford"
    assert c.end == "Heyford"
    assert c.days == 1
    assert c.hours_per_day == 6.0
    assert c.boat_beam_m is None
    assert c.amenity_prefs == []
    assert "allow_derelict" not in CanalConstraints.model_fields
    assert "allow_derelict" not in ResolvedConstraints.model_fields


def test_movable_bridge_delay_is_finite_and_nonnegative():
    assert CanalConstraints(start="A", movable_bridge_delay_min=0).movable_bridge_delay_min == 0
    with pytest.raises(ValidationError):
        ResolvedConstraints(start_uid=1, end_uid=2, movable_bridge_delay_min=float("inf"))
    with pytest.raises(ValidationError):
        CanalRouteRequest(
            start_uid=1,
            end_uid=2,
            artifact_revision="r",
            movable_bridge_delay_min=float("nan"),
        )


def test_route_result_round_trip():
    leg = RouteLeg(
        from_place="Oxford",
        to_place="Heyford",
        distance_km=9.5,
        locks=2,
        est_minutes=131,
    )
    day = DayPlan(day=1, legs=[leg], end_near="Heyford", cruising_minutes=131)
    amenity = Amenity(
        kind="pub", name="The Navigation", lat=51.75, lon=-1.26, distance_m=120.0, source="osm"
    )
    result = RouteResult(
        start="Oxford",
        end="Heyford",
        is_ring=False,
        legs=[leg],
        days=[day],
        total_km=9.5,
        total_locks=2,
        total_minutes=131,
        amenities=[amenity],
        graph_source_date="2026-06-21",
    )
    dumped = result.model_dump_json()
    restored = RouteResult.model_validate_json(dumped)
    assert restored == result
    assert restored.legs[0].flagged_unknown_dims is False
    assert restored.warnings == []
    assert restored.access_segments == []


def test_route_access_segment_uses_canonical_endpoint_order():
    segment = RouteAccessSegment(
        from_uid=1,
        to_uid=2,
        osm_way_id=10,
        kind="discouraged",
        tag="boat",
        value="discouraged",
    )

    assert segment.model_dump() == {
        "from_uid": 1,
        "to_uid": 2,
        "osm_way_id": 10,
        "kind": "discouraged",
        "tag": "boat",
        "value": "discouraged",
    }


def test_route_access_segment_rejects_reverse_endpoint_order():
    with pytest.raises(
        ValidationError, match="access segment edge must use ascending endpoint uids"
    ):
        RouteAccessSegment(
            from_uid=2,
            to_uid=1,
            osm_way_id=10,
            kind="unknown",
            tag="access",
            value="customers",
        )


def test_resolved_constraints_has_uids_not_strings():
    rc = ResolvedConstraints(
        start_uid=42,
        end_uid=43,
        days=3,
    )
    assert rc.start_uid == 42
    assert rc.end_uid == 43
    assert rc.hours_per_day == 6.0
    assert not hasattr(rc, "start")
    assert not hasattr(rc, "start_node")


def test_resolved_constraints_rejects_days_zero():
    with pytest.raises(ValidationError):
        ResolvedConstraints(start_uid=0, end_uid=1, days=0)


def test_resolved_constraints_rejects_hours_per_day_zero():
    with pytest.raises(ValidationError):
        ResolvedConstraints(start_uid=0, end_uid=1, days=1, hours_per_day=0)


def test_canal_constraints_rejects_days_zero():
    with pytest.raises(ValidationError):
        CanalConstraints(start="Oxford", end="Banbury", days=0)


def test_canal_constraints_rejects_hours_per_day_zero():
    with pytest.raises(ValidationError):
        CanalConstraints(start="Oxford", end="Banbury", days=1, hours_per_day=0)


def test_canal_constraints_accepts_positive_days():
    c = CanalConstraints(start="Oxford", end="Banbury", days=1, hours_per_day=6.0)
    assert c.days == 1
    assert c.hours_per_day == 6.0


def test_constraints_days_defaults_to_none_meaning_infer():
    # days=None => "infer day count from hours_per_day" (no cap).
    rc = ResolvedConstraints(start_uid=0, end_uid=1, hours_per_day=6.0)
    assert rc.days is None
    c = CanalConstraints(start="Oxford", end="Banbury")
    assert c.days is None
    assert c.hours_per_day == 6.0  # default unchanged


@pytest.mark.parametrize("model", [CanalConstraints, ResolvedConstraints])
@pytest.mark.parametrize("field", ["boat_length_m", "boat_beam_m", "boat_draft_m", "boat_height_m"])
@pytest.mark.parametrize("value", [0, -0.1])
def test_constraints_reject_nonpositive_boat_dimensions(model, field: str, value: float):
    payload: dict[str, object] = (
        {"start": "Oxford"} if model is CanalConstraints else {"start_uid": 1, "end_uid": 2}
    )
    payload[field] = value
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("model", [CanalConstraints, ResolvedConstraints])
def test_constraints_accept_positive_boat_dimensions(model):
    payload: dict[str, object] = (
        {"start": "Oxford"} if model is CanalConstraints else {"start_uid": 1, "end_uid": 2}
    )
    payload.update(
        boat_length_m=18,
        boat_beam_m=2.1,
        boat_draft_m=0.7,
        boat_height_m=2.4,
    )
    constraints = model.model_validate(payload)
    assert constraints.boat_length_m == 18


def test_coordinate_uses_named_lat_lon_fields():
    coordinate = schemas.Coordinate(lat=51.752, lon=-1.258)

    assert coordinate.model_dump() == {"lat": 51.752, "lon": -1.258}


def test_canal_candidate_uses_integer_uid():
    candidate = schemas.CanalCandidate(
        uid=42,
        artifact_revision="oxford-2026-07-11",
        coordinate=schemas.Coordinate(lat=51.752, lon=-1.258),
        straight_line_distance_m=12.5,
        display_name="Oxford Canal",
    )

    assert candidate.uid == 42
    assert isinstance(candidate.uid, int)


def test_geojson_linestring_preserves_lon_lat_coordinate_order():
    geometry = schemas.GeoJSONLineString(coordinates=[(-1.258, 51.752), (-1.25, 51.76)])

    assert geometry.type == "LineString"
    assert geometry.coordinates[0][0] == -1.258
    assert geometry.coordinates[0][1] == 51.752


def test_canal_candidates_response_accepts_empty_candidates():
    response = schemas.CanalCandidatesResponse(
        artifact_revision="oxford-2026-07-11",
        candidates=[],
    )

    assert response.candidates == []


def test_canal_route_response_accepts_overlay_fields():
    route = RouteResult(
        start="Oxford",
        end="Heyford",
        is_ring=False,
        legs=[],
        days=[],
        total_km=0.0,
        total_locks=0,
        total_minutes=0,
        amenities=[],
        graph_source_date="2026-07-11",
    )
    response = CanalRouteResponse(
        route=route,
        geometry=GeoJSONLineString(coordinates=[(-1.0, 51.0), (-1.1, 51.1)]),
        day_geometries=[
            RouteDayGeometry(
                day=1,
                geometry=GeoJSONLineString(coordinates=[(-1.0, 51.0), (-1.1, 51.1)]),
                start=Coordinate(lat=51.0, lon=-1.0),
                end=Coordinate(lat=51.1, lon=-1.1),
            )
        ],
        locks=[
            RouteLock(
                coordinate=Coordinate(lat=51.05, lon=-1.05),
                name=None,
                day=1,
                approximate=True,
            )
        ],
    )
    assert response.day_geometries[0].day == 1
    assert response.locks[0].approximate


def test_canal_route_response_accepts_route_with_empty_legs_and_days():
    route = RouteResult(
        start="Oxford",
        end="Oxford",
        is_ring=False,
        legs=[],
        days=[],
        total_km=0.0,
        total_locks=0,
        total_minutes=0,
        amenities=[],
        graph_source_date="2026-07-11",
    )

    response = schemas.CanalRouteResponse(
        route=route,
        geometry=schemas.GeoJSONLineString(coordinates=[]),
    )

    assert response.route.legs == []
    assert response.route.days == []


def test_catalog_request_accepts_text_and_segment_geometry():
    request = CatalogPlacesRequest.model_validate(
        {
            "catalog_revision": "catalog-2",
            "kinds": ["museum"],
            "bounds": {
                "south": 51.0,
                "west": -1.5,
                "north": 52.0,
                "east": -0.5,
            },
            "text": "  STRASSE  ",
            "segment_geometry": {
                "type": "LineString",
                "coordinates": [[-1.2, 51.4], [-1.1, 51.5]],
            },
            "policy": {"basis": "segment", "radius_m": 2_000},
        }
    )

    assert request.text == "  STRASSE  "
    assert request.policy.basis == "segment"
    assert request.segment_geometry is not None
    assert request.segment_geometry.coordinates[0] == (-1.2, 51.4)


def _catalog_request_payload(**changes):
    payload = {
        "catalog_revision": "catalog-2",
        "kinds": ["museum"],
        "bounds": {
            "south": 51.0,
            "west": -1.5,
            "north": 52.0,
            "east": -0.5,
        },
        "policy": {"basis": "none", "radius_m": None},
    }
    payload.update(changes)
    return payload


def test_catalog_request_rejects_overlong_text():
    with pytest.raises(ValidationError):
        CatalogPlacesRequest.model_validate(_catalog_request_payload(text="x" * 257))


def test_catalog_request_rejects_segment_policy_without_geometry():
    with pytest.raises(ValidationError, match="segment policy requires segment_geometry"):
        CatalogPlacesRequest.model_validate(
            _catalog_request_payload(
                policy={"basis": "segment", "radius_m": 2_000},
            )
        )


@pytest.mark.parametrize("basis", ["route", "waterway", "none"])
def test_catalog_request_rejects_segment_geometry_for_other_policies(basis):
    radius_m = None if basis == "none" else 2_000
    with pytest.raises(ValidationError, match="segment_geometry requires a segment policy"):
        CatalogPlacesRequest.model_validate(
            _catalog_request_payload(
                route_geometry=(
                    {
                        "type": "LineString",
                        "coordinates": [[-1.2, 51.4], [-1.1, 51.5]],
                    }
                    if basis == "route"
                    else None
                ),
                segment_geometry={
                    "type": "LineString",
                    "coordinates": [[-1.2, 51.4], [-1.1, 51.5]],
                },
                policy={"basis": basis, "radius_m": radius_m},
            )
        )


def test_catalog_place_response_accepts_segment_distance():
    response = CatalogPlaceResponse(
        identity="way/42/museum",
        kind="museum",
        name="Canal Museum",
        coordinate=Coordinate(lat=51.5, lon=-1.2),
        distance_to_segment_m=25.0,
        metadata=CatalogMetadata(name="Canal Museum"),
    )

    assert response.distance_to_segment_m == 25.0
    assert (
        CatalogPlaceResponse(
            identity="way/42/museum",
            kind="museum",
            name="Canal Museum",
            coordinate=Coordinate(lat=51.5, lon=-1.2),
            metadata=CatalogMetadata(name="Canal Museum"),
        ).distance_to_segment_m
        is None
    )
