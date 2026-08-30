import networkx as nx
import pytest
from pound.web.network import prepare_network_geometry


@pytest.fixture
def graph() -> nx.Graph:
    graph = nx.Graph()
    graph.add_edge(
        1,
        2,
        geometry=[(51.0, -1.0), (51.05, -1.05), (51.1, -1.1)],
    )
    graph.add_edge(2, 3, geometry=[(51.1, -1.1), (51.1, -1.2)])
    graph.add_edge(2, 4, geometry=[(51.1, -1.1), (51.2, -1.1)])
    return graph


def test_prepare_network_geometry_preserves_branches_and_geojson_order(graph):
    lines = prepare_network_geometry(graph)

    coordinates = [coordinate for line in lines for coordinate in line.coordinates]
    assert len(coordinates) <= 100_000
    assert all(len(coordinate) == 2 for coordinate in coordinates)
    assert any((-1.0, 51.0) in line.coordinates for line in lines)
    assert any((-1.1, 51.1) in line.coordinates for line in lines)
    assert any((-1.2, 51.1) in line.coordinates for line in lines)
    assert any((-1.1, 51.2) in line.coordinates for line in lines)


def test_prepare_network_geometry_respects_vertex_ceiling_and_endpoints():
    graph = nx.Graph()
    graph.add_edge(
        1,
        2,
        geometry=[(51.0, -1.0), (51.01, -1.01), (51.02, -1.02)],
    )
    graph.add_edge(
        2,
        3,
        geometry=[(51.02, -1.02), (51.03, -1.03), (51.04, -1.04)],
    )
    graph.add_edge(
        3,
        4,
        geometry=[(51.04, -1.04), (51.05, -1.05), (51.06, -1.06)],
    )
    graph.add_edge(5, 6, geometry=[(51.2, -1.2), (51.2, -1.3)])

    lines = prepare_network_geometry(graph, max_vertices=4)

    coordinates = [coordinate for line in lines for coordinate in line.coordinates]
    assert len(coordinates) <= 4
    assert (-1.0, 51.0) in coordinates
    assert (-1.06, 51.06) in coordinates
    assert (-1.2, 51.2) in coordinates
    assert (-1.3, 51.2) in coordinates
