import copy
from collections.abc import Sequence
from typing import get_origin, get_type_hints

import networkx as nx
import pytest

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

    result = nearest_coord_candidates(51.0, 0.0, graph, artifact_revision="r7", limit=2)

    assert [candidate.uid for candidate in result] == [1, 3]
    assert all(candidate.artifact_revision == "r7" for candidate in result)
    assert result[0].coordinate == Coordinate(lat=51.0, lon=-0.001)


@pytest.mark.parametrize("limit", [0, -1])
def test_nearest_candidates_rejects_nonpositive_limit(limit):
    with pytest.raises(ValueError, match="limit"):
        nearest_coord_candidates(0, 0, nx.Graph(), artifact_revision="r", limit=limit)


def test_nearest_candidates_returns_empty_for_empty_graph():
    assert nearest_coord_candidates(0, 0, nx.Graph(), artifact_revision="r", limit=3) == []


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

    result = nearest_coord_candidates(51.0, 0.0, graph, artifact_revision="r", limit=4)
    names = {candidate.uid: candidate.display_name for candidate in result}

    assert names == {
        1: "Node Name",
        2: "Alpha Canal",
        3: "Alpha Canal",
        4: "Alpha Canal",
    }

    isolated = nx.Graph()
    isolated.add_node(9, lat=51.0, lon=0.0)
    assert nearest_coord_candidates(
        51.0, 0.0, isolated, artifact_revision="r", limit=1
    )[0].display_name == "Unnamed canal point"


def test_nearest_candidates_does_not_mutate_graph():
    graph = nx.Graph()
    graph.add_node(1, lat=51.0, lon=0.0, metadata={"source": "fixture"})
    before = copy.deepcopy(graph)

    nearest_coord_candidates(51.0, 0.0, graph, artifact_revision="r", limit=1)

    assert nx.utils.graphs_equal(graph, before)


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
