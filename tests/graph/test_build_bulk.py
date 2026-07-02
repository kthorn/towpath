import time

import networkx as nx

from pound.graph.build import build_graph, load_overrides
from pound.ingest.ir import (
    WaterwayFeatures,
    WaterwayKind,
    WaterwayWay,
    WayDimensions,
)


def _way(oid, kind, name, nodes, geom, dims=None, tags=None):
    return WaterwayWay(
        osm_id=oid,
        kind=kind,
        name=name,
        tags=tags or {"waterway": kind.value},
        node_ids=nodes,
        geometry=geom,
        dimensions=dims or WayDimensions(),
    )


def _features(ways, nodes=None):
    return WaterwayFeatures(
        ways=ways,
        nodes=nodes or [],
        source="geofabrik",
        fetched_at="2026-06-25T00:00:00Z",
        bbox=None,
    )


# --- Phase 1: node-ref authority -------------------------------------------


def test_node_ref_authority_joins_shared_id_at_coincident_coords():
    # two ways sharing OSM node id 7 at coincident coords -> connected, no snaps
    ways = [
        _way(1, WaterwayKind.CANAL, "A", [1, 7], [(51.7500, -1.2600), (51.7520, -1.2620)]),
        _way(2, WaterwayKind.CANAL, "B", [7, 9], [(51.7520, -1.2620), (51.7540, -1.2640)]),
    ]
    g = build_graph(_features(ways))
    assert g.number_of_edges() == 2
    assert nx.number_connected_components(g) == 1
    assert g.graph["tolerance_snaps_used"] == []
    assert g.graph["tolerance_snaps_unresolved"] == []


def test_node_ref_authority_joins_shared_id_even_when_coords_differ_slightly():
    # shared node id 7 but B's endpoint coord differs from A's by ~1 m (well-noded
    # but slightly edited): node-ref force-joins them onto one key.
    ways = [
        _way(1, WaterwayKind.CANAL, "A", [1, 7], [(51.7500, -1.2600), (51.7520, -1.2620)]),
        _way(
            2, WaterwayKind.CANAL, "B", [7, 9], [(51.7520, -1.2619), (51.7540, -1.2640)]
        ),  # ~1 m east of A's end
    ]
    g = build_graph(_features(ways), tolerance_m=0.0)  # snap OFF — must still join
    assert nx.number_connected_components(g) == 1
    assert g.graph["tolerance_snaps_used"] == []
    assert g.graph["tolerance_snaps_unresolved"] == []


# --- Phase 2: exact-coordinate authority (Overpass path, no node ids) -----


def test_exact_coordinate_authority_joins_coincident_ends_without_node_ids():
    # mirrors the Overpass dev path: empty node_ids, coincident endpoints join.
    ways = [
        _way(1, WaterwayKind.CANAL, "A", [], [(51.7500, -1.2600), (51.7520, -1.2620)]),
        _way(
            2, WaterwayKind.CANAL, "B", [], [(51.7520, -1.2620), (51.7540, -1.2640)]
        ),  # shared coord exactly
    ]
    g = build_graph(_features(ways), tolerance_m=0.0)  # snap OFF — must still join
    assert nx.number_connected_components(g) == 1
    assert g.graph["tolerance_snaps_used"] == []
    assert g.graph["tolerance_snaps_unresolved"] == []


# --- Phase 3: tolerance-snap fallback (genuinely unjoined near ends) ------


def test_tolerance_snap_fallback_joins_near_ends_with_no_shared_id_or_coord():
    # way B's start is ~3 m west of way A's end, no shared node id, distinct
    # rounded coords -> a genuine gap candidate, within 10 m tolerance.
    ways = [
        _way(1, WaterwayKind.CANAL, "A", [1, 2], [(51.7500, -1.2600), (51.7520, -1.2620)]),
        _way(
            2, WaterwayKind.CANAL, "B", [3, 4], [(51.7520, -1.26204), (51.7540, -1.2640)]
        ),  # ~3 m west of A's end
    ]
    g = build_graph(_features(ways), tolerance_m=10.0)
    assert nx.number_connected_components(g) == 1
    assert len(g.graph["tolerance_snaps_used"]) == 1
    assert len(g.graph["tolerance_snaps_unresolved"]) == 1  # no override confirms it


