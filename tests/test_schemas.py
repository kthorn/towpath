from pound.schemas import (
    Amenity,
    CanalConstraints,
    DayPlan,
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
