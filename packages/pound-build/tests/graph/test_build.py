import json

import networkx as nx
from fixtures import oxford_fixture_path
from pound.models import AccessCaveat, WaterwayKind, WayDimensions
from pound_build.graph.build import build_graph
from pound_build.ingest.ir import NodeKind, WaterwayFeatures, WaterwayNode, WaterwayWay
from pound_build.ingest.overpass import parse


def _features():
    try:
        with open(oxford_fixture_path()) as f:
            return parse(json.load(f)["elements"], None)
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(f"Failed to load Oxford fixture: {e}") from e


def _way(osm_id, tags, geometry, node_ids):
    return WaterwayWay(
        osm_id=osm_id,
        kind=WaterwayKind.CANAL,
        name=None,
        tags=tags,
        node_ids=node_ids,
        geometry=geometry,
        dimensions=WayDimensions(),
    )


def _features_for(*ways, nodes=()):
    return WaterwayFeatures(
        ways=list(ways),
        nodes=list(nodes),
        source="test",
        fetched_at="2026-08-23T00:00:00Z",
        bbox=None,
    )


def test_build_returns_networkx_graph():
    g = build_graph(_features())
    assert isinstance(g, nx.Graph)
    assert all(data["movable_bridge_ids"] == () for _, data in g.nodes(data=True))
    assert all(data["turning_point"] is False for _, data in g.nodes(data=True))
    assert all(data["turning_max_length_m"] is None for _, data in g.nodes(data=True))


def test_build_attaches_turning_point_and_maximum_length_to_waterway_node():
    graph = build_graph(
        _features_for(
            _way(
                11,
                {"waterway": "canal"},
                [(51.0, -1.0), (51.001, -1.0), (51.002, -1.0)],
                [1, 2, 3],
            ),
            nodes=(
                WaterwayNode(
                    osm_id=2,
                    lat=51.001,
                    lon=-1.0,
                    tags={"waterway": "turning_point", "maxlength": "21.5"},
                    kind=NodeKind.TURNING_POINT,
                ),
            ),
        )
    )

    turning = next(data for _, data in graph.nodes(data=True) if "2" in data["osm_node_ids"])
    assert turning["turning_point"] is True
    assert turning["turning_max_length_m"] == 21.5


def test_build_attaches_turning_point_by_coordinate_identity():
    graph = build_graph(
        _features_for(
            _way(11, {"waterway": "canal"}, [(51.0, -1.0), (51.001, -1.0)], [1, 2]),
            nodes=(
                WaterwayNode(
                    osm_id=99,
                    lat=51.001,
                    lon=-1.0,
                    tags={"waterway": "turning_point"},
                    kind=NodeKind.TURNING_POINT,
                ),
            ),
        )
    )

    turning = next(data for _, data in graph.nodes(data=True) if data["lat"] == 51.001)
    assert turning["turning_point"] is True
    assert turning["turning_max_length_m"] is None


def test_build_does_not_create_unmatched_turning_point_node():
    graph = build_graph(
        _features_for(
            _way(11, {"waterway": "canal"}, [(51.0, -1.0), (51.001, -1.0)], [1, 2]),
            nodes=(
                WaterwayNode(
                    osm_id=99,
                    lat=52.0,
                    lon=-2.0,
                    tags={"waterway": "turning_point"},
                    kind=NodeKind.TURNING_POINT,
                ),
            ),
        )
    )

    assert graph.number_of_nodes() == 2
    assert all("99" not in data["osm_node_ids"] for _, data in graph.nodes(data=True))


def test_build_excludes_derelict_ways():
    g = build_graph(_features())
    ids = {d["osm_way_id"] for _, _, d in g.edges(data=True)}
    assert 1004 not in ids  # disused:waterway
    assert 1005 not in ids  # derelict_canal


def test_build_main_chain_and_pendant_counts_match_noded_model():
    g = build_graph(_features())
    # chain 1001(2 edges)->1002(1)->1003(1), pendant 1007(1) joins 1003 far-end
    # by shared id 3002, Duke's Cut 1006(1 edge) isolated.
    ids = {d["osm_way_id"] for _, _, d in g.edges(data=True)}
    assert ids == {1001, 1002, 1003, 1006, 1007}
    # main-chain+pendant component = 6 nodes (11,12,13,5003,3002,7002); Duke's = 2 -> 8 total
    assert g.number_of_nodes() == 8
    # 1001 yields 2 segment edges; 1002/1003/1006/1007 yield 1 each -> 6 total
    assert g.number_of_edges() == 6


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
    assert edge["has_tunnel"]
    assert edge["movable_bridge_ids"] == ()
    assert edge["tunnel_restrictions"] == ()


def test_build_attaches_retained_access_caveats_to_each_emitted_segment():
    graph = build_graph(
        _features_for(
            _way(
                77,
                {"waterway": "canal", "boat": "discouraged"},
                [(51.0, -1.0), (51.001, -1.0), (51.002, -1.0)],
                [1, 2, 3],
            )
        )
    )
    expected = (AccessCaveat(77, "boat", "discouraged", "discouraged"),)
    assert [data["access_caveats"] for _, _, data in graph.edges(data=True)] == [expected, expected]


def test_build_merges_sorted_unique_access_caveats_from_coincident_ways():
    geometry = [(51.0, -1.0), (51.001, -1.0)]
    graph = build_graph(
        _features_for(
            _way(11, {"waterway": "canal", "boat": "discouraged"}, geometry, [1, 2]),
            _way(10, {"waterway": "canal", "access": "customers"}, geometry, [1, 2]),
        )
    )
    edge = next(data for _, _, data in graph.edges(data=True))
    assert edge["access_caveats"] == (
        AccessCaveat(10, "access", "customers", "unknown"),
        AccessCaveat(11, "boat", "discouraged", "discouraged"),
    )
