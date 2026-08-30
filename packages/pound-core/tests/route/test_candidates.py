import copy
import random
from collections.abc import Sequence
from typing import get_origin, get_type_hints

import networkx as nx
import pytest
from pound.geometry import haversine_m as _haversine_m
from pound.graph.spatial import GraphSpatialIndex
from pound.route.candidates import nearest_coord_candidates, select_spaced_candidates
from pound.schemas import CanalCandidate, Coordinate


def _candidate(uid: int, lat: float, lon: float, distance: float) -> CanalCandidate:
    return CanalCandidate(
        uid=uid,
        artifact_revision="rev-1",
        coordinate=Coordinate(lat=lat, lon=lon),
        straight_line_distance_m=distance,
        display_name=f"Point {uid}",
    )


def test_nearest_candidates_orders_by_distance_then_uid_and_truncates():
    graph = nx.Graph()
    graph.add_node(3, lat=51.0, lon=0.001)
    graph.add_node(1, lat=51.0, lon=-0.001)
    graph.add_node(2, lat=51.0, lon=0.003)

    result = nearest_coord_candidates(
        51.0, 0.0, graph, GraphSpatialIndex(graph), artifact_revision="r7", limit=2
    )

    assert [candidate.uid for candidate in result] == [1, 3]
    assert all(candidate.artifact_revision == "r7" for candidate in result)
    assert result[0].coordinate == Coordinate(lat=51.0, lon=-0.001)


@pytest.mark.parametrize("limit", [0, -1])
def test_nearest_candidates_rejects_nonpositive_limit(limit):
    with pytest.raises(ValueError, match="limit"):
        graph = nx.Graph()
        nearest_coord_candidates(
            0, 0, graph, GraphSpatialIndex(graph), artifact_revision="r", limit=limit
        )


def test_nearest_candidates_returns_empty_for_empty_graph():
    graph = nx.Graph()
    assert (
        nearest_coord_candidates(
            0, 0, graph, GraphSpatialIndex(graph), artifact_revision="r", limit=3
        )
        == []
    )


def test_nearest_candidates_uses_node_name_then_edge_name_then_fallback():
    graph = nx.Graph()
    graph.add_node(1, lat=51.0, lon=0.0, name="  Node Name  ")
    graph.add_node(2, lat=51.0, lon=0.01, name="   ")
    graph.add_node(3, lat=51.0, lon=0.02)
    graph.add_node(4, lat=51.0, lon=0.03)
    graph.add_edge(1, 2, name="Zulu Canal")
    graph.add_edge(2, 3, name="  Alpha Canal ")
    graph.add_edge(2, 4, name="Alpha Canal")
    graph.add_edge(3, 4, name="  ")

    result = nearest_coord_candidates(
        51.0, 0.0, graph, GraphSpatialIndex(graph), artifact_revision="r", limit=4
    )
    names = {candidate.uid: candidate.display_name for candidate in result}

    assert names == {
        1: "Node Name",
        2: "Alpha Canal",
        3: "Alpha Canal",
        4: "Alpha Canal",
    }

    isolated = nx.Graph()
    isolated.add_node(9, lat=51.0, lon=0.0)
    assert (
        nearest_coord_candidates(
            51.0,
            0.0,
            isolated,
            GraphSpatialIndex(isolated),
            artifact_revision="r",
            limit=1,
        )[0].display_name
        == "Unnamed canal point"
    )


def test_nearest_candidates_does_not_mutate_graph():
    graph = nx.Graph()
    graph.add_node(1, lat=51.0, lon=0.0, metadata={"source": "fixture"})
    before = copy.deepcopy(graph)

    index = GraphSpatialIndex(graph)
    nearest_coord_candidates(51.0, 0.0, graph, index, artifact_revision="r", limit=1)

    assert nx.utils.graphs_equal(graph, before)


@pytest.mark.parametrize(
    ("query", "nodes", "limit"),
    [
        ((89.9, 35.0), [(4, 89.8, -145.0), (1, 89.85, 40.0), (3, 89.7, 35.0)], 9),
        ((0.0, 179.95), [(5, 0.0, -179.9), (2, 0.0, 179.8), (8, 0.0, 170.0)], 2),
        ((0.0, 0.0), [(7, 0.0, -0.01), (3, 0.0, 0.01)], 2),
    ],
)
def test_indexed_candidates_equal_exhaustive_for_spherical_edge_cases(query, nodes, limit):
    graph = nx.Graph()
    for uid, lat, lon in nodes:
        graph.add_node(uid, lat=lat, lon=lon)
    index = GraphSpatialIndex(graph)

    result = nearest_coord_candidates(*query, graph, index, artifact_revision="r", limit=limit)
    exhaustive = sorted(
        nodes,
        key=lambda node: (
            _haversine_m(query, (node[1], node[2])),
            node[0],
        ),
    )[:limit]

    assert [candidate.uid for candidate in result] == [node[0] for node in exhaustive]


