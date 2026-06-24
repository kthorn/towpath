import json

from pound.graph.locks import attach_locks

from pound.graph.build import build_graph
from pound.ingest.overpass import parse
from tests.fixtures import oxford_fixture_path, staircase_fixture_path


def _oxford():
    with open(oxford_fixture_path()) as f:
        return parse(json.load(f)["elements"], None)


def _staircase():
    with open(staircase_fixture_path()) as f:
        return parse(json.load(f)["elements"], None)


# --- Oxford fixture ---


def test_lock_way_sets_edge_locks():
    g, report = attach_locks(build_graph(_oxford()), _oxford())
    edge = next(d for _, _, d in g.edges(data=True) if d["osm_way_id"] == 1003)
    assert edge["locks"] == 1
    assert report["lock_ways_attached"] == 1


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
        if d["osm_way_id"] in (1001, 1002, 1006):
            assert d["locks"] == 0


def test_orphan_locks_reported():
    _, report = attach_locks(build_graph(_oxford()), _oxford())
    assert report["orphan_lock_ways"] == []
    assert report["orphan_lock_nodes"] == []


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
    assert report["lock_gate_nodes"] == 1  # node 6003
    # the gate sits at the chamber-1/chamber-2 junction; neither edge gets +1
    assert sum(d["locks"] for _, _, d in g.edges(data=True)) == 3
