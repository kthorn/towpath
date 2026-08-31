import json

from fixtures import oxford_fixture_path
from pound_build.graph.build import build_graph
from pound_build.graph.locks import attach_locks
from pound_build.ingest.overpass import parse
from pound_build.validate.connectivity import validate_graph


def _graph_and_report():
    try:
        with open(oxford_fixture_path()) as f:
            features = parse(json.load(f)["elements"], None)
        g, report = attach_locks(build_graph(features), features)
        return g, report
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(f"Failed to load Oxford fixture: {e}") from e


def test_component_count_is_two():
    g, report = _graph_and_report()
    v = validate_graph(g, report)
    assert v["component_count"] == 2  # main chain + pendant + Duke's Cut (2 components)
    assert v["largest_component_size"] == 6  # main chain+pendant component: 6 nodes


def test_no_derelict_edges():
    g, report = _graph_and_report()
    v = validate_graph(g, report)
    assert v["derelict_edges"] == 0


def test_missing_dims_count():
    g, report = _graph_and_report()
    v = validate_graph(g, report)
    # 1001(x2 no dims), 1003, 1006, 1007 have no dims; 1002 does
    assert v["edges_missing_dims"] == 5


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
    assert v["total_edges"] == 6
    assert v["total_nodes"] == 8


def test_report_has_bulk_connectivity_keys():
    g, report = _graph_and_report()
    v = validate_graph(g, report)
    for k in (
        "place_nodes_seen",
        "place_nodes_in_gazetteer",
        "named_nodes_in_graph",
        "ambiguous_place_names",
    ):
        assert k in v
    # removed snap/override keys are absent
    for k in ("tolerance_snaps_used", "tolerance_snaps_unresolved", "overrides_applied"):
        assert k not in v


def test_report_defaults_when_graph_has_no_bulk_attrs():
    # A plain graph (no graph.graph bulk keys) still validates.
    import networkx as nx

    g = nx.Graph()
    g.add_node(0, lat=51.7, lon=-1.2)
    v = validate_graph(g, {"orphan_lock_ways": [], "orphan_lock_nodes": []})
    assert v["place_nodes_seen"] == 0
    assert v["place_nodes_in_gazetteer"] == 0
    assert v["named_nodes_in_graph"] == 0
    assert v["ambiguous_place_names"] == []
    # removed snap/override keys are absent
    for k in ("tolerance_snaps_used", "tolerance_snaps_unresolved", "overrides_applied"):
        assert k not in v


def test_report_merges_poi_attachment_validation_counts():
    g, report = _graph_and_report()
    v = validate_graph(
        g,
        report,
        {
            "duplicate_identities": 2,
            "empty_geometry": 1,
            "invalid_geometry": 3,
            "rejected_by_corridor": 4,
        },
    )
    assert v["poi_duplicate_identities"] == 2
    assert v["poi_empty_geometry"] == 1
    assert v["poi_invalid_geometry"] == 3
    assert v["poi_rejected_by_corridor"] == 4