def test_indexed_candidates_expand_multiple_radii_and_reuse_index(monkeypatch):
    graph = nx.Graph()
    graph.add_node(1, lat=0.0, lon=0.1)
    graph.add_node(2, lat=0.0, lon=0.2)
    index = GraphSpatialIndex(graph)
    calls = 0
    original = GraphSpatialIndex.query_node_uids

    def counting_query(self, envelopes):
        nonlocal calls
        if self is index:
            calls += 1
        return original(self, envelopes)

    monkeypatch.setattr(GraphSpatialIndex, "query_node_uids", counting_query)
    result = nearest_coord_candidates(0, 0, graph, index, artifact_revision="r", limit=2)

    assert [candidate.uid for candidate in result] == [1, 2]
    assert calls >= 3


def test_indexed_candidates_equal_exhaustive_on_seeded_random_graph():
    randomizer = random.Random(90210)
    graph = nx.Graph()
    for uid in range(100):
        graph.add_node(
            uid,
            lat=randomizer.uniform(-89.9, 89.9),
            lon=randomizer.uniform(-180, 180),
        )
    query = (randomizer.uniform(-89.9, 89.9), randomizer.uniform(-180, 180))

    result = nearest_coord_candidates(
        *query, graph, GraphSpatialIndex(graph), artifact_revision="r", limit=17
    )
    exhaustive = sorted(
        graph.nodes,
        key=lambda uid: (
            _haversine_m(
                query,
                (graph.nodes[uid]["lat"], graph.nodes[uid]["lon"]),
            ),
            uid,
        ),
    )[:17]

    assert [candidate.uid for candidate in result] == exhaustive


def test_indexed_candidates_queries_whole_world_once_before_termination(monkeypatch):
    graph = nx.Graph()
    graph.add_node(1, lat=0.0, lon=180.0)
    index = GraphSpatialIndex(graph)
    original = GraphSpatialIndex.query_node_uids
    world_queries = 0

    def counting_query(self, envelopes):
        nonlocal world_queries
        if self is index and envelopes[0].bounds == (-180.0, -90.0, 180.0, 90.0):
            world_queries += 1
        return original(self, envelopes)

    monkeypatch.setattr(GraphSpatialIndex, "query_node_uids", counting_query)

    result = nearest_coord_candidates(0, 0, graph, index, artifact_revision="r", limit=1)

    assert [candidate.uid for candidate in result] == [1]
    assert world_queries == 1


def test_spacing_zero_returns_raw_nearest_candidates_up_to_cap():
    candidates = [_candidate(i, 51.0, i / 1000, float(i)) for i in range(4)]

    result = select_spaced_candidates(candidates, destination_limit=3, minimum_spacing_m=0)

    assert result == candidates[:3]


def test_spacing_always_retains_nearest_and_skips_point_near_any_retained():
    candidates = [
        _candidate(1, 51.0, 0.0, 0),
        _candidate(2, 51.0, 0.0001, 10),
        _candidate(3, 51.0, 0.002, 20),
        _candidate(4, 51.0, 0.0021, 30),
        _candidate(5, 51.0, 0.004, 40),
    ]

    result = select_spaced_candidates(candidates, destination_limit=3, minimum_spacing_m=100)

    assert [candidate.uid for candidate in result] == [1, 3, 5]


def test_spacing_honors_configured_cap():
    candidates = [_candidate(i, 51.0, i / 100, float(i)) for i in range(4)]
    assert len(select_spaced_candidates(candidates, destination_limit=2, minimum_spacing_m=1)) == 2


@pytest.mark.parametrize(
    ("destination_limit", "minimum_spacing_m"),
    [(0, 0), (-1, 0), (1, -0.1)],
)
def test_spacing_rejects_invalid_settings(destination_limit, minimum_spacing_m):
    with pytest.raises(ValueError):
        select_spaced_candidates(
            [],
            destination_limit=destination_limit,
            minimum_spacing_m=minimum_spacing_m,
        )


def test_spacing_does_not_mutate_input():
    candidates = [_candidate(1, 51.0, 0.0, 0), _candidate(2, 51.0, 0.001, 1)]
    before = copy.deepcopy(candidates)

    select_spaced_candidates(candidates, destination_limit=1, minimum_spacing_m=10)

    assert candidates == before


def test_spacing_accepts_tuple_sequence_without_mutating_it():
    candidates = (
        _candidate(1, 51.0, 0.0, 0),
        _candidate(2, 51.0, 0.002, 1),
    )

    result = select_spaced_candidates(candidates, destination_limit=2, minimum_spacing_m=100)

    assert result == list(candidates)
    assert isinstance(candidates, tuple)
    assert get_origin(get_type_hints(select_spaced_candidates)["candidates"]) is Sequence
