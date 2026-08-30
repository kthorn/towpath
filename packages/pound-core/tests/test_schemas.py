import pytest  # pyright: ignore[reportMissingImports]
from pound import schemas
from pound.catalog.metadata import CatalogMetadata
from pound.schemas import (
    Amenity,
    BoatHireProvenance,
    CanalConstraints,
    CanalRouteResponse,
    Coordinate,
    DayPlan,
    GeoJSONLineString,
    GeoJSONPoint,
    OsmProvenance,
    PlaceResponse,
    PlacesRequest,
    PlacesResponse,
    ResolvedConstraints,
    RouteAccessSegment,
    RouteDayGeometry,
    RouteLeg,
    RouteLock,
    RouteResult,
)
from pound.web.api import CanalNetworkRequest, CanalRouteRequest
from pydantic import TypeAdapter, ValidationError  # pyright: ignore[reportMissingImports]


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


@pytest.mark.parametrize(
    "model, payload",
    [
        (CanalConstraints, {"start": "Oxford"}),
        (ResolvedConstraints, {"start_uid": 1, "end_uid": 2}),
        (
            CanalRouteRequest,
            {"start_uid": 1, "end_uid": 2, "artifact_revision": "revision-test"},
        ),
    ],
)
@pytest.mark.parametrize(
    "field",
    ["hours_per_day", "boat_length_m", "boat_beam_m", "boat_draft_m", "boat_height_m"],
)
def test_route_trust_boundaries_reject_nonfinite_hours_and_dimensions(model, payload, field):
    invalid = {**payload, field: float("inf")}

    with pytest.raises(ValidationError):
        model.model_validate(invalid)

    valid = model.model_validate(payload)
    assert valid.days is None


def test_network_request_requires_bounded_schedule():
    assert CanalNetworkRequest(days=365, hours_per_day=1).days == 365
    assert CanalNetworkRequest(days=1, hours_per_day=24).hours_per_day == 24
    with pytest.raises(ValidationError):
        CanalNetworkRequest(days=366, hours_per_day=1)
    with pytest.raises(ValidationError):
        CanalNetworkRequest(days=1, hours_per_day=25)
    with pytest.raises(ValidationError):
        CanalNetworkRequest.model_validate({"days": 1})


def test_network_request_validates_selected_base_identity():
    request = CanalNetworkRequest(days=1, hours_per_day=6, selected_base_identity=None)
    assert request.selected_base_identity is None
    with pytest.raises(ValidationError):
        CanalNetworkRequest(days=1, hours_per_day=6, selected_base_identity="")


@pytest.mark.parametrize(
    "field",
    ["hours_per_day", "boat_length_m", "boat_beam_m", "boat_draft_m", "boat_height_m"],
)
def test_network_request_rejects_nonfinite_hours_and_dimensions(field):
    payload = {"days": 1, "hours_per_day": 6, field: float("inf")}

    with pytest.raises(ValidationError):
        CanalNetworkRequest.model_validate(payload)


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


def _viewport_places_payload(**changes):
    payload = {
        "mode": "viewport",
        "kinds": ["pub"],
        "bounds": {"south": 51.0, "west": -1.5, "north": 52.0, "east": -0.5},
        "policy": {"basis": "none"},
    }
    payload.update(changes)
    return payload


def _nearby_places_payload(**changes):
    payload = {
        "mode": "nearby",
        "kinds": ["pub"],
        "radius_m": 1_000.0,
        "targets": [{"id": "stop", "geometry": {"type": "Point", "coordinates": [-1.0, 52.0]}}],
    }
    payload.update(changes)
    return payload


def test_nearby_places_request_accepts_point_and_line_targets():
    request = TypeAdapter(PlacesRequest).validate_python(
        {
            "mode": "nearby",
            "kinds": ["pub", "boat_hire"],
            "radius_m": 1_000.0,
            "targets": [
                {"id": "stop", "geometry": {"type": "Point", "coordinates": [-1.0, 52.0]}},
                {
                    "id": "day",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[-1.0, 52.0], [-1.1, 52.1]],
                    },
                },
            ],
        }
    )

    assert request.mode == "nearby"
    assert len(request.targets) == 2
    assert request.targets[0].geometry.coordinates == (-1.0, 52.0)


@pytest.mark.parametrize(
    "changes",
    [
        {"targets": []},
        {"kinds": []},
        {
            "targets": [
                {"id": "same", "geometry": {"type": "Point", "coordinates": [-1.0, 52.0]}},
                {"id": "same", "geometry": {"type": "Point", "coordinates": [-1.1, 52.1]}},
            ]
        },
    ],
)
def test_nearby_places_request_rejects_empty_or_duplicate_selection(changes):
    payload = _nearby_places_payload()
    payload.update(changes)

    with pytest.raises(ValidationError):
        TypeAdapter(PlacesRequest).validate_python(payload)


def test_viewport_places_request_requires_route_for_day_geometry():
    payload = _viewport_places_payload(
        day_geometry={
            "type": "LineString",
            "coordinates": [[-1.0, 51.0], [-1.1, 51.1]],
        }
    )

    with pytest.raises(ValidationError, match="day_geometry"):
        TypeAdapter(PlacesRequest).validate_python(payload)


