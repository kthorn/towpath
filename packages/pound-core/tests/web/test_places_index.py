from __future__ import annotations

from typing import Any, Literal, cast

import networkx as nx
import pound.web.places as places
import pytest  # pyright: ignore[reportMissingImports]
from pound.catalog.metadata import CatalogMetadata
from pound.catalog.models import CatalogPlace
from pound.catalog.spatial import CatalogSpatialIndex
from pound.graph.spatial import GraphSpatialIndex
from pound.ingest.ir import OsmElementType, WayDimensions
from pound.schemas import (
    BoatHireProvenance,
    MapBounds,
    NearbyPlacesRequest,
    OsmProvenance,
    PlacesQueryPolicy,
    ViewportPlacesRequest,
)
from pound.web.boat_hire import BoatHireSeed
from shapely import wkb
from shapely.geometry import LineString, Point


def _graph() -> nx.Graph:
    graph = nx.Graph()
    graph.add_node(1, lat=51.0, lon=-1.0, movable_bridge_ids=())
    graph.add_node(2, lat=51.0, lon=-0.99, movable_bridge_ids=())
    graph.add_edge(
        1,
        2,
        geometry=[(51.0, -1.0), (51.0, -0.99)],
        dimensions=WayDimensions(),
        length_m=700.0,
        locks=0,
        movable_bridge_ids=(),
    )
    return graph


def _place(
    kind: str,
    osm_id: int,
    *,
    lat: float = 51.0,
    lon: float = -1.0,
    name: str | None = None,
    geometry: Point | LineString | None = None,
    osm_type: OsmElementType = OsmElementType.NODE,
) -> CatalogPlace:
    display_name = name or f"{kind} {osm_id}"
    geometry = geometry or Point(lon, lat)
    return CatalogPlace(
        osm_type=osm_type,
        osm_id=osm_id,
        kind=kind,
        name=display_name,
        lat=lat,
        lon=lon,
        metadata=CatalogMetadata(name=display_name),
        geometry_wkb=wkb.dumps(geometry, output_dimension=2),
        geometry_source="point" if geometry.geom_type == "Point" else "line",
    )


def _bounds() -> MapBounds:
    return MapBounds(south=50.9, west=-1.1, north=51.1, east=-0.9)


def _viewport_request(
    kinds: list[str],
    *,
    text: str | None = None,
    policy: Literal["route", "waterway", "none"] = "none",
    radius_m: float | None = None,
    route_geometry: list[tuple[float, float]] | None = None,
    day_geometry: list[tuple[float, float]] | None = None,
) -> ViewportPlacesRequest:
    return ViewportPlacesRequest(
        mode="viewport",
        kinds=kinds,
        bounds=_bounds(),
        text=text,
        route_geometry=(
            cast(Any, {"type": "LineString", "coordinates": route_geometry})
            if route_geometry is not None
            else None
        ),
        day_geometry=(
            cast(Any, {"type": "LineString", "coordinates": day_geometry})
            if day_geometry is not None
            else None
        ),
        policy=PlacesQueryPolicy(basis=policy, radius_m=radius_m),
    )


def _nearby_request(
    kinds: list[str],
    *,
    radius_m: float = 200.0,
    targets: list[dict[str, Any]] | None = None,
    text: str | None = None,
) -> NearbyPlacesRequest:
    return NearbyPlacesRequest(
        mode="nearby",
        kinds=kinds,
        radius_m=radius_m,
        text=text,
        targets=cast(
            Any,
            targets
            if targets is not None
            else [
                {
                    "id": "point",
                    "geometry": {"type": "Point", "coordinates": [-1.0, 51.0]},
                }
            ],
        ),
    )


def _index(
    catalog_places: tuple[CatalogPlace, ...] = (),
    seeds: tuple[BoatHireSeed, ...] = (),
) -> places.PlacesIndex:
    graph_index = GraphSpatialIndex(_graph())
    catalog_index = CatalogSpatialIndex(catalog_places, graph_index)
    return places.PlacesIndex(catalog_index, graph_index, seeds)


def test_viewport_composes_osm_before_boat_hire_and_matches_provider_location_text():
    index = _index(
        (_place("pub", 2, name="OSM pub"),),
        (
            BoatHireSeed(
                "provider",
                "base:one",
                51.0,
                -1.0,
                source_provider_name="River Hire",
                location_name="Canal Basin",
            ),
        ),
    )

    response = index.query(_viewport_request(["pub", "boat_hire"], text="canal"))

    assert [place.provenance.source for place in response.places] == ["boat_hire"]
    hire = cast(BoatHireProvenance, response.places[0].provenance)
    assert hire.provider_id == "provider"
    assert hire.location_name == "Canal Basin"

    osm_text = index.query(_viewport_request(["pub", "boat_hire"], text="osm"))
    assert [place.provenance.source for place in osm_text.places] == ["osm"]

    tied = index.query(_viewport_request(["pub", "boat_hire"]))
    assert [place.provenance.source for place in tied.places] == ["osm", "boat_hire"]


