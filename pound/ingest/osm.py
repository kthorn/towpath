"""Bulk OSM reader: osmium tags-filter (CLI) -> filtered PBF -> pyosmium -> WaterwayFeatures.

Mirrors overpass.parse's contract: populates the same WaterwayFeatures IR via
the same pure filters functions. Unlike the Overpass reader, this fills
`node_ids` (pyosmium gives way-node refs), which lets build_graph's node-ref
authority unify ways at shared OSM junction nodes. Used by `pound-ingest build
england`.

`osmium` is an optional dependency (the `bulk` extra); tests needing it are
gated by the `bulk` pytest marker. `osmium-tool` is a system CLI prereq.
"""

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from pound.ingest import filters
from pound.ingest.filters import filter_navigable_ways
from pound.ingest.ir import (
    WaterwayFeatures,
    WaterwayKind,
    WaterwayNode,
    WaterwayWay,
)
from pound.ingest.prune import prune_non_navigable_infra

# Pinned OSM-filter expression (design §3.1, Scope D OQ-D1).
TAGS_FILTER_EXPR = r"""w/waterway=canal,river,fairway,lock,derelict_canal
w/disused:waterway
w/abandoned:waterway
w/lock=yes
n/waterway=lock_gate,mooring
n/lock=yes
n/leisure=marina
n/place
"""


def run_tags_filter(in_pbf: Path, out_pbf: Path) -> None:
    """Shell out once to `osmium tags-filter`. Raises FileNotFoundError if
    osmium is not installed (it's a documented system prereq)."""
    out_pbf = Path(out_pbf)
    out_pbf.parent.mkdir(parents=True, exist_ok=True)
    exprs = [line for line in TAGS_FILTER_EXPR.splitlines() if line.strip()]
    # --overwrite: the filtered PBF is a cache rebuilt on every `build england`
    # re-run (the D.3 curation loop). Without it osmium refuses to clobber the
    # stale file from the previous run, breaking idempotency.
    subprocess.run(
        ["osmium", "tags-filter", "--overwrite", "-o", str(out_pbf), str(in_pbf), *exprs],
        check=True,
    )


def read_pbf(pbf_path: Path) -> WaterwayFeatures:
    """Stream-parse a filtered PBF (or OSM XML) via pyosmium into WaterwayFeatures.

    Fills node_ids. source='geofabrik', fetched_at=PBF mtime, bbox=None
    (extract bbox not distilled in this scope).
    """
    import osmium

    ways: list[WaterwayWay] = []
    nodes: list[WaterwayNode] = []
    pbf_path = Path(pbf_path)

    class _Handler(osmium.SimpleHandler):
        def way(self, w):
            tags = {t.k: t.v for t in w.tags}
            if filters.is_derelict(tags):
                return
            kind = filters.classify_way(tags)
            if kind is None:
                return
            geom = []
            for n in w.nodes:
                if n.location.valid:
                    geom.append((n.location.lat, n.location.lon))
            if len(geom) < 2:
                return
            ways.append(
                WaterwayWay(
                    osm_id=w.id,
                    kind=kind,
                    name=tags.get("name"),
                    tags=tags,
                    node_ids=[n.ref for n in w.nodes],
                    geometry=geom,
                    dimensions=filters.extract_dimensions(tags),
                    has_tunnel=tags.get("tunnel") == "yes",
                    has_movable_bridge=(
                        "bridge:movable" in tags or tags.get("bridge") == "movable"
                    ),
                )
            )

        def node(self, n):
            tags = {t.k: t.v for t in n.tags} if n.tags else {}
            kind = filters.classify_node(tags)
            if kind is None:
                return
            if not n.location.valid:
                return
            nodes.append(
                WaterwayNode(
                    osm_id=n.id,
                    lat=n.location.lat,
                    lon=n.location.lon,
                    tags=tags,
                    kind=kind,
                )
            )

    _Handler().apply_file(str(pbf_path), locations=True)

    routable = {WaterwayKind.CANAL, WaterwayKind.RIVER, WaterwayKind.FAIRWAY}
    ways.sort(key=lambda w: (0 if w.kind in routable else 1, w.osm_id))

    fetched_at = datetime.fromtimestamp(pbf_path.stat().st_mtime, tz=UTC).isoformat()
    return WaterwayFeatures(
        ways=ways,
        nodes=nodes,
        source="geofabrik",
        fetched_at=fetched_at,
        bbox=None,
    )


def read_england(pbf_path: Path | None = None) -> WaterwayFeatures:
    """Tags-filter then read, then prune infra nodes on non-navigable ways
    and filter navigable ways. pbf_path defaults to POUND_PBF_PATH env or
    pound/data/england.osm.pbf. Filtered output lands beside it as
    england_waterways.osm.pbf (gitignored).

    Ordering: prune BEFORE filter. prune needs boat=no ways present to decide
    "all incidents non-navigable"; see the spec's load-bearing ordering note.
    """
    if pbf_path is None:
        pbf_path = Path(os.environ.get("POUND_PBF_PATH", "pound/data/england.osm.pbf"))
    pbf_path = Path(pbf_path)
    base = pbf_path.name.split(".")[0]
    filtered = pbf_path.parent / (base + "_waterways.osm.pbf")
    run_tags_filter(pbf_path, filtered)
    features = read_pbf(filtered)
    # prune BEFORE filter: see spec's load-bearing ordering note.
    features = prune_non_navigable_infra(features)
    features = filter_navigable_ways(features)
    return features
