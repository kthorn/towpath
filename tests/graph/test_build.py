import json

import networkx as nx
from pound.graph.build import build_graph

from pound.ingest.ir import WaterwayKind
from pound.ingest.overpass import parse
from tests.fixtures import oxford_fixture_path


def _features():
    with open(oxford_fixture_path()) as f:
        return parse(json.load(f)["elements"], None)


def test_build_returns_networkx_graph():
    g = build_graph(_features())
    assert isinstance(g, nx.Graph)


def test_build_excludes_derelict_ways():
    g = build_graph(_features())
    ids = {d["osm_way_id"] for _, _, d in g.edges(data=True)}
    assert 1004 not in ids  # disused:waterway
    assert 1005 not in ids  # derelict_canal


def test_build_main_chain_has_three_edges():
    g = build_graph(_features())
    # ways 1001 -> 1002 -> 1003 chain by shared endpoints => 3 edges, 4 nodes
    ids = {d["osm_way_id"] for _, _, d in g.edges(data=True)}
    assert ids == {1001, 1002, 1003, 1006}
    # Duke's Cut (1006) is isolated at 51.7400,-1.2500 -> 51.7410,-1.2510
    assert g.number_of_nodes() == 6  # 4 chain nodes + 2 Duke's Cut nodes


def test_build_edge_has_length_and_dims():
    g = build_graph(_features())
    edge = next(d for _, _, d in g.edges(data=True) if d["osm_way_id"] == 1002)
    assert edge["length_m"] > 0.0
    assert edge["dimensions"].max_beam_m == 2.1
    assert edge["dimensions"].max_draft_m == 0.9
    assert edge["kind"] == WaterwayKind.CANAL


def test_build_lock_way_edge_kind():
    g = build_graph(_features())
    edge = next(d for _, _, d in g.edges(data=True) if d["osm_way_id"] == 1003)
    assert edge["kind"] == WaterwayKind.LOCK
    assert edge["locks"] == 0  # filled by locks.py, not build


def test_build_tunnel_flag():
    g = build_graph(_features())
    edge = next(d for _, _, d in g.edges(data=True) if d["osm_way_id"] == 1006)
    assert edge["has_tunnel"] is True
