import json

from pound.graph.build import build_graph
from pound.graph.locks import attach_locks
from pound.ingest.overpass import parse
from pound.validate.connectivity import validate_graph
from tests.fixtures import oxford_fixture_path


def _graph_and_report():
    with open(oxford_fixture_path()) as f:
        features = parse(json.load(f)["elements"], None)
    g, report = attach_locks(build_graph(features), features)
    return g, report


def test_component_count_is_two():
    g, report = _graph_and_report()
    v = validate_graph(g, report)
    assert v["component_count"] == 2  # main chain + pendant + Duke's Cut (2 components)
    assert v["largest_component_size"] == 5  # 4 chain + 1 pendant far-end


def test_no_derelict_edges():
    g, report = _graph_and_report()
    v = validate_graph(g, report)
    assert v["derelict_edges"] == 0


def test_missing_dims_count():
    g, report = _graph_and_report()
    v = validate_graph(g, report)
    # 1001, 1003, 1007, 1006 have no dims; 1002 does
    assert v["edges_missing_dims"] == 4


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
    assert v["total_edges"] == 5
    assert v["total_nodes"] == 7


def test_report_has_bulk_connectivity_keys():
    g, report = _graph_and_report()
    v = validate_graph(g, report)
    for k in (
        "overrides_applied",
        "tolerance_snaps_used",
        "tolerance_snaps_unresolved",
        "place_nodes_seen",
        "place_nodes_in_gazetteer",
        "named_nodes_in_graph",
        "ambiguous_place_names",
    ):
        assert k in v


def test_report_defaults_when_graph_has_no_bulk_attrs():
    # A plain Scope-C-style graph (no graph.graph bulk keys) still validates.
    import networkx as nx

    g = nx.Graph()
    g.add_node((51.7, -1.2), lat=51.7, lon=-1.2)
    v = validate_graph(g, {"orphan_lock_ways": [], "orphan_lock_nodes": []})
    assert v["overrides_applied"] == 0
    assert v["tolerance_snaps_used"] == []
    assert v["tolerance_snaps_unresolved"] == []
    assert v["place_nodes_seen"] == 0
    assert v["place_nodes_in_gazetteer"] == 0
    assert v["named_nodes_in_graph"] == 0
    assert v["ambiguous_place_names"] == []
