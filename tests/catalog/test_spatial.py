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
) -> CatalogPlace:
    geometry = geometry or Point(lon, lat)
    return CatalogPlace(
        osm_type=OsmElementType.NODE,
        osm_id=osm_id,
        kind=kind,
        name=f"{kind} {osm_id}",
        lat=lat,
        lon=lon,
        metadata=CatalogMetadata(name=f"{kind} {osm_id}"),
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
