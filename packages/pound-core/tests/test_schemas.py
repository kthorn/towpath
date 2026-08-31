import pytest  # pyright: ignore[reportMissingImports]
from pound import schemas
from pound.catalog.metadata import CatalogMetadata
from pound.schemas import (
    BoatHireProvenance,
    CanalConstraints,
    CanalPointHandle,
    CanalRouteResponse,
    Coordinate,
    GeoJSONLineString,
    GeoJSONPoint,
    NamedRouteRequest,
    OsmProvenance,
    PlaceResponse,
    PlacesRequest,
    PlacesResponse,
    ProjectedRouteConstraints,
    RouteAccessSegment,
    RouteDayGeometry,
    RouteLock,
    RouteResult,
)
from pydantic import TypeAdapter, ValidationError  # pyright: ignore[reportMissingImports]


def _projected_payload() -> dict[str, object]:
    return {
        "start": {"edge": (1, 2), "fraction": 0.0},
        "end": {"edge": (1, 2), "fraction": 1.0},
    }


def test_canal_constraints_share_only_day_and_boat_options():
    c = CanalConstraints(days=1)
    named = NamedRouteRequest(start="Oxford", end="Heyford", days=1)
    projected = ProjectedRouteConstraints.model_validate(_projected_payload())
    assert named.start == "Oxford"
    assert named.end == "Heyford"
    assert projected.start == CanalPointHandle(edge=(1, 2), fraction=0)
    assert c.days == 1
    assert c.hours_per_day == 6.0
    assert c.boat_beam_m is None
    assert c.amenity_prefs == []
    assert "start" not in CanalConstraints.model_fields
    assert "end" not in CanalConstraints.model_fields
    assert "allow_derelict" not in ProjectedRouteConstraints.model_fields


def test_movable_bridge_delay_is_finite_and_nonnegative():
    assert CanalConstraints(movable_bridge_delay_min=0).movable_bridge_delay_min == 0
    with pytest.raises(ValidationError):
        ProjectedRouteConstraints.model_validate(
            {**_projected_payload(), "movable_bridge_delay_min": float("inf")}
        )


def test_projected_constraints_have_handles_not_node_ids():
    constraints = ProjectedRouteConstraints.model_validate(_projected_payload())
    assert constraints.start.edge == (1, 2)
    assert constraints.end.fraction == 1
    assert not hasattr(constraints, "start_node")


def test_projected_constraints_reject_days_zero():
    with pytest.raises(ValidationError):
        ProjectedRouteConstraints.model_validate({**_projected_payload(), "days": 0})


def test_projected_constraints_reject_hours_per_day_zero():
    with pytest.raises(ValidationError):
        ProjectedRouteConstraints.model_validate({**_projected_payload(), "hours_per_day": 0})


@pytest.mark.parametrize(
    "model, payload",
    [(CanalConstraints, {}), (ProjectedRouteConstraints, _projected_payload())],
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


def test_canal_constraints_rejects_days_zero():
    with pytest.raises(ValidationError):
        CanalConstraints(days=0)


def test_canal_constraints_rejects_hours_per_day_zero():
    with pytest.raises(ValidationError):
        CanalConstraints(days=1, hours_per_day=0)


def test_canal_constraints_accepts_positive_days():
    c = CanalConstraints(days=1, hours_per_day=6.0)
    assert c.days == 1
    assert c.hours_per_day == 6.0


def test_constraints_days_defaults_to_none_meaning_infer():
    projected = ProjectedRouteConstraints.model_validate(_projected_payload())
    assert projected.days is None
    c = CanalConstraints()
    assert c.days is None
    assert c.hours_per_day == 6.0


@pytest.mark.parametrize("model", [CanalConstraints, ProjectedRouteConstraints])
@pytest.mark.parametrize("field", ["boat_length_m", "boat_beam_m", "boat_draft_m", "boat_height_m"])
@pytest.mark.parametrize("value", [0, -0.1])
def test_constraints_reject_nonpositive_boat_dimensions(model, field: str, value: float):
    payload = {} if model is CanalConstraints else _projected_payload()
    payload[field] = value
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("model", [CanalConstraints, ProjectedRouteConstraints])
def test_constraints_accept_positive_boat_dimensions(model):
    payload = {} if model is CanalConstraints else _projected_payload()
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


def test_canal_candidate_uses_projected_handle_identity():
    handle = schemas.CanalPointHandle(edge=(41, 42), fraction=0.5)
    candidate = schemas.CanalCandidate(
        candidate_id="41:42:0.500000000000",
        handle=handle,
        coordinate=schemas.Coordinate(lat=51.752, lon=-1.258),
        straight_line_distance_m=12.5,
        display_name="Oxford Canal",
    )

    assert candidate.candidate_id == "41:42:0.500000000000"
    assert candidate.handle == handle


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


def test_route_result_json_round_trip_preserves_uid_free_access_segments():
    route = RouteResult(
        start="Oxford",
        end="Heyford",
        is_ring=False,
        legs=[],
        days=[],
        total_km=1.25,
        total_locks=0,
        total_minutes=15,
        amenities=[],
        access_segments=[
            RouteAccessSegment(
                osm_way_id=42,
                kind="discouraged",
                tag="boat",
                value="discouraged",
            )
        ],
        graph_source_date="2026-08-30",
    )

    restored = RouteResult.model_validate_json(route.model_dump_json())

    assert restored == route
    assert restored.access_segments[0].model_dump() == {
        "osm_way_id": 42,
        "kind": "discouraged",
        "tag": "boat",
        "value": "discouraged",
    }


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
