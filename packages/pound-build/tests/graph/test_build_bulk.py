import networkx as nx
import pytest
from pound_build.graph.build import build_graph
from pound_build.graph.locks import attach_locks
from pound_build.ingest.ir import (
    NodeKind,
    WaterwayFeatures,
    WaterwayKind,
    WaterwayNode,
    WaterwayWay,
    WayDimensions,
)


def _way(
    oid,
    kind,
    name,
    nodes,
    geom,
    dims=None,
    tags=None,
    *,
    has_tunnel=False,
    has_movable_bridge=False,
):
    return WaterwayWay(
        osm_id=oid,
        kind=kind,
        name=name,
        tags=tags or {"waterway": kind.value},
        node_ids=nodes,
        geometry=geom,
        dimensions=dims or WayDimensions(),
        has_tunnel=has_tunnel,
        has_movable_bridge=has_movable_bridge,
    )


def _features(ways, nodes=None):
    return WaterwayFeatures(
        ways=ways,
        nodes=nodes or [],
        source="geofabrik",
        fetched_at="2026-06-25T00:00:00Z",
        bbox=None,
    )


# --- Noded emission: every OSM id -> node, consecutive ids -> edges --------


def test_noded_way_emits_per_segment_edges():
    # 3 node_ids, 3 coords -> 3 nodes, 2 segment edges (not 1 whole-way edge).
    ways = [
        _way(
            1,
            WaterwayKind.CANAL,
            "A",
            [11, 12, 13],
            [(51.7500, -1.2600), (51.7510, -1.2610), (51.7520, -1.2620)],
        )
    ]
    g = build_graph(_features(ways))
    assert g.number_of_nodes() == 3
    assert g.number_of_edges() == 2
    # each segment edge carries the parent way's osm_way_id
    assert {d["osm_way_id"] for _, _, d in g.edges(data=True)} == {1}


def test_segment_edge_length_is_per_segment_not_whole_way():
    ways = [
        _way(
            1,
            WaterwayKind.CANAL,
            "A",
            [11, 12, 13],
            [(51.7500, -1.2600), (51.7510, -1.2610), (51.7520, -1.2620)],
        )
    ]
    g = build_graph(_features(ways))
    seg = next(d for _, _, d in g.edges(data=True))
    # ~131 m per segment, NOT the ~262 m whole-way length.
    assert 120.0 < seg["length_m"] < 140.0


# --- Shared junctions collapse at emission (no contraction phase) ----------


def test_shared_osm_id_at_endpoint_joins_two_ways():
    ways = [
        _way(1, WaterwayKind.CANAL, "A", [1, 7], [(51.7500, -1.2600), (51.7520, -1.2620)]),
        _way(2, WaterwayKind.CANAL, "B", [7, 9], [(51.7520, -1.2620), (51.7540, -1.2640)]),
    ]
    g = build_graph(_features(ways))
    assert g.number_of_nodes() == 3
    assert g.number_of_edges() == 2
    assert nx.number_connected_components(g) == 1


def test_internal_junction_way_joins_main_chain_at_an_internal_node():
    """Acceptance crit 5: a way sharing an OSM id only at an INTERNAL position
    of another way joins it — the exact defect this rewrite fixes. Under the
    endpoint-only build, B's shared id sits in the middle of A (not at A's
    endpoints), so B becomes a detached single edge and the graph is two
    components; noding makes A's shared id a real graph node and B joins it."""
    ways = [
        _way(
            1,
            WaterwayKind.CANAL,
            "A",
            [1, 2, 3],
            [(51.7500, -1.2600), (51.7510, -1.2610), (51.7520, -1.2620)],
        ),
        _way(
            2,
            WaterwayKind.CANAL,
            "B",
            [4, 2],  # node 2 is INTERNAL to A
            [(51.7600, -1.2700), (51.7510, -1.2610)],
        ),
    ]
    g = build_graph(_features(ways))
    assert nx.number_connected_components(g) == 1
    # A has 3 nodes; B brings 1 new (id 4); the shared id 2 is one graph node of degree 3
    # (A's two segment edges + B's one edge).
    shared_node = next(n for n, d in g.nodes(data=True) if "2" in d.get("osm_node_ids", set()))
    assert g.degree(shared_node) == 3


