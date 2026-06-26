import json

from pound.validate.connectivity import validate_graph

from pound.graph.build import build_graph
from pound.graph.locks import attach_locks
from pound.ingest.overpass import parse
from tests.fixtures import oxford_fixture_path


def _graph_and_report():
    with open(oxford_fixture_path()) as f:
        features = parse(json.load(f)["elements"], None)
    g, report = attach_locks(build_graph(features), features)
    return g, report


def test_component_count_is_two():
    g, report = _graph_and_report()
    v = validate_graph(g, report)
    assert v["component_count"] == 2  # main chain + Duke's Cut
    assert v["largest_component_size"] == 4  # 4 nodes in the main chain


def test_no_derelict_edges():
    g, report = _graph_and_report()
    v = validate_graph(g, report)
    assert v["derelict_edges"] == 0


def test_missing_dims_count():
    g, report = _graph_and_report()
    v = validate_graph(g, report)
    # 1001, 1003, 1006 have no dims; 1002 does
    assert v["edges_missing_dims"] == 3


def test_no_zero_length_or_self_loops():
    g, report = _graph_and_report()
    v = validate_graph(g, report)
    assert v["zero_length_edges"] == 0
    assert v["self_loops"] == 0


def test_orphans_carry_through():
    g, report = _graph_and_report()
    v = validate_graph(g, report)
    assert v["orphan_lock_ways"] == []
    assert v["orphan_lock_nodes"] == []


def test_totals_present():
    g, report = _graph_and_report()
    v = validate_graph(g, report)
    assert v["total_edges"] == 4
    assert v["total_nodes"] == 6
