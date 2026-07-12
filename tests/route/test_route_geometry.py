import copy

import networkx as nx

from pound.ingest.ir import WayDimensions
from pound.route.plan import _to_geojson, plan_canal_route
from pound.schemas import ResolvedConstraints


def _three_node_graph() -> nx.Graph:
    graph = nx.Graph(fetched_at="2026-07-11T00:00:00Z")
    graph.add_node(1, lat=51.0, lon=-1.0, name="Start")
    graph.add_node(2, lat=51.1, lon=-1.1, name="Middle")
    graph.add_node(3, lat=51.2, lon=-1.2, name="End")
    dimensions = WayDimensions()
    graph.add_edge(
        1,
        2,
        length_m=100.0,
        locks=0,
        dimensions=dimensions,
        osm_way_id=12,
        geometry=[(51.0, -1.0), (51.1, -1.1)],
    )
    graph.add_edge(
        2,
        3,
        length_m=100.0,
        locks=0,
        dimensions=dimensions,
        osm_way_id=23,
        geometry=[(51.2, -1.2), (51.1, -1.1)],
    )
    return graph


def test_plan_canal_route_orients_and_joins_geometry_in_traversal_order():
    graph = _three_node_graph()
    before = copy.deepcopy(graph)

    response = plan_canal_route(ResolvedConstraints(start_uid=1, end_uid=3), graph=graph)

    assert [leg.from_place for leg in response.route.legs] == ["Start", "Middle"]
    assert response.geometry.type == "LineString"
    assert response.geometry.coordinates == [
        (-1.0, 51.0),
        (-1.1, 51.1),
        (-1.2, 51.2),
    ]
    assert graph.nodes == before.nodes
    assert graph.edges == before.edges


def test_plan_canal_route_reverses_geometry_with_the_route():
    graph = _three_node_graph()

    response = plan_canal_route(ResolvedConstraints(start_uid=3, end_uid=1), graph=graph)

    assert [leg.from_place for leg in response.route.legs] == ["End", "Middle"]
    assert response.geometry.coordinates == [
        (-1.2, 51.2),
        (-1.1, 51.1),
        (-1.0, 51.0),
    ]


def test_to_geojson_swaps_internal_lat_lon_coordinates():
    geometry = _to_geojson([(51.0, -1.0), (51.1, -1.1)])

    assert geometry.type == "LineString"
    assert geometry.coordinates == [(-1.0, 51.0), (-1.1, 51.1)]


def test_reverse_route_orients_high_precision_variable_length_geometry():
    graph = nx.Graph(fetched_at="2026-07-11T00:00:00Z")
    graph.add_node(1, lat=51.1234568, lon=-1.1234568, name="Start")
    graph.add_node(2, lat=51.2234568, lon=-1.2234568, name="End")
    graph.add_edge(
        1,
        2,
        length_m=100.0,
        locks=0,
        dimensions=WayDimensions(),
        osm_way_id=12,
        geometry=[
            (51.123456789, -1.123456789),
            (51.173456789, -1.173456789),
            (51.223456789, -1.223456789),
        ],
    )

    response = plan_canal_route(ResolvedConstraints(start_uid=2, end_uid=1), graph=graph)

    assert response.geometry.coordinates == [
        (-1.223456789, 51.223456789),
        (-1.173456789, 51.173456789),
        (-1.123456789, 51.123456789),
    ]