def test_exact_coordinate_authority_joins_coincident_ends_without_node_ids():
    # id-less dev path (Overpass out geom): coincident rounded coords join.
    ways = [
        _way(1, WaterwayKind.CANAL, "A", [], [(51.7500, -1.2600), (51.7520, -1.2620)]),
        _way(2, WaterwayKind.CANAL, "B", [], [(51.7520, -1.2620), (51.7540, -1.2640)]),
    ]
    g = build_graph(_features(ways))
    assert nx.number_connected_components(g) == 1


def test_distinct_osm_ids_rounding_to_same_coord_collapse_to_one_node():
    # two ways that don't share an OSM node id but meet at the same rounded coord
    # become ONE graph node (coord authority); both ids land in osm_node_ids.
    ways = [
        _way(1, WaterwayKind.CANAL, "A", [1, 2], [(51.7500, -1.2600), (51.7520, -1.2620)]),
        _way(2, WaterwayKind.CANAL, "B", [3, 4], [(51.7540, -1.2640), (51.7520, -1.2620)]),
    ]
    g = build_graph(_features(ways))
    assert nx.number_connected_components(g) == 1
    shared = next(n for n, d in g.nodes(data=True) if {"2", "4"} <= d.get("osm_node_ids", set()))
    assert g.nodes[shared]["osm_node_ids"] == {"2", "4"}


# --- Closed-ring skip (area polygons are never routable) -------------------


def test_closed_ring_way_emits_no_self_loop_and_no_isolated_node():
    from pound_build.validate.connectivity import validate_graph

    ring_geom = [
        (51.7500, -1.2600),
        (51.7510, -1.2600),
        (51.7510, -1.2610),
        (51.7500, -1.2600),  # == first -> closed ring
    ]
    ways = [_way(1, WaterwayKind.CANAL, "Basin", [1, 2, 3, 1], ring_geom)]
    g = build_graph(_features(ways))
    assert g.number_of_edges() == 0
    assert g.number_of_nodes() == 0
    v = validate_graph(g, {"orphan_lock_ways": [], "orphan_lock_nodes": []})
    assert v["self_loops"] == 0


def test_closed_ring_does_not_mask_a_real_routable_cycle():
    a, b, c = (51.7500, -1.2600), (51.7520, -1.2600), (51.7510, -1.2620)
    ways = [
        _way(10, WaterwayKind.CANAL, "AB", [1, 2], [a, b]),
        _way(20, WaterwayKind.CANAL, "BC", [2, 3], [b, c]),
        _way(30, WaterwayKind.CANAL, "CA", [3, 1], [c, a]),
    ]
    g = build_graph(_features(ways))
    assert g.number_of_edges() == 3
    assert nx.number_connected_components(g) == 1
    assert all(u != v for u, v in g.edges())


def test_consecutive_duplicate_id_or_coord_segment_is_skipped():
    # a way that references the same OSM id twice in a row (or two coords that
    # round equal) would yield a zero-length self-loop; dedupe-then-iterate.
    ways = [
        _way(
            1,
            WaterwayKind.CANAL,
            "A",
            [1, 1, 2],
            [(51.7500, -1.2600), (51.7500, -1.2600), (51.7520, -1.2620)],
        )
    ]
    g = build_graph(_features(ways))
    assert g.number_of_edges() == 1
    assert all(u != v for u, v in g.edges())


# --- Edge collision: merge attrs (§3.3) — acceptance crit 6 ----------------


def test_coincident_lock_and_canal_ways_merge_to_one_lock_edge():
    """Acceptance crit 6: a lock-tagged edge coincident with a canal-tagged edge
    resolves to one edge with kind==LOCK, the LOCK way's osm_way_id kept (so
    attach_locks finds it), and locks==1 both at build (§3.3 merge sets it) and
    after attach_locks."""
    # routable ways sort before locks in read_pbf/parse, but the merge is
    # order-independent; mirror the measured case (canal emissible first).
    ways = [
        _way(100, WaterwayKind.CANAL, "Canal", [1, 2], [(51.7500, -1.2600), (51.7520, -1.2620)]),
        _way(200, WaterwayKind.LOCK, "Lock", [1, 2], [(51.7500, -1.2600), (51.7520, -1.2620)]),
    ]
    g = build_graph(_features(ways))
    assert g.number_of_edges() == 1
    e = next(d for _, _, d in g.edges(data=True))
    assert e["kind"] == WaterwayKind.LOCK
    assert e["osm_way_id"] == 200  # LOCK way's id kept
    assert e["locks"] == 1  # set at merge (one party LOCK)
    # after attach_locks (deep copy), the way-loop finds osm_way_id==200 -> locks=1
    g2, _ = attach_locks(g, _features(ways))
    e2 = next(d for _, _, d in g2.edges(data=True))
    assert e2["locks"] == 1


