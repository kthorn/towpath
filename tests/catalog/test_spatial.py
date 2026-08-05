import networkx as nx
import pytest
from shapely import wkb
from shapely.geometry import LineString, Point

from pound.catalog.metadata import CatalogMetadata
from pound.catalog.models import CatalogPlace
from pound.catalog.spatial import CatalogQueryLimitError, CatalogSpatialIndex
from pound.graph.spatial import GraphSpatialIndex
from pound.ingest.ir import OsmElementType
from pound.schemas import CatalogPlacesRequest, MapBounds


def _graph() -> nx.Graph:
    graph = nx.Graph()
    graph.add_node(1, lat=51.0, lon=-1.0)
    graph.add_node(2, lat=51.0, lon=-0.99)
    graph.add_edge(1, 2, geometry=[(51.0, -1.0), (51.0, -0.99)])
    return graph


def _place(
    kind: str,
    *,
    osm_id: int,
    lat: float,
    lon: float,
    geometry=None,
    name: str | None = None,
    alt_name: str | None = None,
    osm_type: OsmElementType = OsmElementType.NODE,
) -> CatalogPlace:
    geometry = geometry or Point(lon, lat)
    primary_name = name or f"{kind} {osm_id}"
    return CatalogPlace(
        osm_type=osm_type,
        osm_id=osm_id,
        kind=kind,
        name=primary_name,
        lat=lat,
        lon=lon,
        metadata=CatalogMetadata(name=primary_name, alt_name=alt_name),
        geometry_wkb=wkb.dumps(geometry, output_dimension=2),
        geometry_source="point" if geometry.geom_type == "Point" else "line",
    )


def _request(**changes) -> CatalogPlacesRequest:
    payload = {
        "catalog_revision": "catalog-test",
        "kinds": ["pub"],
        "bounds": MapBounds(south=50.9, west=-1.1, north=51.1, east=-0.9),
        "route_geometry": {
            "type": "LineString",
            "coordinates": [[-1.1, 51.0], [-0.9, 51.0]],
        },
        "policy": {"basis": "route", "radius_m": 1000},
    }
    payload.update(changes)
    return CatalogPlacesRequest.model_validate(payload)


def test_catalog_index_does_not_build_unused_geometry_tree():
    index = CatalogSpatialIndex(
        (_place("pub", osm_id=1, lat=51.0, lon=-1.0),),
        GraphSpatialIndex(_graph()),
    )

    assert not hasattr(index, "geometry_tree")


def test_catalog_query_filters_kinds_viewport_and_keeps_deterministic_order():
    index = CatalogSpatialIndex(
        (
            _place("pub", osm_id=9, lat=51.0, lon=-1.0),
            _place("museum", osm_id=3, lat=51.0, lon=-1.0),
            _place("pub", osm_id=2, lat=52.0, lon=-2.0),
        ),
        GraphSpatialIndex(_graph()),
    )

    result = index.query(_request(policy={"basis": "none", "radius_m": None}))

    assert [place.identity for place in result.places] == [(OsmElementType.NODE, 9, "pub")]
    assert result.matching_count == 1
    assert not result.over_cap


def test_catalog_query_uses_full_geometry_for_route_distance_and_day_distance():
    index = CatalogSpatialIndex(
        (
            _place(
                "pub",
                osm_id=1,
                lat=51.003,
                lon=-0.995,
                geometry=LineString([(-0.995, 51.0), (-0.995, 51.003)]),
            ),
        ),
        GraphSpatialIndex(_graph()),
    )

    result = index.query(
        _request(
            route_geometry={
                "type": "LineString",
                "coordinates": [[-1.1, 51.0], [-0.9, 51.0]],
            },
            day_geometry={
                "type": "LineString",
                "coordinates": [[-1.1, 51.003], [-0.9, 51.003]],
            },
            day=2,
            policy={"basis": "route", "radius_m": 20},
        )
    )

    assert result.matching_count == 1
    assert result.full_route_distances[0] == pytest.approx(0, abs=0.1)
    selected_distance = result.selected_geometry_distances[0]
    assert selected_distance is not None
    assert selected_distance < 10


def test_catalog_query_applies_waterway_policy_and_exposes_distance():
    graph_index = GraphSpatialIndex(_graph())
    place = _place("marina", osm_id=1, lat=51.001, lon=-0.995)
    result = CatalogSpatialIndex((place,), graph_index).query(
        _request(
            kinds=["marina"],
            policy={"basis": "waterway", "radius_m": 120},
            route_geometry=None,
        )
    )

    assert result.matching_count == 1
    assert result.waterway_distances[0] == pytest.approx(111, abs=3)