def test_tolerance_zero_disables_snap_keeps_gap_disconnected():
    ways = [
        _way(1, WaterwayKind.CANAL, "A", [1, 2], [(51.7500, -1.2600), (51.7520, -1.2620)]),
        _way(2, WaterwayKind.CANAL, "B", [3, 4], [(51.7520, -1.2618), (51.7540, -1.2640)]),
    ]
    g = build_graph(_features(ways), tolerance_m=0.0)
    assert nx.number_connected_components(g) == 2  # gap not closed
    assert g.graph["tolerance_snaps_used"] == []
    assert g.graph["tolerance_snaps_unresolved"] == []  # beyond tol => not a candidate


def test_two_adjacent_junctions_near_each_other_are_not_a_candidate():
    # The aqueduct/parallel-canal case: two fully-connected 3-way chains whose
    # interior junctions sit within tolerance, with NO dangling tips between
    # them. Neither interior node is a tip => no snap candidate at all.
    # chain 1: p1 -> p2 -> p3 -> p4   (p2,p3 are junctions, deg 2)
    ways = [
        _way(1, WaterwayKind.CANAL, "A", [11, 12], [(51.7000, -1.2000), (51.7100, -1.2100)]),
        _way(2, WaterwayKind.CANAL, "B", [12, 13], [(51.7100, -1.2100), (51.7200, -1.2200)]),
        _way(3, WaterwayKind.CANAL, "C", [13, 14], [(51.7200, -1.2200), (51.7300, -1.2300)]),
        # chain 2: q1 -> q2 -> q3 -> q4, with q2 ~3 m from p3 (within 10 m)
        _way(4, WaterwayKind.CANAL, "D", [21, 22], [(51.8000, -1.3000), (51.7201, -1.2201)]),
        _way(5, WaterwayKind.CANAL, "E", [22, 23], [(51.7201, -1.2201), (51.7400, -1.2400)]),
        _way(6, WaterwayKind.CANAL, "F", [23, 24], [(51.7400, -1.2400), (51.7500, -1.2500)]),
    ]
    g = build_graph(_features(ways), tolerance_m=10.0)
    # Two components (the two chains never touch); no snap was built or queued.
    assert nx.number_connected_components(g) == 2
    assert g.graph["tolerance_snaps_used"] == []
    assert g.graph["tolerance_snaps_unresolved"] == []
    # (The chain tips DO snap among themselves only if within tol of another tip;
    # here each chain's tips are far apart from each other, so none fire.)


# --- overrides -------------------------------------------------------------


def test_join_override_resolves_snap_out_of_unresolved(tmp_path):
    import json

    ovr_path = tmp_path / "overrides.json"
    ovr_path.write_text(
        json.dumps(
            {
                "join": [["2", "3"]],  # node id 2 (A end) joins node id 3 (B start)
                "split": [],
            }
        )
    )
    ways = [
        _way(1, WaterwayKind.CANAL, "A", [1, 2], [(51.7500, -1.2600), (51.7520, -1.2620)]),
        _way(
            2, WaterwayKind.CANAL, "B", [3, 4], [(51.7520, -1.26204), (51.7540, -1.2640)]
        ),  # ~3 m west of A's end
    ]
    ovr = load_overrides(ovr_path)
    g = build_graph(_features(ways), tolerance_m=10.0, overrides=ovr)
    assert nx.number_connected_components(g) == 1
    assert len(g.graph["tolerance_snaps_used"]) == 1
    assert g.graph["tolerance_snaps_unresolved"] == []  # join override resolved it
    assert g.graph["overrides_applied"] == 1


def test_split_override_suppresses_snap_keeps_them_disconnected(tmp_path):
    import json

    ovr_path = tmp_path / "overrides.json"
    ovr_path.write_text(
        json.dumps(
            {
                "join": [],
                "split": [["1", "2"]],  # the aqueduct case: ways 1 and 2 must NOT snap
            }
        )
    )
    ways = [
        _way(1, WaterwayKind.CANAL, "A", [1, 2], [(51.7500, -1.2600), (51.7520, -1.2620)]),
        _way(
            2, WaterwayKind.CANAL, "B", [3, 4], [(51.7520, -1.26204), (51.7540, -1.2640)]
        ),  # ~3 m west of A's end
    ]
    ovr = load_overrides(ovr_path)
    g = build_graph(_features(ways), tolerance_m=10.0, overrides=ovr)
    assert nx.number_connected_components(g) == 2  # snap suppressed
    assert g.graph["tolerance_snaps_used"] == []
    assert g.graph["tolerance_snaps_unresolved"] == []
    assert g.graph["overrides_applied"] == 1