def test_coincident_river_and_canal_merge_prefers_canal():
    ways = [
        _way(300, WaterwayKind.RIVER, "R", [1, 2], [(51.7500, -1.2600), (51.7520, -1.2620)]),
        _way(400, WaterwayKind.CANAL, "C", [1, 2], [(51.7500, -1.2600), (51.7520, -1.2620)]),
    ]
    g = build_graph(_features(ways))
    assert g.number_of_edges() == 1
    e = next(d for _, _, d in g.edges(data=True))
    assert e["kind"] == WaterwayKind.CANAL  # Calder-and-Hebble dual-classification


def test_collision_union_tightens_dimensions():
    ways = [
        _way(
            500,
            WaterwayKind.CANAL,
            "C",
            [1, 2],
            [(51.7500, -1.2600), (51.7520, -1.2620)],
            dims=WayDimensions(max_beam_m=2.0, max_draft_m=0.8),
        ),
        _way(
            501,
            WaterwayKind.CANAL,
            "C2",
            [1, 2],
            [(51.7500, -1.2600), (51.7520, -1.2620)],
            dims=WayDimensions(max_beam_m=2.2, max_draft_m=None, max_length_m=18.0),
        ),
    ]
    g = build_graph(_features(ways))
    d = g.edges[next(iter(g.edges))]["dimensions"]
    assert d.max_beam_m == 2.0  # min
    assert d.max_draft_m == 0.8  # carried from the other way
    assert d.max_length_m == 18.0


def test_bridge_tagged_multi_segment_way_marks_only_lower_middle_emittable_segment():
    way = _way(
        101,
        WaterwayKind.CANAL,
        "Bridge reach",
        [1, 2, 3, 4],
        [(51.75, -1.26), (51.751, -1.261), (51.752, -1.262), (51.753, -1.263)],
        tags={"waterway": "canal", "bridge:movable": "swing"},
        has_movable_bridge=True,
    )
    graph = build_graph(_features([way]))
    u, v, data = next(
        (u, v, data)
        for u, v, data in graph.edges(data=True)
        if data["movable_bridge_ids"] == ("way:101",)
    )
    assert {"2", "3"} <= graph.nodes[u]["osm_node_ids"] | graph.nodes[v]["osm_node_ids"]


def test_bridge_node_suppresses_overlapping_way_event_without_node_refs():
    way = _way(
        101,
        WaterwayKind.CANAL,
        "Bridge reach",
        [],
        [(51.75, -1.26), (51.751, -1.261)],
        tags={"waterway": "canal", "bridge": "movable"},
        has_movable_bridge=True,
    )
    node = WaterwayNode(
        osm_id=900,
        lat=51.7505,
        lon=-1.2605,
        tags={"bridge": "movable"},
        kind=NodeKind.MOVABLE_BRIDGE,
    )
    graph = build_graph(_features([way], [node]))
    assert all("way:101" not in data["movable_bridge_ids"] for _, _, data in graph.edges(data=True))
    assert {
        bridge_id for _, data in graph.nodes(data=True) for bridge_id in data["movable_bridge_ids"]
    } | {
        bridge_id
        for _, _, data in graph.edges(data=True)
        for bridge_id in data["movable_bridge_ids"]
    } == {"node:900"}


def test_tunnel_way_emits_sorted_restrictions():
    way = _way(
        102,
        WaterwayKind.CANAL,
        "Tunnel reach",
        [1, 2],
        [(51.75, -1.26), (51.751, -1.261)],
        tags={
            "waterway": "canal",
            "tunnel": "yes",
            "oneway:boat": "yes",
            "opening_hours": "Mo-Fr 09:00-17:00",
        },
        has_tunnel=True,
    )

    graph = build_graph(_features([way]))

    assert next(data for _, _, data in graph.edges(data=True))["tunnel_restrictions"] == (
        (102, "oneway:boat", "yes"),
        (102, "opening_hours", "Mo-Fr 09:00-17:00"),
    )


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"oneway": "yes"}, ((104, "oneway", "yes"),)),
        ({"oneway": "no"}, ()),
        ({"access": "private"}, ((104, "access", "private"),)),
        ({"access": "yes"}, ()),
        ({"boat": "private"}, ((104, "boat", "private"),)),
        ({"boat": "yes"}, ()),
        (
            {"oneway:conditional": "yes @ (Mo-Fr)"},
            ((104, "oneway:conditional", "yes @ (Mo-Fr)"),),
        ),
        ({"restriction": "no_entry"}, ((104, "restriction", "no_entry"),)),
        (
            {"restriction:boat": "no_entry"},
            ((104, "restriction:boat", "no_entry"),),
        ),
    ],
)
def test_tunnel_way_emits_each_unmodeled_restriction(tags, expected):
    way = _way(
        104,
        WaterwayKind.CANAL,
        "Tunnel reach",
        [1, 2],
        [(51.75, -1.26), (51.751, -1.261)],
        tags={"waterway": "canal", "tunnel": "yes", **tags},
        has_tunnel=True,
    )

    graph = build_graph(_features([way]))

    assert next(data for _, _, data in graph.edges(data=True))["tunnel_restrictions"] == expected


