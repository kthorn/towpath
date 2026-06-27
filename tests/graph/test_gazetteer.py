from pound.graph.build import _node_key, build_graph
from pound.graph.gazetteer import (
    ambiguous_place_names,
    attach_node_names,
    build_gazetteer,
)
from pound.ingest.ir import (
    NodeKind,
    WaterwayFeatures,
    WaterwayKind,
    WaterwayNode,
    WaterwayWay,
    WayDimensions,
)


def _place(oid, name, lat, lon):
    return WaterwayNode(
        osm_id=oid, lat=lat, lon=lon, tags={"place": "village", "name": name}, kind=NodeKind.PLACE
    )


def _way(oid, nodes, geom):
    return WaterwayWay(
        osm_id=oid,
        kind=WaterwayKind.CANAL,
        name="X",
        tags={"waterway": "canal"},
        node_ids=nodes,
        geometry=geom,
        dimensions=WayDimensions(),
    )


def test_gazetteer_unambiguous_name_maps_to_single_key():
    feats = WaterwayFeatures(
        ways=[_way(1, [10, 11], [(51.75, -1.26), (51.76, -1.27)])],
        nodes=[_place(100, "Oxford", 51.75, -1.26), _place(101, "Banbury", 51.76, -1.27)],
        source="geofabrik",
        fetched_at="t",
        bbox=None,
    )
    gaz = build_gazetteer(feats)
    assert gaz["Oxford"] == _node_key(51.75, -1.26)
    assert gaz["Banbury"] == _node_key(51.76, -1.27)
    assert ambiguous_place_names(gaz) == []


def test_gazetteer_duplicate_name_maps_to_list_of_candidates():
    feats = WaterwayFeatures(
        ways=[],
        nodes=[_place(100, "Newton", 52.0, -1.0), _place(101, "Newton", 53.0, -2.0)],
        source="geofabrik",
        fetched_at="t",
        bbox=None,
    )
    gaz = build_gazetteer(feats)
    assert isinstance(gaz["Newton"], list)
    assert len(gaz["Newton"]) == 2
    assert set(gaz["Newton"]) == {_node_key(52.0, -1.0), _node_key(53.0, -2.0)}
    assert ambiguous_place_names(gaz) == ["Newton"]


def test_attach_node_names_sets_name_on_coincident_graph_nodes():
    feats = WaterwayFeatures(
        ways=[_way(1, [10, 11], [(51.75, -1.26), (51.76, -1.27)])],
        nodes=[_place(100, "Oxford", 51.75, -1.26)],  # coincides with way end
        source="geofabrik",
        fetched_at="t",
        bbox=None,
    )
    g = build_graph(feats)
    n = attach_node_names(g, feats)
    assert n == 1
    key = _node_key(51.75, -1.26)
    assert g.nodes[key].get("name") == "Oxford"


def test_attach_node_names_skips_non_coincident_place():
    feats = WaterwayFeatures(
        ways=[_way(1, [10, 11], [(51.75, -1.26), (51.76, -1.27)])],
        nodes=[_place(100, "FarAway", 55.0, 0.0)],  # not on the way
        source="geofabrik",
        fetched_at="t",
        bbox=None,
    )
    g = build_graph(feats)
    n = attach_node_names(g, feats)
    assert n == 0