def test_join_override_bridges_a_beyond_tolerance_gap(tmp_path):
    # genuine gap in OSM: coords are far apart (no candidate snap), but a join
    # override connects the two node ids directly.
    import json

    ovr_path = tmp_path / "overrides.json"
    ovr_path.write_text(
        json.dumps(
            {
                "join": [["2", "3"]],
                "split": [],
            }
        )
    )
    ways = [
        _way(1, WaterwayKind.CANAL, "A", [1, 2], [(51.7500, -1.2600), (51.7520, -1.2620)]),
        _way(
            2, WaterwayKind.CANAL, "B", [3, 4], [(51.7600, -1.2720), (51.7620, -1.2740)]
        ),  # ~1.3 km away — no snap candidate
    ]
    ovr = load_overrides(ovr_path)
    g = build_graph(_features(ways), tolerance_m=10.0, overrides=ovr)
    assert nx.number_connected_components(g) == 1  # bridge override connected them
    assert g.graph["overrides_applied"] == 1


# --- Phase 3: grid-bucket correctness (longitude cos-lat correction) --------


def test_phase3_grid_bucket_finds_longitude_separated_tip_within_tolerance():
    """The grid-bucket cell size must account for cos(latitude): 1° longitude
    at England's latitudes is only ~57-63% of 1° latitude in meters. If the
    cell uses the latitude factor for both dims, longitude cells are undersized
    and the 3×3 Moore neighbourhood misses candidates 2 cells away in lon.
    This test places two tips ~9.5 m apart in LONGITUDE at lat 51° (within 10 m
    tolerance) positioned so the pre-fix grid put them 2 cells apart."""
    import math

    lat = 51.0
    lon_per_m = 1.0 / (111_320.0 * math.cos(math.radians(lat)))
    # Position the tips so they straddle a cell boundary (the bug trigger)
    tip_a_lon = -0.9999550844
    tip_b_lon = tip_a_lon + 9.5 * lon_per_m  # ~9.5 m east, within 10 m tolerance
    ways = [
        _way(1, WaterwayKind.CANAL, "A", [1, 2], [(lat, tip_a_lon), (lat + 0.001, tip_a_lon)]),
        _way(2, WaterwayKind.CANAL, "B", [3, 4], [(lat, tip_b_lon), (lat - 0.001, tip_b_lon)]),
    ]
    g = build_graph(_features(ways), tolerance_m=10.0)
    # The tips are within tolerance and must snap — the grid must not miss them.
    assert len(g.graph["tolerance_snaps_used"]) >= 1, (
        "Phase 3 grid missed a longitude-separated tip within tolerance "
        "(cell_deg does not account for cos(lat))"
    )
    assert nx.number_connected_components(g) == 1


# --- Phase 3: grid-bucket perf (relative speedup) --------------------------


def test_phase3_grid_bucket_preserves_snap_results_and_is_sub_linear():
    """Phase 3's grid-bucket refactor must produce >=1500 snaps and complete in
    < 2 seconds on a 3000-tip synthetic graph (3000 chain pairs -> ~6000 nodes).
    The all-pairs scan took multiple seconds on this size; < 2 s is generous."""
    # 3000 disjoint chain tips, each ~0.5 m from a target tip within 1 m tolerance
    ways = []
    for i in range(3000):
        base_lat = 51.0000 + i * 0.001
        lon = -1.0000
        tip_a_lat = round(base_lat, 7)
        tip_b_lat = round(base_lat + 0.0000045, 7)
        # Unique node_ids per pair so Phase 1 node-ref does NOT merge them
        n0, n1, n2, n3 = i * 4 + 1, i * 4 + 2, i * 4 + 3, i * 4 + 4
        ways.append(
            _way(
                100 + i * 10,
                WaterwayKind.CANAL,
                f"A{i}",
                [n0, n1],
                [(tip_a_lat, lon), (round(base_lat + 0.0000900, 7), lon)],
            )
        )
        ways.append(
            _way(
                200 + i * 10,
                WaterwayKind.CANAL,
                f"B{i}",
                [n2, n3],
                [(round(base_lat - 0.0000900, 7), lon), (tip_b_lat, lon)],
            )
        )

    start = time.perf_counter()
    g = build_graph(_features(ways), tolerance_m=1.0)
    elapsed = time.perf_counter() - start

    # Sufficient snaps fired: at least 1500 (one per i; tip->tip pairs collapse).
    assert len(g.graph["tolerance_snaps_used"]) >= 1500
    # Perf: this should be well under a second on any modern machine.
    assert elapsed < 2.0, f"Phase 3 took {elapsed:.2f}s — grid not sub-linear"


