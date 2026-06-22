"""Build/ingest report — seed of the design §4.3 / §7.1 build report.

Pure: takes a WaterwayFeatures IR, returns a plain dict of counts and flags you
can eyeball during dev or serialize to JSON. No network, no file IO.
"""

from collections import Counter

from pound.ingest.ir import WaterwayFeatures, WaterwayKind

_ROUTABLE = {WaterwayKind.CANAL, WaterwayKind.RIVER, WaterwayKind.FAIRWAY}


def summarize(features: WaterwayFeatures) -> dict:
    ways_by_kind = Counter(w.kind.value for w in features.ways)
    nodes_by_kind = Counter(n.kind.value for n in features.nodes)

    lock_count = sum(
        1 for w in features.ways if w.kind == WaterwayKind.LOCK
    ) + sum(1 for n in features.nodes if n.kind.value == "lock")

    def _has_any_dim(w) -> bool:
        d = w.dimensions
        return any(
            v is not None
            for v in (d.max_beam_m, d.max_length_m, d.max_draft_m, d.max_height_m)
        )

    routable_missing_dims = sum(
        1 for w in features.ways if w.kind in _ROUTABLE and not _has_any_dim(w)
    )

    return {
        "source": features.source,
        "fetched_at": features.fetched_at,
        "bbox": list(features.bbox) if features.bbox else None,
        "way_count": len(features.ways),
        "ways_by_kind": dict(ways_by_kind),
        "node_count": len(features.nodes),
        "nodes_by_kind": dict(nodes_by_kind),
        "lock_count": lock_count,
        "routable_ways_missing_all_dimensions": routable_missing_dims,
        "tunnel_ways": sum(1 for w in features.ways if w.has_tunnel),
        "movable_bridge_ways": sum(1 for w in features.ways if w.has_movable_bridge),
    }
