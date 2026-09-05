"""Infra-node prune: drop lock_gate/lock/turning_point/mooring/movable_bridge/marina nodes
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

_INCIDENT = 1
_NAVIGABLE = 2


def _infra_incident_states(features: WaterwayFeatures) -> dict[int, int]:
    target_ids = set()
    for node in features.nodes:
        kind = classify_node(node.tags) if node.kind is None else node.kind
        if kind is not None and kind != NodeKind.PLACE:
            target_ids.add(node.osm_id)

    states: dict[int, int] = {}
    for way in features.ways:
        way_state = _INCIDENT | (_NAVIGABLE if is_navigable(way.tags) else 0)
        for node_id in way.node_ids:
            if node_id in target_ids:
                states[node_id] = states.get(node_id, 0) | way_state
    return states


def _non_navigable_infra_ids(features: WaterwayFeatures) -> set[int]:
    return {
        node_id
        for node_id, state in _infra_incident_states(features).items()
        if state == _INCIDENT
    }


def prune_non_navigable_infra(features: WaterwayFeatures) -> WaterwayFeatures:
    """Return a new WaterwayFeatures with infra nodes sitting entirely on
    non-navigable ways removed. `place` nodes are never removed.

    A non-`place` classified node is dropped iff (a) it is incident to at least
    one way via `WaterwayWay.node_ids` AND (b) every incident way is
    non-navigable (`is_navigable(tags) is False`). A node with no incident ways
    is kept (the post-filter cannot determine navigability by join — that is the
    Overpass no-op case).
    """
    dropped_ids = _non_navigable_infra_ids(features)
    kept_nodes = [node for node in features.nodes if node.osm_id not in dropped_ids]
    return features.model_copy(update={"nodes": kept_nodes})