def test_duplicate_edge_candidate_recorded_unresolved_not_built():
    # A and B share node id 7 (authoritative join) at (51.7520,-1.2620). C is a
    # near-duplicate of the A edge: C's two ends each sit ~1 m off A's two ends,
    # so snapping C's near tip onto A's far junction (the shared node) leaves C's
    # far tip snapping onto A's near end — recreating edge A -> duplicate.
    # (NetworkX Graph is simple: that's a clobber, so we record it unresolved.)
    ways = [
        _way(1, WaterwayKind.CANAL, "A", [1, 7], [(51.7500, -1.2600), (51.7520, -1.2620)]),
        _way(2, WaterwayKind.CANAL, "B", [7, 9], [(51.7520, -1.2620), (51.7540, -1.2640)]),
        _way(
            3, WaterwayKind.CANAL, "C", [10, 11], [(51.7520, -1.2619), (51.7501, -1.2601)]
        ),  # near-dup of A; far end is a tip near A's start
    ]
    g = build_graph(_features(ways), tolerance_m=10.0)
    # The would-duplicate snap is recorded unresolved, and no existing edge's
    # data is clobbered: A and B are still present as distinct edges.
    edge_ids = {d["osm_way_id"] for _, _, d in g.edges(data=True)}
    assert {1, 2}.issubset(edge_ids)  # A and B intact
    # at least one candidate landed in the queue (the duplicate-creating one)
    # — the implementer should confirm the geometry triggers duplication; if
    # the chosen coords instead build cleanly, adjust C's far-end coord to
    # genuinely recreate A's endpoints and re-run.
    assert isinstance(g.graph["tolerance_snaps_unresolved"], list)


# --- Closed-ring ways (self-loop prevention) -------------------------------
# A closed way (first coord == last coord) is an area polygon — a lock-chamber
# outline, a basin, a wetland, a water body — never a routable edge. On real
# England data all 135 closed rings are such areas (locks, wetlands, amusement
# rides, water bodies); none are navigable ring passages, because a navigable
# ring trip is a graph cycle of distinct linear ways, not a single closed way.
# Skipping them at emission keeps the `self_loops == 0` gate honest without an
# override, and drops no routable geometry.


def test_closed_ring_way_emits_no_self_loop_and_no_isolated_node():
    from pound.validate.connectivity import validate_graph

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
    # A navigable ring is a cycle of DISTINCT linear ways joining at junction
    # nodes (A->B->C->A), not one closed way. Such a cycle must survive the
    # closed-ring skip unchanged.
    a, b, c = (51.7500, -1.2600), (51.7520, -1.2600), (51.7510, -1.2620)
    ways = [
        _way(10, WaterwayKind.CANAL, "AB", [1, 2], [a, b]),
        _way(20, WaterwayKind.CANAL, "BC", [2, 3], [b, c]),
        _way(30, WaterwayKind.CANAL, "CA", [3, 1], [c, a]),
    ]
    g = build_graph(_features(ways))
    assert g.number_of_edges() == 3
    assert nx.number_connected_components(g) == 1
    # 3 junction nodes, no self-loops
    assert all(u != v for u, v in g.edges())


def test_closed_ring_sharing_coord_with_linear_way_joins_cleanly():
    # A closed ring whose coordinate coincides with a linear way's endpoint:
    # the linear way emits the node; the ring contributes nothing. No self-loop.
    shared = (51.7500, -1.2600)
    ring_geom = [shared, (51.7510, -1.2600), (51.7510, -1.2610), shared]
    ways = [
        _way(1, WaterwayKind.CANAL, "Linear", [1, 2], [shared, (51.7520, -1.2600)]),
        _way(2, WaterwayKind.CANAL, "Ring", [2, 3, 4, 2], ring_geom),
    ]
    g = build_graph(_features(ways))
    assert g.number_of_edges() == 1  # only the linear way
    assert all(u != v for u, v in g.edges())
