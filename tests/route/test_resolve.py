import networkx as nx
import pytest

from pound.route.resolve import resolve_place


def _graph_with_gazetteer(gaz, nodes):
    """nodes: list of (uid, lat, lon). Mirror build_graph's uid-keyed graph."""
    g = nx.Graph()
    for uid, lat, lon in nodes:
        g.add_node(uid, lat=lat, lon=lon)
    g.graph["gazetteer"] = gaz
    return g


def test_resolve_place_returns_exact_node_when_in_gazetteer():
    g = _graph_with_gazetteer(
        {"Oxford": (51.75, -1.26), "Banbury": (52.06, -1.34)},
        [(0, 51.75, -1.26), (1, 52.06, -1.34)],
    )
    assert resolve_place("Oxford", g) == 0
    assert resolve_place("Banbury", g) == 1


def test_resolve_place_snaps_to_nearest_graph_node_within_tolerance():
    # Place coordinate ~140 m from the nearest graph node; 50 m tolerance fails,
    # 200 m tolerance succeeds and returns the matched node's uid (the nearest uid).
    g = _graph_with_gazetteer(
        {"Pub": (51.7509, -1.2609)},
        [(0, 51.75, -1.26), (1, 51.80, -1.30)],
    )
    with pytest.raises(ValueError, match="not within"):
        resolve_place("Pub", g, snap_tolerance_m=50.0)
    assert resolve_place("Pub", g, snap_tolerance_m=200.0) == 0  # nearest uid


def test_resolve_place_unknown_name_raises_with_count():
    g = _graph_with_gazetteer(
        {"Oxford": (51.75, -1.26)},
        [(0, 51.75, -1.26)],
    )
    with pytest.raises(ValueError, match="not found in gazetteer.*covers 1 places"):
        resolve_place("Narnia", g)


def test_resolve_place_ambiguous_name_raises():
    g = _graph_with_gazetteer(
        {"Newton": [(52.0, -1.0), (53.0, -2.0)]},
        [(0, 52.0, -1.0), (1, 53.0, -2.0)],
    )
    with pytest.raises(ValueError, match="matches 2 places"):
        resolve_place("Newton", g)
