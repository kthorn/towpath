import pytest
from pydantic import ValidationError

from pound import schemas
from pound.schemas import (
    Amenity,
    CanalConstraints,
    DayPlan,
    ResolvedConstraints,
    RouteLeg,
    RouteResult,
)


def test_canal_constraints_defaults():
    c = CanalConstraints(start="Oxford", end="Heyford", days=1)
    assert c.start == "Oxford"
    assert c.end == "Heyford"
    assert c.days == 1
    assert c.hours_per_day == 6.0
    assert c.boat_beam_m is None
    assert c.amenity_prefs == []
    assert c.allow_derelict is False


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
    assert geometry.coordinates[0] == (-1.258, 51.752)


def test_canal_candidates_response_accepts_empty_candidates():
    response = schemas.CanalCandidatesResponse(
        artifact_revision="oxford-2026-07-11",
        candidates=[],
    )

    assert response.candidates == []


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