def test_viewport_route_waterway_and_none_policies_apply_to_hire_points():
    seed = BoatHireSeed("provider", "base:one", 51.001, -0.995)
    index = _index(seeds=(seed,))
    route = [(-1.1, 51.0), (-0.9, 51.0)]

    assert index.query(_viewport_request(["boat_hire"])).places
    assert not index.query(
        _viewport_request(["boat_hire"], policy="route", radius_m=20, route_geometry=route)
    ).places
    assert index.query(
        _viewport_request(["boat_hire"], policy="route", radius_m=200, route_geometry=route)
    ).places
    assert not index.query(_viewport_request(["boat_hire"], policy="waterway", radius_m=20)).places
    assert index.query(_viewport_request(["boat_hire"], policy="waterway", radius_m=200)).places


def test_viewport_catalog_work_limit_maps_and_records_candidate_count():
    places_index = _index((_place("pub", 1),))
    places_index.max_work = 0
    stats = places.PlacesQueryStats()

    with pytest.raises(places.PlacesQueryBudgetError) as error:
        places_index.query(_viewport_request(["pub"]), stats=stats)

    assert error.value.fields == ["bounds"]
    assert stats.work_used == 1


def test_viewport_catalog_result_limit_maps_and_records_candidate_count():
    places_index = _index((_place("pub", 1),))
    places_index.max_results = 0
    stats = places.PlacesQueryStats()

    with pytest.raises(places.PlacesResultLimitError) as error:
        places_index.query(_viewport_request(["pub"]), stats=stats)

    assert error.value.target_id is None
    assert stats.work_used == 1


def test_boat_hire_only_viewport_does_not_charge_osm_candidates():
    index = _index(
        (_place("marina", 1),),
        (BoatHireSeed("provider", "base:one", 51.0, -1.0),),
    )
    stats = places.PlacesQueryStats()

    response = index.query(_viewport_request(["boat_hire"]), stats=stats)

    assert len(response.places) == 1
    assert stats.work_used == 1


def test_nearby_point_and_line_targets_duplicate_results_and_aggregate_work():
    index = _index(
        (_place("pub", 1),),
        (BoatHireSeed("provider", "base:one", 51.0, -1.0),),
    )
    request = _nearby_request(
        ["pub", "boat_hire"],
        targets=[
            {"id": "point", "geometry": {"type": "Point", "coordinates": [-1.0, 51.0]}},
            {
                "id": "line",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-1.0, 51.0], [-0.99, 51.0]],
                },
            },
        ],
    )
    stats = places.PlacesQueryStats()

    response = index.query(request, stats=stats)

    assert [place.target_id for place in response.places] == [
        "point",
        "point",
        "line",
        "line",
    ]
    assert stats.work_used == 4
    assert all(place.distance_to_target_m is not None for place in response.places)
    assert all(place.distance_to_full_route_m is None for place in response.places)


def test_nearby_work_budget_counts_each_public_seed_for_each_target():
    index = _index(
        seeds=(BoatHireSeed("provider", "base:one", 51.0, -1.0),),
    )
    request = _nearby_request(
        ["boat_hire"],
        targets=[
            {"id": "first", "geometry": {"type": "Point", "coordinates": [-1.0, 51.0]}},
            {"id": "second", "geometry": {"type": "Point", "coordinates": [-1.0, 51.0]}},
        ],
    )
    stats = places.PlacesQueryStats()
    index.max_work = 1

    with pytest.raises(places.PlacesQueryBudgetError) as error:
        index.query(request, stats=stats)

    assert error.value.fields == ["targets"]
    assert stats.work_used == 2


def test_nearby_result_limit_identifies_crossing_target_and_keeps_stats():
    index = _index(
        (_place("pub", 1),),
        (BoatHireSeed("provider", "base:one", 51.0, -1.0),),
    )
    request = _nearby_request(
        ["pub", "boat_hire"],
        targets=[
            {"id": "first", "geometry": {"type": "Point", "coordinates": [-1.0, 51.0]}},
            {"id": "second", "geometry": {"type": "Point", "coordinates": [-1.0, 51.0]}},
        ],
    )
    index.max_results = 1
    stats = places.PlacesQueryStats()

    with pytest.raises(places.PlacesResultLimitError) as error:
        index.query(request, stats=stats)

    assert error.value.target_id == "first"
    assert stats.work_used == 2


