import copy

import networkx as nx
import pytest
from pound.geometry import haversine_m as _haversine_m
from pound.graph.spatial import CandidateSpatialIndex
from pound.route import candidates as candidate_module
from pound.route.candidates import nearest_candidates
from pound.route.project import project_handle
from pound.schemas import CanalPointHandle, Coordinate
from shapely.strtree import STRtree


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


def test_nearest_candidates_queries_only_bounded_sample_envelope(monkeypatch):
    graph = _graph()
    graph.add_node(10, lat=52.0, lon=-2.0)
    graph.add_node(11, lat=52.0, lon=-1.985)
    graph.add_edge(
        10,
        11,
        geometry=[(52.0, -2.0), (52.0, -1.985)],
        candidate_eligible=True,
    )
    index = CandidateSpatialIndex(graph)
    queried_bounds = []
    original_query = STRtree.query

    def record_query(tree, geometry, *args, **kwargs):
        if tree is index.candidate_wgs84_tree:
            queried_bounds.append(geometry.bounds)
        return original_query(tree, geometry, *args, **kwargs)

    monkeypatch.setattr(STRtree, "query", record_query)
    nearest_candidates(51.0, -1.0, index, limit=1)

    assert queried_bounds
    assert queried_bounds[0][2] - queried_bounds[0][0] < 0.01


def test_nearest_candidates_reports_and_orders_exact_haversine_distances():
    graph = nx.Graph()
    graph.add_node(1, lat=51.0, lon=-1.0)
    graph.add_node(2, lat=51.001, lon=-1.0)
    graph.add_node(3, lat=51.02, lon=-1.02)
    graph.add_node(4, lat=51.021, lon=-1.02)
    graph.add_edge(1, 2, geometry=[(51.0, -1.0), (51.001, -1.0)], candidate_eligible=False)
    graph.add_edge(3, 4, geometry=[(51.02, -1.02), (51.021, -1.02)], candidate_eligible=False)
    index = CandidateSpatialIndex(graph, spacing_m=1)
    query = (51.0, -1.0)

    result = nearest_candidates(*query, index, limit=4)
    expected = sorted(
        index.candidate_points,
        key=lambda point: _haversine_m(query, (point.coordinate.lat, point.coordinate.lon)),
    )

    assert [candidate.candidate_id for candidate in result] == [
        candidate_module.candidate_id(point) for point in expected
    ]
    assert [candidate.straight_line_distance_m for candidate in result] == pytest.approx(
        [_haversine_m(query, (point.coordinate.lat, point.coordinate.lon)) for point in expected]
    )


def test_candidate_index_is_deeply_immutable():
    index = CandidateSpatialIndex(_graph())

    with pytest.raises(TypeError):
        index.edge_positions[(1, 2)] = 99
    with pytest.raises((TypeError, ValueError)):
        index.candidate_points[0].coordinate.lat = 0


def test_legacy_candidate_bridge_uses_shared_index_without_rebuilding(monkeypatch):
    index = CandidateSpatialIndex(_graph())

    def fail_rebuild(*args, **kwargs):
        raise AssertionError("candidate index rebuilt")

    monkeypatch.setattr(candidate_module, "CandidateSpatialIndex", fail_rebuild)
    result = candidate_module.nearest_coord_candidates(
        51.0, -1.0, index, artifact_revision="revision", limit=1
    )

    assert len(result) == 1
