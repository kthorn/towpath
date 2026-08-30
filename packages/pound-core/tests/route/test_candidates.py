import copy

import networkx as nx
import pytest
from pound.graph.spatial import CandidateSpatialIndex
from pound.route.candidates import nearest_candidates
from pound.route.project import project_handle
from pound.schemas import CanalPointHandle, Coordinate


def _graph() -> nx.Graph:
    graph = nx.Graph()
    graph.add_node(1, lat=51.0, lon=-1.0, name="Start")
    graph.add_node(2, lat=51.0, lon=-0.985, name="Junction")
    graph.add_node(3, lat=51.0, lon=-0.97, name="End")
    graph.add_edge(
        1,
        2,
        geometry=[(51.0, -1.0), (51.0, -0.985)],
        candidate_eligible=True,
        name="Eligible reach",
    )
    graph.add_edge(
        2,
        3,
        geometry=[(51.0, -0.985), (51.0, -0.97)],
        candidate_eligible=False,
        name="Lock reach",
        locks=1,
    )
    return graph


def test_nearest_candidates_includes_exact_projection_and_deterministic_id():
    graph = _graph()
    index = CandidateSpatialIndex(graph)
    handle = CanalPointHandle(edge=(1, 2), fraction=0.5)
    projected = project_handle(handle, graph)

    result = nearest_candidates(projected.coordinate.lat, projected.coordinate.lon, index, limit=1)

    assert result[0].handle.edge == handle.edge
    assert result[0].handle.fraction == pytest.approx(handle.fraction, abs=2e-6)
    assert result[0].coordinate.lat == pytest.approx(projected.coordinate.lat, abs=3e-7)
    assert result[0].coordinate.lon == pytest.approx(projected.coordinate.lon, abs=3e-7)
    assert result[0].candidate_id == f"1:2:{result[0].handle.fraction:.12f}"
    assert result[0].straight_line_distance_m == pytest.approx(0, abs=0.01)


def test_nearest_candidates_rejects_nonpositive_limit():
    with pytest.raises(ValueError, match="limit"):
        nearest_candidates(51.0, -1.0, CandidateSpatialIndex(_graph()), limit=0)


def test_candidate_index_is_repeatable_and_does_not_mutate_graph():
    graph = _graph()
    before = copy.deepcopy(graph)
    first = nearest_candidates(51.0, -0.99, CandidateSpatialIndex(graph), limit=5)
    second = nearest_candidates(51.0, -0.99, CandidateSpatialIndex(graph), limit=5)

    assert first == second
    assert nx.utils.graphs_equal(graph, before)


def test_candidate_ids_and_coordinates_are_unique_at_shared_junction():
    index = CandidateSpatialIndex(_graph())
    result = nearest_candidates(51.0, -0.985, index, limit=20)

    assert len({candidate.candidate_id for candidate in result}) == len(result)
    assert (
        sum(candidate.coordinate == Coordinate(lat=51.0, lon=-0.985) for candidate in result) == 1
    )


def test_candidates_keep_infrastructure_endpoints_but_not_interiors():
    result = nearest_candidates(51.0, -0.975, CandidateSpatialIndex(_graph()), limit=20)

    infrastructure = [candidate for candidate in result if candidate.handle.edge == (2, 3)]
    assert all(candidate.handle.fraction in (0.0, 1.0) for candidate in infrastructure)
