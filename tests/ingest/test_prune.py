from pound.ingest.ir import (
    NodeKind,
    WaterwayFeatures,
    WaterwayKind,
    WaterwayNode,
    WaterwayWay,
    WayDimensions,
)
from pound.ingest.prune import prune_non_navigable_infra


def _way(osm_id, kind, tags, geom, node_ids):
    return WaterwayWay(
        osm_id=osm_id,
        kind=kind,
        name=tags.get("name"),
        tags=tags,
        node_ids=node_ids,
        geometry=geom,
        dimensions=WayDimensions(),
    )


def _node(osm_id, kind, tags=None):
    return WaterwayNode(
        osm_id=osm_id,
        lat=51.0 + osm_id / 1000,
        lon=-1.0,
        tags=tags or {"waterway": kind.value} if kind else {},
        kind=kind,
    )


def _features(ways, nodes):
    return WaterwayFeatures(
        ways=ways,
        nodes=nodes,
        source="test",
        fetched_at="2026-06-28T00:00:00Z",
        bbox=None,
    )


def test_lock_gate_on_single_boat_no_way_is_dropped():
    # way 1 carries node 100 at its start; boat=no.
    ways = [
        _way(
            1,
            WaterwayKind.CANAL,
            {"waterway": "canal", "boat": "no"},
            [(51.0, -1.0), (51.001, -1.0)],
            [100, 101],
        ),
    ]
    nodes = [_node(100, NodeKind.LOCK_GATE)]
    out = prune_non_navigable_infra(_features(ways, nodes))
    assert [n.osm_id for n in out.nodes] == []


def test_lock_gate_on_mixed_boat_no_and_yes_is_kept():
    # node 100 at the shared endpoint of a boat=no way and a boat=yes way
    ways = [
        _way(
            1,
            WaterwayKind.CANAL,
            {"waterway": "canal", "boat": "no"},
            [(51.0, -1.0), (51.001, -1.0)],
            [100, 101],
        ),
        _way(
            2,
            WaterwayKind.CANAL,
            {"waterway": "canal", "boat": "yes"},
            [(51.001, -1.0), (51.002, -1.0)],
            [101, 100],
        ),
    ]
    nodes = [_node(100, NodeKind.LOCK_GATE)]
    out = prune_non_navigable_infra(_features(ways, nodes))
    assert [n.osm_id for n in out.nodes] == [100]


def test_lock_gate_on_two_boat_no_and_one_boat_yes_way_is_kept():
    # two non-navigable incidents + one navigable -> still gates traffic -> kept
    ways = [
        _way(
            1,
            WaterwayKind.CANAL,
            {"waterway": "canal", "boat": "no"},
            [(51.0, -1.0), (51.001, -1.0)],
            [100, 101],
        ),
        _way(
            2,
            WaterwayKind.CANAL,
            {"waterway": "canal", "boat": "no"},
            [(51.002, -1.0), (51.003, -1.0)],
            [102, 100],
        ),
        _way(
            3,
            WaterwayKind.CANAL,
            {"waterway": "canal", "boat": "yes"},
            [(51.003, -1.0), (51.004, -1.0)],
            [100, 103],
        ),
    ]
    nodes = [_node(100, NodeKind.LOCK_GATE)]
    out = prune_non_navigable_infra(_features(ways, nodes))
    assert [n.osm_id for n in out.nodes] == [100]


def test_place_node_on_all_boat_no_ways_is_kept():
    # gazetteer anchors survive even when all incidents are non-navigable
    ways = [
        _way(
            1,
            WaterwayKind.CANAL,
            {"waterway": "canal", "boat": "no"},
            [(51.0, -1.0), (51.001, -1.0)],
            [200, 201],
        ),
    ]
    nodes = [
        WaterwayNode(
            osm_id=200,
            lat=51.0,
            lon=-1.0,
            tags={"place": "town", "name": "Reading"},
            kind=NodeKind.PLACE,
        ),
    ]
    out = prune_non_navigable_infra(_features(ways, nodes))
    assert [n.osm_id for n in out.nodes] == [200]


def test_node_with_no_incident_ways_is_kept():
    # Overpass path: empty/wrong node_ids -> node has zero incidents -> kept (no-op)
    ways = [
        _way(
            1,
            WaterwayKind.CANAL,
            {"waterway": "canal", "boat": "no"},
            [(51.0, -1.0), (51.001, -1.0)],
            [],
        ),  # empty node_ids (out geom)
    ]
    nodes = [_node(300, NodeKind.LOCK_GATE)]
    out = prune_non_navigable_infra(_features(ways, nodes))
    assert [n.osm_id for n in out.nodes] == [300]


def test_way_with_missing_boat_tag_counts_as_navigable():
    # a way with no `boat` key is navigable -> its sole lock_gate is kept
    ways = [
        _way(
            1, WaterwayKind.CANAL, {"waterway": "canal"}, [(51.0, -1.0), (51.001, -1.0)], [400, 401]
        ),
    ]
    nodes = [_node(400, NodeKind.LOCK_GATE)]
    out = prune_non_navigable_infra(_features(ways, nodes))
    assert [n.osm_id for n in out.nodes] == [400]


def test_node_with_own_boat_no_tag_is_not_dropped_by_node_tag():
    # node-level `boat=no` is IGNORED -- prune uses incident-way tags only
    ways = [
        _way(
            1,
            WaterwayKind.CANAL,
            {"waterway": "canal", "boat": "yes"},
            [(51.0, -1.0), (51.001, -1.0)],
            [500, 501],
        ),
    ]
    nodes = [
        WaterwayNode(
            osm_id=500,
            lat=51.0,
            lon=-1.0,
            tags={"waterway": "lock_gate", "boat": "no"},
            kind=NodeKind.LOCK_GATE,
        ),
    ]
    out = prune_non_navigable_infra(_features(ways, nodes))
    assert [n.osm_id for n in out.nodes] == [500]  # kept -- its incident is navigable


def test_prune_does_not_mutate_input():
    ways = [
        _way(
            1,
            WaterwayKind.CANAL,
            {"waterway": "canal", "boat": "no"},
            [(51.0, -1.0), (51.001, -1.0)],
            [100, 101],
        ),
    ]
    nodes = [_node(100, NodeKind.LOCK_GATE)]
    features = _features(ways, nodes)
    out = prune_non_navigable_infra(features)
    assert out is not features
    assert out.nodes is not features.nodes
    # input untouched
    assert [n.osm_id for n in features.nodes] == [100]


def test_prune_preserves_ways():
    # ways are NEVER touched by prune (the way filter is a separate function)
    ways = [
        _way(
            1,
            WaterwayKind.CANAL,
            {"waterway": "canal", "boat": "no"},
            [(51.0, -1.0), (51.001, -1.0)],
            [100, 101],
        ),
        _way(
            2, WaterwayKind.RIVER, {"waterway": "river"}, [(51.01, -1.0), (51.02, -1.0)], [101, 102]
        ),
    ]
    nodes = [_node(100, NodeKind.LOCK_GATE)]
    features = _features(ways, nodes)
    out = prune_non_navigable_infra(features)
    assert [w.osm_id for w in out.ways] == [1, 2]  # both ways survive prune
    assert [n.osm_id for n in out.nodes] == []  # but the lock_gate on boat=no drops
