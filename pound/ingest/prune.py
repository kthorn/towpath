"""Infra-node prune: drop lock_gate/lock/mooring/movable_bridge/marina nodes
sitting *entirely* on non-navigable ways.

Pure: takes WaterwayFeatures, returns a new WaterwayFeatures with affected
nodes removed. `place` nodes are never removed (gazetteer relevance is
independent of waterway navigability). `ways` are never touched here.

Effective only when `WaterwayWay.node_ids` is populated (the pyosmium bulk
reader fills it). On the Overpass `out geom` path `node_ids` is empty on real
data, so no node is incident to any way and the function runs without dropping
(best-effort, not a silent drop — see the spec's bulk-effectiveness caveat).
"""

from pound.ingest.filters import classify_node, is_navigable
from pound.ingest.ir import NodeKind, WaterwayFeatures


def prune_non_navigable_infra(features: WaterwayFeatures) -> WaterwayFeatures:
    """Return a new WaterwayFeatures with infra nodes sitting entirely on
    non-navigable ways removed. `place` nodes are never removed.

    A non-`place` classified node is dropped iff (a) it is incident to at least
    one way via `WaterwayWay.node_ids` AND (b) every incident way is
    non-navigable (`is_navigable(tags) is False`). A node with no incident ways
    is kept (the post-filter cannot determine navigability by join — that is the
    Overpass no-op case).
    """
    # osm node id (str) -> set of incident way osm_ids
    incidents: dict[str, set[int]] = {}
    for w in features.ways:
        if not w.node_ids:
            continue
        for nid in w.node_ids:
            incidents.setdefault(str(nid), set()).add(w.osm_id)
    ways_by_id = {w.osm_id: w for w in features.ways}

    def _should_drop(node) -> bool:
        kind = classify_node(node.tags) if node.kind is None else node.kind
        # Defensive: handle any future NodeKind.OTHER (or new kinds) the same as
        # infra -- only PLACE is unconditionally kept. classify_node never emits
        # OTHER today, so this branch is forward-compat, not exercised yet.
        if kind is None or kind == NodeKind.PLACE:
            return False
        inc = incidents.get(str(node.osm_id))
        if not inc:
            return False  # no incidents -> kept (Overpass no-op case)
        # all incidents must be non-navigable; if any is navigable/untagged -> keep
        navigable_seen = False
        for wid in inc:
            w = ways_by_id.get(wid)
            if w is not None and is_navigable(w.tags):
                navigable_seen = True
                break
        return not navigable_seen

    kept_nodes = [n for n in features.nodes if not _should_drop(n)]
    return features.model_copy(update={"nodes": kept_nodes})
