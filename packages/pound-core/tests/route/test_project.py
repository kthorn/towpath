import math

import networkx as nx
import pytest
from pound.graph.spatial import CandidateSpatialIndex
from pound.route.project import project_handle
from pound.schemas import CanalPointHandle, Coordinate, ProjectedCanalPoint


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


def test_handle_requires_canonical_finite_fraction_in_range():
    with pytest.raises(ValueError, match="canonical order"):
        CanalPointHandle(edge=(2, 1), fraction=0.5)
    for fraction in (-0.1, 1.1, math.inf, math.nan):
        with pytest.raises(ValueError, match="finite"):
            CanalPointHandle(edge=(1, 2), fraction=fraction)


def test_project_handle_returns_exact_metric_mid_edge_coordinate():
    graph = _graph()
    projected = project_handle(CanalPointHandle(edge=(1, 2), fraction=0.5), graph)

    assert isinstance(projected, ProjectedCanalPoint)
    assert projected.handle == CanalPointHandle(edge=(1, 2), fraction=0.5)
    assert projected.coordinate.lat == pytest.approx(51.0, abs=3e-7)
    assert projected.coordinate.lon == pytest.approx(-0.9925, abs=3e-7)


def test_fixed_samples_use_250_metre_intervals_and_canonical_handles():
    index = CandidateSpatialIndex(_graph())
    samples = sorted(
        (point for point in index.candidate_points if point.handle.edge == (1, 2)),
        key=lambda point: point.handle.fraction,
    )
    edge_position = index.edge_keys.index((1, 2))
    edge_length = index.edge_lines[edge_position].length
    distances = [point.handle.fraction * edge_length for point in samples]

    assert distances[0] == pytest.approx(0)
    assert distances[1:-1] == pytest.approx([250, 500, 750, 1000], abs=1e-6)
    assert distances[-1] == pytest.approx(index.edge_lines[index.edge_keys.index((1, 2))].length)


def test_index_deduplicates_shared_junction_and_keeps_infrastructure_endpoints_only():
    index = CandidateSpatialIndex(_graph())

    junctions = [
        point
        for point in index.endpoint_points
        if point.coordinate == Coordinate(lat=51.0, lon=-0.985)
    ]
    infrastructure = [point for point in index.candidate_points if point.handle.edge == (2, 3)]
    assert len(junctions) == 1
    assert [point.handle.fraction for point in infrastructure] in ([1.0], [0.0, 1.0])