def test_result_capacity_is_charged_after_osm_identity_suppression():
    osm = _place("marina", 1)
    seed = BoatHireSeed(
        "provider",
        "base:one",
        51.0,
        -1.0,
        osm_url="https://www.openstreetmap.org/node/1",
    )
    places_index = _index((osm,), (seed,))
    places_index.max_results = 1

    response = places_index.query(_viewport_request(["marina", "boat_hire"]))

    assert len(response.places) == 1
    assert response.places[0].provenance.source == "boat_hire"


@pytest.mark.parametrize("mode", ["viewport", "nearby"])
def test_suppression_headroom_counts_each_selected_catalog_kind(mode: str):
    shared_identity = tuple(_place(kind, 2) for kind in ("marina", "museum", "pub"))
    unrelated = _place("cafe", 1, lon=-1.001)
    seed = BoatHireSeed(
        "provider",
        "base:shared",
        51.0,
        -1.0,
        osm_url="https://www.openstreetmap.org/node/2",
    )
    places_index = _index(shared_identity + (unrelated,), (seed,))
    places_index.max_results = 2

    if mode == "viewport":
        request = _viewport_request(
            ["marina", "museum", "pub", "cafe", "boat_hire"],
        )
    else:
        request = _nearby_request(
            ["marina", "museum", "pub", "cafe", "boat_hire"],
            radius_m=200,
        )

    response = places_index.query(request)

    assert len(response.places) == 2
    assert {place.kind for place in response.places} == {"boat_hire", "cafe"}


def test_exact_osm_identity_suppresses_osm_only_when_hire_is_emitted():
    osm = _place("marina", 1, name="osm-only-name")
    seed = BoatHireSeed(
        "provider",
        "base:one",
        51.0,
        -1.0,
        source_provider_name="Provider",
        location_name="Basin",
        osm_url="https://www.openstreetmap.org/node/1",
    )
    index = _index((osm,), (seed,))

    both = index.query(_viewport_request(["marina", "boat_hire"]))
    assert [place.provenance.source for place in both.places] == ["boat_hire"]

    marina_only = index.query(_viewport_request(["marina"]))
    assert [place.provenance.source for place in marina_only.places] == ["osm"]

    text_excludes_hire = index.query(
        _viewport_request(["marina", "boat_hire"], text="osm-only-name")
    )
    assert [place.provenance.source for place in text_excludes_hire.places] == ["osm"]


def test_same_osm_url_keeps_distinct_public_providers_and_review_rows_do_not_suppress():
    osm = _place("marina", 1)
    public = (
        BoatHireSeed(
            "provider-a",
            "base:a",
            51.0,
            -1.0,
            osm_url="https://www.openstreetmap.org/node/1",
        ),
        BoatHireSeed(
            "provider-b",
            "base:b",
            51.0,
            -1.0,
            osm_url="https://www.openstreetmap.org/node/1",
        ),
    )
    review = BoatHireSeed(
        "review-provider",
        "base:review",
        51.0,
        -1.0,
        record_type="review_positive",
        osm_url="https://www.openstreetmap.org/node/1",
    )

    response = _index((osm,), public + (review,)).query(_viewport_request(["marina", "boat_hire"]))

    assert [place.provenance.source for place in response.places] == [
        "boat_hire",
        "boat_hire",
    ]
    assert {
        cast(BoatHireProvenance, place.provenance).provider_id for place in response.places
    } == {"provider-a", "provider-b"}
    assert (
        len(_index((osm,), (review,)).query(_viewport_request(["marina", "boat_hire"])).places) == 1
    )
    assert isinstance(
        _index((osm,), (review,))
        .query(_viewport_request(["marina", "boat_hire"]))
        .places[0]
        .provenance,
        OsmProvenance,
    )


def test_places_query_rejects_configured_mode_budgets_before_source_work():
    index = _index((_place("pub", 1),), (BoatHireSeed("provider", "base:one", 51.0, -1.0),))

    with pytest.raises(places.PlacesQueryBudgetError) as kinds_error:
        index.__class__(
            index.catalog_index,
            index.waterway_index,
            index.boat_hire_seeds,
            max_kinds=1,
        ).query(_viewport_request(["pub", "boat_hire"]))
    assert kinds_error.value.fields == ["kinds"]

    with pytest.raises(places.PlacesQueryBudgetError) as span_error:
        index.__class__(
            index.catalog_index,
            index.waterway_index,
            index.boat_hire_seeds,
            max_viewport_span_deg=0.1,
        ).query(_viewport_request(["pub"]))
    assert span_error.value.fields == ["bounds"]

    with pytest.raises(places.PlacesQueryBudgetError) as vertices_error:
        index.__class__(
            index.catalog_index,
            index.waterway_index,
            index.boat_hire_seeds,
            max_vertices=1,
        ).query(
            _viewport_request(
                ["pub"],
                route_geometry=[(-1.0, 51.0), (-0.9, 51.0)],
            )
        )
    assert vertices_error.value.fields == ["route_geometry", "day_geometry"]

    with pytest.raises(places.PlacesQueryBudgetError) as radius_error:
        index.__class__(
            index.catalog_index,
            index.waterway_index,
            index.boat_hire_seeds,
            max_radius_m=10,
        ).query(_nearby_request(["pub"], radius_m=11))
    assert radius_error.value.fields == ["radius_m"]

    with pytest.raises(places.PlacesQueryBudgetError) as targets_error:
        index.__class__(
            index.catalog_index,
            index.waterway_index,
            index.boat_hire_seeds,
            max_targets=1,
        ).query(
            _nearby_request(
                ["pub"],
                targets=[
                    {"id": "one", "geometry": {"type": "Point", "coordinates": [-1.0, 51.0]}},
                    {"id": "two", "geometry": {"type": "Point", "coordinates": [-1.0, 51.0]}},
                ],
            )
        )
    assert targets_error.value.fields == ["targets"]


