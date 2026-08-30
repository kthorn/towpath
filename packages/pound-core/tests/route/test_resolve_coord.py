import networkx as nx
import pytest  # pyright: ignore[reportMissingImports]
from pound.graph.spatial import CandidateSpatialIndex
from pound.route.resolve import resolve_coord
from pound.schemas import CanalPointHandle


def _resolve(lat: float, lon: float, graph: nx.Graph) -> tuple[CanalPointHandle, float]:
    return resolve_coord(lat, lon, graph, CandidateSpatialIndex(graph))


def _graph() -> nx.Graph:
    graph = nx.Graph()
    graph.add_node(1, lat=51.0, lon=-1.0)
    graph.add_node(2, lat=51.0, lon=-0.98)
    graph.add_edge(1, 2, geometry=[(51.0, -1.0), (51.0, -0.98)])
    return graph


def test_resolve_coord_projects_midpoint_to_canonical_edge():
    graph = _graph()

    handle, distance = _resolve(51.0, -0.99, graph)

    assert handle.edge == (1, 2)
    assert handle.fraction == pytest.approx(0.5, abs=2e-6)
    assert distance == pytest.approx(0, abs=0.1)


def test_resolve_coord_returns_projected_endpoint_for_exact_coordinate():
    graph = _graph()

    handle, distance = _resolve(51.0, -1.0, graph)

    assert handle.edge == (1, 2)
    assert handle.fraction == 0
    assert distance == 0


def test_resolve_coord_empty_graph_raises():
    graph = nx.Graph()

    with pytest.raises(ValueError, match="no navigable edges"):
        _resolve(51.75, -1.26, graph)
