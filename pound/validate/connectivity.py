"""Build-time graph validation -> report dict (design §4.3, §7.1).

Pure over a built (and lock-attached) graph. Produces the same kind of report
dict as ingest/summarize.py — component sizes, orphans, filter sanity, tag
coverage, degenerate geometry. Not a runtime checker (design §1, §7).
"""

import networkx as nx

from pound.ingest.ir import WaterwayKind


def validate_graph(graph: nx.Graph, lock_report: dict) -> dict:
    components = list(nx.connected_components(graph))
    sizes = sorted((len(c) for c in components), reverse=True)

    derelict = 0
    missing_dims = 0
    zero_length = 0
    self_loops = 0
    for u, v, d in graph.edges(data=True):
        if u == v:
            self_loops += 1
        if d.get("length_m", 0.0) == 0.0:
            zero_length += 1
        # derelict kinds should never reach the graph (build excludes them);
        # count any non-routable kind that slipped through as derelict.
        if d.get("kind") not in {
            WaterwayKind.CANAL,
            WaterwayKind.RIVER,
            WaterwayKind.FAIRWAY,
            WaterwayKind.LOCK,
        }:
            derelict += 1
        dims = d.get("dimensions")
        if dims is None or not any(
            getattr(dims, f) is not None
            for f in ("max_beam_m", "max_length_m", "max_draft_m", "max_height_m")
        ):
            missing_dims += 1

    # Augmented Scope D keys (additive — read graph.graph defensively).
    gg = graph.graph
    snaps_used = list(gg.get("tolerance_snaps_used", []))
    snaps_unresolved = list(gg.get("tolerance_snaps_unresolved", []))
    overrides_applied = int(gg.get("overrides_applied", 0))

    gaz = gg.get("gazetteer", {})
    place_in_gaz = sum(1 for v in gaz.values() if not isinstance(v, list)) + sum(
        len(v) for v in gaz.values() if isinstance(v, list)
    )

    named_nodes = 0
    for _k, data in graph.nodes(data=True):
        if "name" in data:
            named_nodes += 1

    ambiguous = sorted([name for name, v in gaz.items() if isinstance(v, list)]) if gaz else []

    return {
        "component_count": len(components),
        "largest_component_size": sizes[0] if sizes else 0,
        "component_sizes": sizes,
        "orphan_lock_ways": list(lock_report.get("orphan_lock_ways", [])),
        "orphan_lock_nodes": list(lock_report.get("orphan_lock_nodes", [])),
        "derelict_edges": derelict,
        "edges_missing_dims": missing_dims,
        "zero_length_edges": zero_length,
        "self_loops": self_loops,
        "total_edges": graph.number_of_edges(),
        "total_nodes": graph.number_of_nodes(),
        "overrides_applied": overrides_applied,
        "tolerance_snaps_used": snaps_used,
        "tolerance_snaps_unresolved": snaps_unresolved,
        "place_nodes_seen": int(gg.get("place_nodes_seen", 0)),
        "place_nodes_in_gazetteer": place_in_gaz,
        "named_nodes_in_graph": named_nodes,
        "ambiguous_place_names": ambiguous,
    }
