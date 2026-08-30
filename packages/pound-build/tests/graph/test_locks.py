import json

import networkx as nx
import pytest
from fixtures import oxford_fixture_path, staircase_fixture_path
from pound_build.graph.build import build_graph
from pound_build.graph.locks import attach_locks
from pound_build.ingest.ir import NodeKind, WaterwayFeatures, WaterwayNode
from pound_build.ingest.overpass import parse


def _oxford():
    try:
        with open(oxford_fixture_path()) as f:
            return parse(json.load(f)["elements"], None)
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(f"Failed to load Oxford fixture: {e}") from e


def _staircase():
    try:
        with open(staircase_fixture_path()) as f:
            return parse(json.load(f)["elements"], None)
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(f"Failed to load staircase fixture: {e}") from e


# --- Oxford fixture ---


def test_lock_way_sets_edge_locks():
    g, report = attach_locks(build_graph(_oxford()), _oxford())
    edge = next(d for _, _, d in g.edges(data=True) if d["osm_way_id"] == 1003)
    assert edge["locks"] == 1
    assert report["lock_ways_attached"] == 1


def test_attach_locks_retains_source_lock_point():
    features = _oxford()
    graph = build_graph(features)
    graph, _ = attach_locks(graph, features, in_place=True)

    lock_edges = [data for _, _, data in graph.edges(data=True) if data.get("locks")]
    lock_node = next(node for node in features.nodes if node.kind.value == "lock")
    expected_point = (lock_node.lat, lock_node.lon)
    assert lock_edges
    assert len(lock_edges[0]["lock_points"]) == 1
    assert lock_edges[0]["lock_points"][0] == expected_point


def test_lock_node_in_middle_of_segment_projects_onto_edge_line():
    graph = nx.Graph()
    graph.add_node(1, lat=51.0, lon=-1.0)
    graph.add_node(2, lat=51.0, lon=-0.99)
    graph.add_edge(
        1,
        2,
        geometry=[(51.0, -1.0), (51.0, -0.99)],
        kind="canal",
        length_m=700.0,
        locks=0,
        osm_way_id=1,
    )
    features = WaterwayFeatures(
        ways=[],
        nodes=[
            WaterwayNode(
                osm_id=999,
                lat=51.0001,
                lon=-0.995,
                tags={"lock": "yes"},
                kind=NodeKind.LOCK,
            )
        ],
        source="overpass",
        fetched_at="",
        bbox=None,
    )

    attached, report = attach_locks(graph, features, in_place=True)

    point = attached.edges[1, 2]["lock_points"][0]
    assert report["lock_nodes_attached"] == 1
    assert point[0] == pytest.approx(51.0, abs=2e-7)
    assert point[1] == pytest.approx(-0.995, abs=1e-7)


def test_lock_node_at_endpoint_attaches_to_edge():
    # node 2002 (lock=yes) sits at 51.7540,-1.2640 == end of way 1003
    g, report = attach_locks(build_graph(_oxford()), _oxford())
    assert report["lock_nodes_attached"] >= 1
    edge = next(d for _, _, d in g.edges(data=True) if d["osm_way_id"] == 1003)
    assert edge["locks"] == 1  # idempotent: lock way + lock node same edge => 1


def test_lock_gate_node_counted_but_not_incrementing():
    g, report = attach_locks(build_graph(_oxford()), _oxford())
    assert report["lock_gate_nodes"] == 1  # node 2001
    edge = next(d for _, _, d in g.edges(data=True) if d["osm_way_id"] == 1003)
    assert edge["locks"] == 1  # gate doesn't add a second lock


def test_non_lock_edges_have_zero_locks():
    g, _ = attach_locks(build_graph(_oxford()), _oxford())
    for _, _, d in g.edges(data=True):
        if d["osm_way_id"] in (1001, 1002, 1006, 1007):
            assert d["locks"] == 0


def test_orphan_locks_reported():
    _, report = attach_locks(build_graph(_oxford()), _oxford())
    assert report["orphan_lock_ways"] == []
    assert report["orphan_lock_nodes"] == []


def test_attach_locks_is_pure_by_default():
    features = _oxford()
    graph = build_graph(features)

    attached, _ = attach_locks(graph, features)

    assert attached is not graph
    assert sum(data["locks"] for _, _, data in graph.edges(data=True)) == 0
    assert sum(data["locks"] for _, _, data in attached.edges(data=True)) > 0


def test_attach_locks_can_mutate_a_build_owned_graph_in_place():
    features = _oxford()
    graph = build_graph(features)

    attached, _ = attach_locks(graph, features, in_place=True)

    assert attached is graph
    assert sum(data["locks"] for _, _, data in graph.edges(data=True)) > 0


# --- Staircase fixture (the bug the Task 3 classify_way fix existed to catch) ---


def test_staircase_counts_three_locks():
    """Three chambers (canal+lock=yes ways) => three LOCK edges => 3 locks.

    Without the Task 3 classify_way fix these ways would be CANAL and the
    staircase would count as 0 locks. This test proves the fix end-to-end.
    """
    features = _staircase()
    g, report = attach_locks(build_graph(features), features)
    lock_edges = [d for _, _, d in g.edges(data=True) if d["locks"] >= 1]
    assert len(lock_edges) == 3
    assert sum(d["locks"] for _, _, d in g.edges(data=True)) == 3
    assert report["lock_ways_attached"] == 3


def test_staircase_chambers_chain_into_one_component():
    features = _staircase()
    g, _ = attach_locks(build_graph(features), features)
    # 3 chambers sharing endpoints => 4 nodes, 3 edges, one component
    assert g.number_of_nodes() == 4
    assert g.number_of_edges() == 3
    import networkx as nx

    assert nx.number_connected_components(g) == 1


def test_staircase_lock_gate_counted_not_incrementing():
    features = _staircase()
    g, report = attach_locks(build_graph(features), features)
    # 4 gate nodes now (6004 bottom entrance, 6003 chamber1/2 boundary, 6005
    # chamber2/3 boundary, 6006 top exit) — the Step 6b augmentation. They drive
    # the flight's chamber count (G=4 -> 3 chambers), one lock per chamber's
    # downstream-gate segment; gates themselves still don't increment beyond
    # that (no double-counting).
    assert report["lock_gate_nodes"] == 4
    assert sum(d["locks"] for _, _, d in g.edges(data=True)) == 3