def test_coincident_way_preserves_tunnel_restrictions():
    tunnel = _way(
        102,
        WaterwayKind.CANAL,
        "Tunnel reach",
        [1, 2],
        [(51.75, -1.26), (51.751, -1.261)],
        tags={
            "waterway": "canal",
            "tunnel": "yes",
            "oneway:boat": "yes",
            "opening_hours": "Mo-Fr 09:00-17:00",
        },
        has_tunnel=True,
    )
    coincident = _way(
        103,
        WaterwayKind.CANAL,
        "Surface reach",
        [3, 4],
        [(51.75, -1.26), (51.751, -1.261)],
    )

    graph = build_graph(_features([tunnel, coincident]))

    assert next(data for _, _, data in graph.edges(data=True))["tunnel_restrictions"] == (
        (102, "oneway:boat", "yes"),
        (102, "opening_hours", "Mo-Fr 09:00-17:00"),
    )


# --- attach_locks flight-level chamber model (§3.5, OQ-A Model D) --------


def test_multi_node_lock_way_counts_chambers_by_gates():
    """A multi-node LOCK way with internal gate nodes: chambers = gates-1, set
    on the downstream-gate segments, not on every segment (Model B) and not on
    the first segment only (Model A). A 4-node, 3-gate way (gate-shape-gate-
    gate) => 2 chambers on the two downstream-gate segments; the shape-to-first-
    gate segment carries 0."""
    # nodes 1(gate), 2(shape), 3(gate), 4(gate). Segment 2->3 has downstream
    # node 3 (a gate) => 1 chamber; segment 3->4 has downstream 4 (gate) =>
    # 1 chamber. Total 2.
    ways = [
        _way(
            700,
            WaterwayKind.LOCK,
            "L",
            [1, 2, 3, 4],
            [(51.7500, -1.2600), (51.7510, -1.2610), (51.7520, -1.2620), (51.7530, -1.2630)],
        )
    ]
    gates = [
        WaterwayNode(
            osm_id=1,
            lat=51.7500,
            lon=-1.2600,
            tags={"waterway": "lock_gate"},
            kind=NodeKind.LOCK_GATE,
        ),
        WaterwayNode(
            osm_id=3,
            lat=51.7520,
            lon=-1.2620,
            tags={"waterway": "lock_gate"},
            kind=NodeKind.LOCK_GATE,
        ),
        WaterwayNode(
            osm_id=4,
            lat=51.7530,
            lon=-1.2630,
            tags={"waterway": "lock_gate"},
            kind=NodeKind.LOCK_GATE,
        ),
    ]
    feats = _features(ways, gates)
    g, _ = attach_locks(build_graph(feats), feats)
    assert sum(d.get("locks", 0) for _, _, d in g.edges(data=True)) == 2
    assert sum(1 for _, _, d in g.edges(data=True) if d.get("locks", 0) >= 1) == 2


def test_three_lock_gates_in_a_row_yields_two_chambers():
    """Kurt's prescription: three lock gates in a row => two chambers. A
    3-node way gate-gate-gate (G=3) => 2 chambers; both segments' downstream
    nodes are gates => 2 lock edges."""
    ways = [
        _way(
            701,
            WaterwayKind.LOCK,
            "L",
            [10, 11, 12],
            [(51.7500, -1.2600), (51.7510, -1.2610), (51.7520, -1.2620)],
        )
    ]
    gates = [
        WaterwayNode(
            osm_id=10,
            lat=51.7500,
            lon=-1.2600,
            tags={"waterway": "lock_gate"},
            kind=NodeKind.LOCK_GATE,
        ),
        WaterwayNode(
            osm_id=11,
            lat=51.7510,
            lon=-1.2610,
            tags={"waterway": "lock_gate"},
            kind=NodeKind.LOCK_GATE,
        ),
        WaterwayNode(
            osm_id=12,
            lat=51.7520,
            lon=-1.2620,
            tags={"waterway": "lock_gate"},
            kind=NodeKind.LOCK_GATE,
        ),
    ]
    feats = _features(ways, gates)
    g, report = attach_locks(build_graph(feats), feats)
    assert sum(d.get("locks", 0) for _, _, d in g.edges(data=True)) == 2
    assert report["lock_ways_attached"] == 1


