import networkx as nx
import pytest

from pound.route.resolve import resolve_coord


def _graph_with_gazetteer(gaz, nodes):
    """nodes: list of (uid, lat, lon). Mirror build_graph's uid-keyed graph."""
    g = nx.Graph()
    for uid, lat, lon in nodes:
        g.add_node(uid, lat=lat, lon=lon)
    g.graph["gazetteer"] = gaz
    return g


def test_resolve_coord_returns_nearest_uid_and_distance():
    g = _graph_with_gazetteer({}, [(0, 51.75, -1.26), (1, 52.06, -1.34)])
    uid, dist = resolve_coord(51.7501, -1.2601, g)
    assert uid == 0
    assert dist == pytest.approx(13, abs=5)  # ~13 m from node 0


def test_resolve_coord_picks_closer_of_two_nodes():
    g = _graph_with_gazetteer({}, [(0, 51.75, -1.26), (1, 52.06, -1.34)])
    uid, dist = resolve_coord(52.0599, -1.3399, g)
    assert uid == 1
    assert dist < 50


def test_resolve_coord_exact_node_returns_zero_distance():
    g = _graph_with_gazetteer({}, [(0, 51.75, -1.26)])
    uid, dist = resolve_coord(51.75, -1.26, g)
    assert uid == 0
    assert dist == 0


def test_resolve_coord_empty_graph_raises():
    g = nx.Graph()
    with pytest.raises(ValueError, match="no graph nodes"):
        resolve_coord(51.75, -1.26, g)
