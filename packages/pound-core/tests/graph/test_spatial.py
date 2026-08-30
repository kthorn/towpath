import copy
import math

import networkx as nx
import pytest  # pyright: ignore[reportMissingImports]
from pound.graph.spatial import (
    GraphSpatialIndex,
    PoiSpatialIndex,
    lat_lon_to_xy,
    spherical_envelopes,
)
from pound.models import OsmElementType, PoiCategory, RuntimePoi
from pound.schemas import GeoJSONLineString, MapBounds
from shapely.geometry import Point


def _graph() -> nx.Graph:
    graph = nx.Graph()
    graph.add_node(9, lat=51.0, lon=-1.0)
    graph.add_node(2, lat=51.0, lon=-0.99)
    graph.add_node(5, lat=51.01, lon=-0.99)
    graph.add_edge(9, 2, geometry=[(51.0, -1.0), (51.0, -0.99)])
    graph.add_edge(2, 5, geometry=[(51.0, -0.99), (51.01, -0.99)], navigable=False)
    return graph


def test_index_builds_stable_eligible_edge_mappings():
    index = GraphSpatialIndex(_graph())

    assert index.edge_keys == ((2, 9),)
    assert index.edge_tree is not None


def test_empty_index_has_no_trees_and_queries_empty():
    index = GraphSpatialIndex(nx.Graph())

    assert index.edge_tree is None
    with pytest.raises(ValueError, match="navigable edges"):
        index.project_to_nearest_edge(51, -1)


def test_edge_projection_returns_canonical_key_and_wgs84_point():
    index = GraphSpatialIndex(_graph())

    key, projected, distance = index.project_to_nearest_edge(51.001, -0.995)

    assert key == (2, 9)
    assert projected.y == pytest.approx(51.0, abs=2e-5)
    assert projected.x == pytest.approx(-0.995, abs=2e-5)
    assert distance == pytest.approx(111, abs=3)


def test_public_waterway_distance_accepts_normalized_geometry():
    index = GraphSpatialIndex(_graph())

    distance = index.distance_to_waterway(Point(-0.995, 51.001))

    assert distance == pytest.approx(111, abs=3)


def test_public_waterway_distance_returns_none_without_navigable_edges():
    index = GraphSpatialIndex(nx.Graph())

    assert index.distance_to_waterway(Point(-0.995, 51.001)) is None


def test_spherical_envelopes_split_antimeridian_and_cover_all_longitudes_at_pole():
    wrapped = spherical_envelopes(lon=179.9, lat=0, radius_m=30_000)
    polar = spherical_envelopes(lon=12, lat=89.9, radius_m=30_000)

    assert len(wrapped) == 2
    assert wrapped[0].bounds[0] == -180
    assert wrapped[1].bounds[2] == 180
    assert len(polar) == 1
    assert polar[0].bounds[0] == -180
    assert polar[0].bounds[2] == 180


def test_spherical_envelope_whole_world_and_named_axis_helper():
    envelopes = spherical_envelopes(lon=123, lat=-45, radius_m=math.pi * 6_371_000)

    assert envelopes[0].bounds == (-180.0, -90.0, 180.0, 90.0)
    assert lat_lon_to_xy(lat=12.5, lon=-7.25) == (-7.25, 12.5)


def test_index_construction_and_queries_do_not_mutate_graph_or_index():
    graph = _graph()
    graph_before = copy.deepcopy(graph)
    index = GraphSpatialIndex(graph)
    state = (index.edge_keys, index.edge_lines)

    first = index.project_to_nearest_edge(51.0, -0.995)
    second = index.project_to_nearest_edge(51.0, -0.995)

    assert first == second
    assert (index.edge_keys, index.edge_lines) == state
    assert nx.utils.graphs_equal(graph, graph_before)


def _poi(
    kind: str,
    lat: float,
    lon: float,
    osm_id: int = 1,
    category: PoiCategory = PoiCategory.PROVISIONS,
) -> RuntimePoi:
    return RuntimePoi(
        osm_type=OsmElementType.NODE,
        osm_id=osm_id,
        category=category,
        kind=kind,
        name=f"{kind} name",
        lat=lat,
        lon=lon,
    )


def _line(points: list[tuple[float, float]]) -> GeoJSONLineString:
    return GeoJSONLineString(coordinates=[(lon, lat) for lat, lon in points])


def test_poi_spatial_index_filters_kind_viewport_and_route_corridor():
    index = PoiSpatialIndex(
        (
            _poi("pub", 51.0, -1.0),
            _poi("pub", 51.02, -1.0, 4),
            _poi("pub", 52.0, -2.0, 2),
            _poi("marina", 51.0, -1.0, 3),
        )
    )
    result = index.query(
        bounds=MapBounds(south=50.9, west=-1.1, north=51.1, east=-0.9),
        route_geometry=_line([(51.0, -1.1), (51.0, -0.9)]),
        kinds=("pub",),
    )
    assert [poi.kind for poi in result.pois] == ["pub"]


def test_poi_spatial_index_returns_over_cap_without_points():
    pois = tuple(_poi("pub", 51.0 + index * 0.000001, -1.0, index + 1) for index in range(1001))
    result = PoiSpatialIndex(pois).query(
        bounds=MapBounds(south=50.9, west=-1.1, north=51.1, east=-0.9),
        route_geometry=_line([(51.0, -1.1), (51.0, -0.9)]),
        kinds=("pub",),
    )
    assert not result.pois
    assert result.zoom_in_required
    assert result.matching_count == 1001


@pytest.mark.parametrize(
    ("category", "latitude_offset", "expected_match"),
    [
        (PoiCategory.CANAL_SERVICE, 0.002, True),
        (PoiCategory.CANAL_SERVICE, 0.003, False),
        (PoiCategory.PROVISIONS, 0.008, True),
        (PoiCategory.PROVISIONS, 0.010, False),
    ],
)
def test_poi_spatial_index_applies_250m_and_1000m_corridors(
    category: PoiCategory, latitude_offset: float, expected_match: bool
):
    index = PoiSpatialIndex((_poi("fuel", 51.0 + latitude_offset, -1.0, category=category),))
    result = index.query(
        bounds=MapBounds(south=50.9, west=-1.1, north=51.02, east=-0.9),
        route_geometry=_line([(51.0, -1.1), (51.0, -0.9)]),
        kinds=("fuel",),
    )

    assert bool(result.pois) is expected_match