def test_flight_level_shared_gate_counted_once():
    """Two LOCK ways sharing a gate endpoint (one chamber's exit IS the next's
    entrance — the cross-way staircase case): the shared gate bounds both
    chambers once, not twice. Two 2-node ways [1,2] and [2,3] where node 2 is a
    gate: G=3 (gates 1,2,3) => 2 chambers across the flight; each way's single
    segment has a downstream gate => 2 lock edges, not 3."""
    ways = [
        _way(800, WaterwayKind.LOCK, "Lower", [1, 2], [(51.7500, -1.2600), (51.7510, -1.2610)]),
        _way(801, WaterwayKind.LOCK, "Upper", [2, 3], [(51.7510, -1.2610), (51.7520, -1.2620)]),
    ]
    gates = [
        WaterwayNode(
            osm_id=1,
            lat=51.7500,
            lon=-1.2600,
            tags={"waterway": "lock_gate"},
            kind=NodeKind.LOCK_GATE,
        ),
        WaterwayNode(
            osm_id=2,
            lat=51.7510,
            lon=-1.2610,
            tags={"waterway": "lock_gate"},
            kind=NodeKind.LOCK_GATE,
        ),
        WaterwayNode(
            osm_id=3,
            lat=51.7520,
            lon=-1.2620,
            tags={"waterway": "lock_gate"},
            kind=NodeKind.LOCK_GATE,
        ),
    ]
    feats = _features(ways, gates)
    g, _ = attach_locks(build_graph(feats), feats)
    # G=3 distinct gates across the flight => 2 chambers => 2 lock edges, not 3
    # (the shared gate 2 is counted once, not by each way).
    assert sum(d.get("locks", 0) for _, _, d in g.edges(data=True)) == 2
    assert sum(1 for _, _, d in g.edges(data=True) if d.get("locks", 0) >= 1) == 2


def test_gateless_flight_floors_to_one_lock():
    """The gateless-flight floor (the 244 gateless flights in England): a LOCK
    way whose gates aren't mapped gets locks=1 on its first segment, not 0."""
    ways = [_way(900, WaterwayKind.LOCK, "L", [1, 2], [(51.7500, -1.2600), (51.7520, -1.2620)])]
    feats = _features(ways, [])  # no gate nodes
    g, report = attach_locks(build_graph(feats), feats)
    assert sum(d.get("locks", 0) for _, _, d in g.edges(data=True)) == 1
    assert report["lock_ways_attached"] == 1


# --- attach_locks lock-node tie-break (§3.5) — acceptance crit 7 ----------


def test_lock_node_tie_goes_to_lock_edge_not_canal_spur():
    """Acceptance crit 7: a lock=yes gate node coincident with BOTH a LOCK
    segment and a canal spur (sharing the junction node) gets locks=1 on the
    LOCK segment and leaves the spur at 0, deterministically (not by emission
    order)."""
    ways = [
        _way(100, WaterwayKind.LOCK, "Lock", [1, 2], [(51.7500, -1.2600), (51.7520, -1.2620)]),
        _way(
            200, WaterwayKind.CANAL, "Spur", [2, 3], [(51.7520, -1.2620), (51.7540, -1.2640)]
        ),  # shares node 2 with the lock
    ]
    nodes = [
        WaterwayNode(osm_id=999, lat=51.7520, lon=-1.2620, tags={"lock": "yes"}, kind=NodeKind.LOCK)
    ]
    feats = _features(ways, nodes)
    g, report = attach_locks(build_graph(feats), feats)
    lock_e = next(d for _, _, d in g.edges(data=True) if d["osm_way_id"] == 100)
    spur_e = next(d for _, _, d in g.edges(data=True) if d["osm_way_id"] == 200)
    assert lock_e["locks"] == 1
    assert spur_e["locks"] == 0
    assert report["lock_nodes_attached"] >= 1