def test_viewport_places_request_accepts_route_without_day_geometry():
    request = TypeAdapter(PlacesRequest).validate_python(
        _viewport_places_payload(
            route_geometry={
                "type": "LineString",
                "coordinates": [[-1.0, 51.0], [-1.1, 51.1]],
            }
        )
    )

    assert request.route_geometry is not None
    assert request.day_geometry is None


@pytest.mark.parametrize("field", ["segment_geometry", "day", "catalog_revision"])
def test_viewport_places_request_forbids_legacy_fields(field):
    payload = _viewport_places_payload(**{field: None})

    with pytest.raises(ValidationError):
        TypeAdapter(PlacesRequest).validate_python(payload)


@pytest.mark.parametrize(
    ("policy", "route_geometry"),
    [
        ({"basis": "route", "radius_m": 1_000.0}, None),
        ({"basis": "waterway"}, None),
        ({"basis": "none", "radius_m": 1_000.0}, None),
    ],
)
def test_viewport_places_request_rejects_invalid_policy_matrix(policy, route_geometry):
    payload = _viewport_places_payload(policy=policy, route_geometry=route_geometry)

    with pytest.raises(ValidationError):
        TypeAdapter(PlacesRequest).validate_python(payload)


def test_viewport_places_request_rejects_reversed_bounds():
    with pytest.raises(ValidationError):
        TypeAdapter(PlacesRequest).validate_python(
            _viewport_places_payload(
                bounds={"south": 52.0, "west": -1.5, "north": 51.0, "east": -0.5}
            )
        )


def test_viewport_places_request_accepts_over_budget_span_for_runtime_validation():
    request = TypeAdapter(PlacesRequest).validate_python(
        _viewport_places_payload(bounds={"south": 51.0, "west": -1.5, "north": 62.0, "east": -0.5})
    )

    assert request.mode == "viewport"
    assert request.bounds.north - request.bounds.south == 11.0


@pytest.mark.parametrize(
    "coordinates",
    [[float("nan"), 52.0], [float("inf"), 52.0], [-181.0, 52.0], [-1.0, 91.0]],
)
def test_geojson_point_rejects_nonfinite_or_out_of_range_coordinates(coordinates):
    with pytest.raises(ValidationError):
        GeoJSONPoint.model_validate({"type": "Point", "coordinates": coordinates})


@pytest.mark.parametrize(
    "coordinates",
    [
        [[-1.0, 52.0], [float("nan"), 52.1]],
        [[-1.0, 52.0], [181.0, 52.1]],
        [[-1.0, 52.0], [-1.1, 91.0]],
    ],
)
def test_geojson_linestring_rejects_nonfinite_or_out_of_range_coordinates(coordinates):
    with pytest.raises(ValidationError):
        schemas.GeoJSONLineString.model_validate({"type": "LineString", "coordinates": coordinates})


def test_places_request_accepts_over_budget_viewport_geometry_for_runtime_validation():
    route_coordinates = [[-1.0, 52.0]] * 10_001
    request = TypeAdapter(PlacesRequest).validate_python(
        _viewport_places_payload(
            route_geometry={"type": "LineString", "coordinates": route_coordinates},
        )
    )

    assert request.mode == "viewport"
    assert len(request.route_geometry.coordinates) == 10_001


def test_places_request_accepts_over_budget_nearby_geometry_for_runtime_validation():
    line_coordinates = [[-1.0, 52.0]] * 10_001
    request = TypeAdapter(PlacesRequest).validate_python(
        _nearby_places_payload(
            targets=[
                {
                    "id": "long-line",
                    "geometry": {"type": "LineString", "coordinates": line_coordinates},
                }
            ]
        )
    )

    assert request.mode == "nearby"
    assert len(request.targets[0].geometry.coordinates) == 10_001


def test_places_response_uses_structured_provenance_and_only_places():
    osm = PlaceResponse(
        kind="pub",
        name="The Towpath",
        coordinate=Coordinate(lat=52.0, lon=-1.0),
        provenance=OsmProvenance(
            source="osm",
            osm_type="way",
            osm_id=42,
            metadata=CatalogMetadata(name="The Towpath"),
        ),
    )
    hire = PlaceResponse(
        kind="boat_hire",
        name="Canal Basin",
        coordinate=Coordinate(lat=52.0, lon=-1.0),
        provenance=BoatHireProvenance(
            source="boat_hire",
            provider_id="provider",
            provider_name="Provider Ltd",
            location_id="base",
            location_name="Canal Basin",
        ),
    )
    response = PlacesResponse(places=[osm, hire])

    assert response.model_dump().keys() == {"places"}
    assert response.places[0].provenance.source == "osm"
    assert response.places[1].provenance.source == "boat_hire"


def test_places_response_rejects_unknown_provenance_source():
    with pytest.raises(ValidationError):
        PlaceResponse.model_validate(
            {
                "kind": "pub",
                "name": "The Towpath",
                "coordinate": {"lat": 52.0, "lon": -1.0},
                "provenance": {"source": "unknown"},
            }
        )
