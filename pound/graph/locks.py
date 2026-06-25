"""Attach lock counts to graph edges (design §4.2, §3.1).

Lock semantics (OQ-6, revised after live-OSM check): UK staircases tag each
chamber as waterway=canal + lock=yes (one way per chamber), reclassified to
WaterwayKind.LOCK by filters.classify_way. Each chamber is its own graph edge
(chamber ways chain by shared coordinates), so matching LOCK-kind ways by
osm_way_id and setting per-edge max(locks, 1) counts a staircase correctly —
5 chambers => 5 edges => 5 locks. lock=yes NODES on a non-LOCK edge increment
that edge per-node (defensive; rare in the wild). lock_gate nodes are counted
as gate metadata but do NOT increment the lock count. Orphans are reported.
"""

import copy
import math

import networkx as nx

from pound.graph.build import _haversine_m
from pound.ingest.ir import NodeKind, WaterwayFeatures, WaterwayKind


def _edge_point_dist_m(edge_geom: list[tuple[float, float]], lat: float, lon: float) -> float:
    """Min distance from (lat, lon) to any point on the edge geometry."""
    p = (lat, lon)
    return min(_haversine_m(p, pt) for pt in edge_geom) if edge_geom else math.inf


def attach_locks(
    graph: nx.Graph, features: WaterwayFeatures, tolerance_m: float = 25.0
) -> tuple[nx.Graph, dict]:
    g = copy.deepcopy(graph)
    report = {
        "lock_ways_attached": 0,
        "lock_nodes_attached": 0,
        "orphan_lock_ways": [],
        "orphan_lock_nodes": [],
        "lock_gate_nodes": 0,
    }

    # Lock ways: find their edge by matching osm_way_id.
    for way in features.ways:
        if way.kind != WaterwayKind.LOCK:
            continue
        match = next((d for _, _, d in g.edges(data=True) if d["osm_way_id"] == way.osm_id), None)
        if match is not None:
            match["locks"] = max(match["locks"], 1)
            report["lock_ways_attached"] += 1
        else:
            report["orphan_lock_ways"].append(way.osm_id)

    # Lock nodes: snap to nearest edge within tolerance.
    for node in features.nodes:
        if node.kind == NodeKind.LOCK_GATE:
            report["lock_gate_nodes"] += 1
            continue  # gates don't increment lock count
        if node.kind != NodeKind.LOCK:
            continue
        best_edge = None
        best_dist = math.inf
        for u, v, d in g.edges(data=True):
            dist = _edge_point_dist_m(d.get("geometry", []), node.lat, node.lon)
            if dist < best_dist:
                best_dist = dist
                best_edge = (u, v, d)
        if best_edge is not None and best_dist <= tolerance_m:
            best_edge[2]["locks"] = max(best_edge[2]["locks"], 1)
            report["lock_nodes_attached"] += 1
        else:
            report["orphan_lock_nodes"].append(node.osm_id)

    return g, report
