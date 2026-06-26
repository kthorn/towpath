import json

import pytest
from pound.route.snap import build_gazetteer, snap_place

from pound.graph.build import build_graph
from pound.ingest.overpass import parse
from tests.fixtures import oxford_fixture_path


def _features():
    with open(oxford_fixture_path()) as f:
        return parse(json.load(f)["elements"], None)


def test_gazetteer_contains_named_places():
    gaz = build_gazetteer(_features())
    assert "Oxford" in gaz
    assert "Hayfield" in gaz


def test_snap_place_returns_graph_node():
    features = _features()
    g = build_graph(features)
    gaz = build_gazetteer(features)
    node = snap_place("Oxford", gaz, g)
    assert node in g.nodes
    node2 = snap_place("Hayfield", gaz, g)
    assert node2 in g.nodes
    assert node != node2


def test_snap_place_unknown_raises():
    g = build_graph(_features())
    gaz = build_gazetteer(_features())
    with pytest.raises(ValueError, match="unknown place"):
        snap_place("Narnia", gaz, g)