def test_catalog_query_waterway_missing_does_not_match_but_locality_does():
    place = _place("marina", osm_id=1, lat=51.001, lon=-0.995)
    no_waterway = CatalogSpatialIndex((place,), GraphSpatialIndex(nx.Graph()))

    bounded = no_waterway.query(
        _request(
            kinds=["marina"],
            route_geometry=None,
            policy={"basis": "waterway", "radius_m": 2_000},
        )
    )
    locality = no_waterway.query(
        _request(
            kinds=["marina"],
            route_geometry=None,
            policy={"basis": "none", "radius_m": None},
        )
    )

    assert bounded.places == ()
    assert locality.places == (place,)
    assert locality.waterway_distances == (None,)


def test_catalog_query_includes_exact_radius_boundary():
    graph_index = GraphSpatialIndex(_graph())
    place = _place("pub", osm_id=1, lat=51.001, lon=-0.995)
    distance = graph_index.distance_to_waterway(wkb.loads(place.geometry_wkb))
    assert distance is not None

    result = CatalogSpatialIndex((place,), graph_index).query(
        _request(policy={"basis": "waterway", "radius_m": distance})
    )

    assert result.matching_count == 1


def test_catalog_query_returns_over_cap_sentinel_without_records():
    places = tuple(
        _place("pub", osm_id=index + 1, lat=51.0 + index * 0.000001, lon=-1.0)
        for index in range(1001)
    )
    result = CatalogSpatialIndex(places, GraphSpatialIndex(_graph())).query(_request())

    assert result.places == ()
    assert result.matching_count == 1001
    assert result.over_cap


def test_catalog_query_rejects_large_viewport_before_metric_work():
    index = CatalogSpatialIndex(
        (_place("pub", osm_id=1, lat=51.0, lon=-1.0),),
        GraphSpatialIndex(_graph()),
    )

    with pytest.raises(CatalogQueryLimitError, match="viewport"):
        index.query(
            _request(
                bounds=MapBounds(south=-90, west=-180, north=90, east=180),
                route_geometry=None,
                policy={"basis": "none", "radius_m": None},
            )
        )


def test_catalog_query_rejects_invalid_radius_and_vertex_budget():
    index = CatalogSpatialIndex(
        (_place("pub", osm_id=1, lat=51.0, lon=-1.0),),
        GraphSpatialIndex(_graph()),
    )

    with pytest.raises(ValueError, match="radius"):
        index.query(_request(policy={"basis": "route", "radius_m": 2_001}))

    with pytest.raises(ValueError, match="coordinate"):
        index.query(
            _request(
                route_geometry={
                    "type": "LineString",
                    "coordinates": [[-1.0, 51.0], [-1.0, 51.0]] * 5_001,
                }
            )
        )


# --- Task 3 tests ---


@pytest.mark.parametrize("text", ["STRASSE", "straße", "  strasse  "])
def test_catalog_query_casefolds_primary_names(text):
    place = _place(
        "pub",
        osm_id=1,
        lat=51.0,
        lon=-1.0,
        name="Straße Arms",
    )
    result = CatalogSpatialIndex((place,), GraphSpatialIndex(_graph())).query(
        _request(
            text=text,
            route_geometry=None,
            policy={"basis": "none", "radius_m": None},
        )
    )

    assert result.places == (place,)


def test_catalog_query_matches_alternate_name_by_substring():
    place = _place(
        "pub",
        osm_id=1,
        lat=51.0,
        lon=-1.0,
        name="Navigation Inn",
        alt_name="Towpath Arms",
    )
    result = CatalogSpatialIndex((place,), GraphSpatialIndex(_graph())).query(
        _request(
            text="PATH AR",
            route_geometry=None,
            policy={"basis": "none", "radius_m": None},
        )
    )

    assert result.places == (place,)


@pytest.mark.parametrize("text", [None, "", "   "])
def test_catalog_query_treats_empty_text_as_no_filter(text):
    place = _place("pub", osm_id=1, lat=51.0, lon=-1.0)
    result = CatalogSpatialIndex((place,), GraphSpatialIndex(_graph())).query(
        _request(
            text=text,
            route_geometry=None,
            policy={"basis": "none", "radius_m": None},
        )
    )

    assert result.places == (place,)


def test_catalog_query_returns_empty_for_text_without_match():
    place = _place("pub", osm_id=1, lat=51.0, lon=-1.0)
    result = CatalogSpatialIndex((place,), GraphSpatialIndex(_graph())).query(
        _request(
            text="museum",
            route_geometry=None,
            policy={"basis": "none", "radius_m": None},
        )
    )

    assert result.places == ()