def test_constructor_rejects_budgets_above_hard_schema_ceilings():
    graph_index = GraphSpatialIndex(_graph())
    catalog_index = CatalogSpatialIndex((), graph_index)

    with pytest.raises(ValueError):
        places.PlacesIndex(catalog_index, graph_index, (), max_kinds=17)
    with pytest.raises(ValueError):
        places.PlacesIndex(catalog_index, graph_index, (), max_radius_m=2_001)
    with pytest.raises(ValueError):
        places.PlacesIndex(catalog_index, graph_index, (), max_vertices=10_001)
    with pytest.raises(ValueError):
        places.PlacesIndex(catalog_index, graph_index, (), max_targets=65)
    with pytest.raises(ValueError):
        places.PlacesIndex(catalog_index, graph_index, (), max_work=100_001)
    with pytest.raises(ValueError):
        places.PlacesIndex(catalog_index, graph_index, (), max_results=1_001)


def test_viewport_context_distances_are_populated_for_hire():
    seed = BoatHireSeed("provider", "base:one", 51.001, -0.995)
    route = [(-1.1, 51.0), (-0.9, 51.0)]
    day = [(-1.1, 51.001), (-0.9, 51.001)]

    response = _index(seeds=(seed,)).query(
        _viewport_request(
            ["boat_hire"],
            policy="route",
            radius_m=200,
            route_geometry=route,
            day_geometry=day,
        )
    )

    place = response.places[0]
    assert place.target_id is None
    assert place.distance_to_target_m is None
    assert place.distance_to_full_route_m is not None
    assert place.distance_to_selected_geometry_m is not None
    assert place.waterway_distance_m is not None


def test_nearby_response_uses_structured_osm_and_hire_provenance():
    osm = _place("pub", 1)
    seed = BoatHireSeed(
        "provider",
        "base:one",
        51.0,
        -1.0,
        source_provider_name="Provider Ltd",
        location_name="Canal Basin",
        source_provider_website="https://provider.test/",
        osm_url="https://www.openstreetmap.org/node/9",
        evidence_url="https://provider.test/evidence",
        booking_url="https://provider.test/book",
    )
    response = _index((osm,), (seed,)).query(_nearby_request(["pub", "boat_hire"]))

    assert isinstance(response.places[0].provenance, OsmProvenance)
    assert isinstance(response.places[1].provenance, BoatHireProvenance)
    hire = cast(BoatHireProvenance, response.places[1].provenance)
    assert hire.provider_name == "Provider Ltd"
    assert hire.provider_url == "https://provider.test/"
    assert hire.osm_url == "https://www.openstreetmap.org/node/9"
    assert hire.evidence_url == "https://provider.test/evidence"
    assert hire.booking_url == "https://provider.test/book"


def test_nearby_line_distance_uses_full_target_geometry():
    line = LineString([(-1.0, 51.0), (-0.99, 51.0)])
    place = _place("marina", 1, lat=51.001, lon=-0.995, geometry=Point(-0.995, 51.001))
    response = _index((place,)).query(
        _nearby_request(
            ["marina"],
            radius_m=200,
            targets=[
                {
                    "id": "line",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [list(coordinate) for coordinate in line.coords],
                    },
                }
            ],
        )
    )

    assert response.places[0].distance_to_target_m == pytest.approx(111, abs=5)


def test_constructor_accepts_zero_result_and_work_budgets_for_explicit_limits():
    graph_index = GraphSpatialIndex(_graph())
    catalog_index = CatalogSpatialIndex((), graph_index)
    index = places.PlacesIndex(catalog_index, graph_index, (), max_work=0, max_results=0)

    assert index.max_work == 0
    assert index.max_results == 0