def _segment_request(radius_m: float) -> CatalogPlacesRequest:
    return _request(
        route_geometry=None,
        segment_geometry={
            "type": "LineString",
            "coordinates": [[-1.1, 51.0], [-0.9, 51.0]],
        },
        policy={"basis": "segment", "radius_m": radius_m},
    )


def test_catalog_query_uses_full_source_geometry_for_segment_distance():
    place = _place(
        "pub",
        osm_id=1,
        lat=51.003,
        lon=-0.995,
        geometry=LineString([(-0.995, 51.0), (-0.995, 51.003)]),
    )

    result = CatalogSpatialIndex((place,), GraphSpatialIndex(_graph())).query(_segment_request(20))

    assert result.places == (place,)
    assert result.segment_distances[0] == pytest.approx(0, abs=0.1)
    assert result.full_route_distances == (None,)


def test_catalog_query_includes_exact_segment_radius_boundary():
    place = _place("pub", osm_id=1, lat=51.001, lon=-0.995)
    index = CatalogSpatialIndex((place,), GraphSpatialIndex(_graph()))
    wide = index.query(_segment_request(2_000))
    distance = wide.segment_distances[0]
    assert distance is not None

    exact = index.query(_segment_request(distance))
    outside = index.query(_segment_request(max(0, distance - 0.01)))

    assert exact.places == (place,)
    assert outside.places == ()


def test_catalog_query_returns_empty_when_segment_has_no_match():
    place = _place("pub", osm_id=1, lat=51.01, lon=-0.995)

    result = CatalogSpatialIndex((place,), GraphSpatialIndex(_graph())).query(_segment_request(10))

    assert result.places == ()
    assert result.segment_distances == ()


def test_catalog_query_orders_segment_matches_by_distance_then_identity():
    near = _place("pub", osm_id=9, lat=51.0001, lon=-0.995)
    tied_museum = _place("museum", osm_id=7, lat=51.001, lon=-0.995)
    tied_pub = _place(
        "pub",
        osm_id=2,
        lat=51.001,
        lon=-0.995,
        osm_type=OsmElementType.WAY,
    )
    request = _request(
        kinds=["pub", "museum"],
        route_geometry=None,
        segment_geometry={
            "type": "LineString",
            "coordinates": [[-1.1, 51.0], [-0.9, 51.0]],
        },
        policy={"basis": "segment", "radius_m": 2_000},
    )

    first = CatalogSpatialIndex(
        (tied_pub, near, tied_museum),
        GraphSpatialIndex(_graph()),
    ).query(request)
    second = CatalogSpatialIndex(
        (tied_museum, near, tied_pub),
        GraphSpatialIndex(_graph()),
    ).query(request)

    expected = [near.identity, tied_museum.identity, tied_pub.identity]
    assert [place.identity for place in first.places] == expected
    assert [place.identity for place in second.places] == expected
    assert list(first.segment_distances) == sorted(first.segment_distances)


def test_unbounded_catalog_query_orders_by_kind_and_osm_identity():
    node_pub = _place("pub", osm_id=9, lat=51.0, lon=-1.0)
    way_pub = _place(
        "pub",
        osm_id=2,
        lat=51.0,
        lon=-1.0,
        osm_type=OsmElementType.WAY,
    )
    museum = _place("museum", osm_id=7, lat=51.0, lon=-1.0)

    result = CatalogSpatialIndex(
        (node_pub, way_pub, museum),
        GraphSpatialIndex(_graph()),
    ).query(
        _request(
            kinds=["pub", "museum"],
            route_geometry=None,
            policy={"basis": "none", "radius_m": None},
        )
    )

    assert [place.identity for place in result.places] == [
        museum.identity,
        node_pub.identity,
        way_pub.identity,
    ]


def test_catalog_query_counts_segment_vertices_in_geometry_budget():
    index = CatalogSpatialIndex(
        (_place("pub", osm_id=1, lat=51.0, lon=-1.0),),
        GraphSpatialIndex(_graph()),
    )

    with pytest.raises(CatalogQueryLimitError, match="coordinate"):
        index.query(
            _request(
                route_geometry=None,
                segment_geometry={
                    "type": "LineString",
                    "coordinates": [[-1.0, 51.0], [-1.0, 51.0]] * 5_001,
                },
                policy={"basis": "segment", "radius_m": 1_000},
            )
        )
