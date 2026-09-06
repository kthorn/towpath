"""Bulk OSM reader: osmium tags-filter (CLI) -> filtered PBF -> pyosmium -> WaterwayFeatures.

Mirrors overpass.parse's contract: populates the same WaterwayFeatures IR via
the same pure filters functions. Unlike the Overpass reader, this fills
`node_ids` (pyosmium gives way-node refs), which lets build_graph's node-ref
authority unify ways at shared OSM junction nodes. Used by `pound-ingest build
great-britain`.

`osmium` is an optional dependency (the `bulk` extra); tests needing it are
gated by the `bulk` pytest marker. `osmium-tool` is a system CLI prereq.
"""

import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pound.models import OsmElementType, WaterwayKind
from shapely import wkt as shapely_wkt

from pound_build.ingest import filters
from pound_build.ingest.diagnostics import PoiDiagnostics
from pound_build.ingest.filters import filter_navigable_ways
from pound_build.ingest.ir import (
    PoiCandidate,
    WaterwayFeatures,
    WaterwayNode,
    WaterwayWay,
)
from pound_build.ingest.pois import classify_poi, normalize_source_tags
from pound_build.ingest.profile import BuildProfiler
from pound_build.ingest.prune import prune_non_navigable_infra

# Pinned OSM-filter expression (design §3.1, Scope D OQ-D1).
TAGS_FILTER_EXPR = r"""w/waterway=canal,river,fairway,lock,derelict_canal
w/disused:waterway
w/abandoned:waterway
w/lock=yes
n/waterway=lock_gate,mooring,turning_point
n/lock=yes
n/bridge:movable
n/bridge=movable
n/leisure=marina
n/place
nwr/waterway=water_point,sanitary_station,fuel
nwr/amenity=pub,cafe,restaurant,fuel,sanitary_dump_station,taxi
nwr/shop=supermarket,convenience,bakery,greengrocer,butcher,deli,general
nwr/leisure=marina
nwr/mooring
nwr/railway=station,halt
nwr/public_transport=platform,stop_position
nwr/highway=footway,path,pedestrian,steps,bus_stop
nwr/entrance
nwr/barrier=gate,stile,kissing_gate,cycle_barrier
"""


def _create_wkt(factory, method: str, obj) -> str | None:
    """Return WKT, or None when pyosmium cannot construct the source geometry."""
    try:
        return getattr(factory, method)(obj)
    except RuntimeError:
        return None


AreaKey = tuple[OsmElementType, int]


class _PendingAreas:
    def __init__(self) -> None:
        self._pending: dict[AreaKey, int | None] = {}
        self._emitted: set[AreaKey] = set()

    def add(self, key: AreaKey, *, node_count: int | None) -> None:
        if key not in self._emitted:
            self._pending[key] = node_count

    def should_emit(self, key: AreaKey) -> bool:
        return key not in self._emitted

    def mark_emitted(self, key: AreaKey) -> None:
        self._emitted.add(key)
        self._pending.pop(key, None)

    def unresolved(self):
        return self._pending.items()

    def release(self) -> None:
        self._pending.clear()
        self._emitted.clear()

    def __len__(self) -> int:
        return len(self._pending)


def _normalized_geometry_wkt(geometry_wkt: str, geometry_source: str) -> str:
    if geometry_source != "area":
        return geometry_wkt
    geometry = shapely_wkt.loads(geometry_wkt)
    if geometry.geom_type == "MultiPolygon" and len(geometry.geoms) == 1:
        return geometry.geoms[0].wkt
    return geometry_wkt


def run_tags_filter(in_pbf: Path, out_pbf: Path) -> None:
    """Shell out once to `osmium tags-filter`. Raises FileNotFoundError if
    osmium is not installed (it's a documented system prereq)."""
    out_pbf = Path(out_pbf)
    out_pbf.parent.mkdir(parents=True, exist_ok=True)
    exprs = [line for line in TAGS_FILTER_EXPR.splitlines() if line.strip()]
    # --overwrite: rebuild the filtered PBF on every `build great-britain`
    # re-run (the D.3 curation loop). Without it osmium refuses to clobber the
    # stale file from the previous run, breaking idempotency.
    subprocess.run(
        ["osmium", "tags-filter", "--overwrite", "-o", str(out_pbf), str(in_pbf), *exprs],
        check=True,
    )


def read_waterway_features(
    pbf_path: Path, *, profile_counts: dict | None = None
) -> WaterwayFeatures:
    """Read only graph-building waterways and infrastructure from a filtered PBF."""
    import osmium

    ways: list[WaterwayWay] = []
    nodes: list[WaterwayNode] = []
    pbf_path = Path(pbf_path)
    scanned = 0

    for obj in osmium.FileProcessor(str(pbf_path)).with_locations():
        scanned += 1
        tags = {tag.k: tag.v for tag in obj.tags}
        object_name = type(obj).__name__
        if object_name == "Way":
            if filters.is_derelict(tags):
                continue
            kind = filters.classify_way(tags)
            if kind is None:
                continue
            node_ids: list[int] = []
            geometry: list[tuple[float, float]] = []
            for node_ref in obj.nodes:
                try:
                    lat = node_ref.location.lat
                    lon = node_ref.location.lon
                except osmium.InvalidLocationError:
                    continue
                node_ids.append(node_ref.ref)
                geometry.append((lat, lon))
            if len(geometry) >= 2:
                ways.append(
                    WaterwayWay(
                        osm_id=obj.id,
                        kind=kind,
                        name=tags.get("name"),
                        tags=tags,
                        node_ids=node_ids,
                        geometry=geometry,
                        dimensions=filters.extract_dimensions(tags),
                        has_tunnel=tags.get("tunnel") == "yes",
                        has_movable_bridge=(
                            "bridge:movable" in tags or tags.get("bridge") == "movable"
                        ),
                    )
                )
        elif object_name == "Node":
            kind = filters.classify_node(tags)
            if kind is not None and obj.location.valid:
                nodes.append(
                    WaterwayNode(
                        osm_id=obj.id,
                        lat=obj.location.lat,
                        lon=obj.location.lon,
                        tags=tags,
                        kind=kind,
                    )
                )

    routable = {WaterwayKind.CANAL, WaterwayKind.RIVER, WaterwayKind.FAIRWAY}
    ways.sort(key=lambda way: (0 if way.kind in routable else 1, way.osm_id))
    if profile_counts is not None:
        profile_counts.update(scanned=scanned, ways=len(ways), nodes=len(nodes))
    return WaterwayFeatures(
        ways=ways,
        nodes=nodes,
        source="geofabrik",
        fetched_at=datetime.fromtimestamp(pbf_path.stat().st_mtime, tz=UTC).isoformat(),
        bbox=None,
    )


def stream_linear_pois(
    pbf_path: Path,
    consume: Callable[[PoiCandidate], None],
    diagnostics: PoiDiagnostics,
    profile_counts: dict | None = None,
) -> None:
    """Attach-ready stream of node and path-derived POIs without area assembly."""
    import osmium

    pbf_path = Path(pbf_path)
    wkt_factory = osmium.geom.WKTFactory()
    scanned = 0
    classified = 0
    emitted = 0

    for obj in osmium.FileProcessor(str(pbf_path)).with_locations():
        scanned += 1
        object_name = type(obj).__name__
        if object_name == "Way":
            tags = {tag.k: tag.v for tag in obj.tags}
            if filters.is_derelict(tags):
                continue
            if tags.get("highway") not in {"footway", "path", "pedestrian"}:
                continue
            osm_type = OsmElementType.WAY
            geometry_source = "derived_path"
            geometry_wkt = _create_wkt(wkt_factory, "create_linestring", obj)
        elif object_name == "Node":
            tags = {tag.k: tag.v for tag in obj.tags}
            osm_type = OsmElementType.NODE
            geometry_source = "point"
            geometry_wkt = wkt_factory.create_point(obj) if obj.location.valid else None
        else:
            continue

        classifications = classify_poi(tags)
        for diagnostic in classifications.skips:
            diagnostics.record(
                diagnostic.reason,
                f"{osm_type.value}/{obj.id}:{diagnostic.key}={diagnostic.value}",
            )
        classified += len(classifications)
        if not classifications:
            continue
        if geometry_wkt is None:
            if osm_type == OsmElementType.WAY:
                diagnostics.record("invalid_geometry", f"way/{obj.id}")
            continue
        for classification in classifications:
            consume(
                PoiCandidate(
                    osm_type=osm_type,
                    osm_id=obj.id,
                    category=classification.category,
                    kind=classification.kind,
                    name=tags.get("name"),
                    tags=normalize_source_tags(tags, classification),
                    geometry_wkt=geometry_wkt,
                    geometry_source=geometry_source,
                )
            )
            emitted += 1

    if profile_counts is not None:
        profile_counts.update(scanned=scanned, classified=classified, emitted=emitted)


def stream_area_pois(
    pbf_path: Path,
    consume: Callable[[PoiCandidate], None],
    diagnostics: PoiDiagnostics,
    profile_counts: dict | None = None,
) -> None:
    """Attach-ready stream of polygon POIs with pass-local area bookkeeping."""
    import osmium

    pbf_path = Path(pbf_path)
    wkt_factory = osmium.geom.WKTFactory()
    pending_areas = _PendingAreas()
    scanned = 0
    classified = 0
    emitted = 0

    for obj in osmium.FileProcessor(str(pbf_path)).with_locations().with_areas():
        scanned += 1
        object_name = type(obj).__name__
        tags = {tag.k: tag.v for tag in obj.tags}
        if object_name == "Way":
            if filters.is_derelict(tags):
                continue
            if tags.get("highway") in {"footway", "path", "pedestrian"}:
                continue
            osm_type = OsmElementType.WAY
            classifications = classify_poi(tags)
            for diagnostic in classifications.skips:
                diagnostics.record(
                    diagnostic.reason,
                    f"way/{obj.id}:{diagnostic.key}={diagnostic.value}",
                )
            classified += len(classifications)
            if classifications:
                pending_areas.add((osm_type, obj.id), node_count=len(obj.nodes))
            continue
        if object_name == "Relation":
            osm_type = OsmElementType.RELATION
            classifications = classify_poi(tags)
            for diagnostic in classifications.skips:
                diagnostics.record(
                    diagnostic.reason,
                    f"relation/{obj.id}:{diagnostic.key}={diagnostic.value}",
                )
            classified += len(classifications)
            if classifications:
                pending_areas.add((osm_type, obj.id), node_count=None)
            continue
        if object_name != "Area":
            continue
        if (
            obj.from_way()
            and tags.get("highway") in {"footway", "path", "pedestrian"}
            and not filters.is_derelict(tags)
        ):
            continue

        osm_type = OsmElementType.WAY if obj.from_way() else OsmElementType.RELATION
        osm_id = obj.orig_id()
        key = (osm_type, osm_id)
        classifications = classify_poi(tags)
        if not classifications or not pending_areas.should_emit(key):
            continue
        geometry_wkt = _create_wkt(wkt_factory, "create_multipolygon", obj)
        if geometry_wkt is None:
            continue
        geometry_wkt = _normalized_geometry_wkt(geometry_wkt, "area")
        for classification in classifications:
            consume(
                PoiCandidate(
                    osm_type=osm_type,
                    osm_id=osm_id,
                    category=classification.category,
                    kind=classification.kind,
                    name=tags.get("name"),
                    tags=normalize_source_tags(tags, classification),
                    geometry_wkt=geometry_wkt,
                    geometry_source="area",
                )
            )
            emitted += 1
        pending_areas.mark_emitted(key)

    pending_count = len(pending_areas)
    for (osm_type, osm_id), node_count in pending_areas.unresolved():
        if osm_type == OsmElementType.RELATION:
            reason = "incomplete_relation_geometry"
        else:
            reason = "missing_area_geometry" if (node_count or 0) < 2 else "invalid_geometry"
        diagnostics.record(reason, f"{osm_type.value}/{osm_id}")
    if profile_counts is not None:
        profile_counts.update(
            scanned=scanned,
            classified=classified,
            emitted=emitted,
            pending_areas=pending_count,
        )
    pending_areas.release()


def read_pbf(pbf_path: Path, *, profile_counts: dict | None = None) -> WaterwayFeatures:
    """Stream-parse a filtered PBF (or OSM XML) via pyosmium into WaterwayFeatures.

    Fills node_ids. source='geofabrik', fetched_at=PBF mtime, bbox=None
    (extract bbox not distilled in this scope).
    """
    import osmium

    ways: list[WaterwayWay] = []
    nodes: list[WaterwayNode] = []
    candidates: dict[tuple[OsmElementType, int, str], PoiCandidate] = {}
    diagnostics = PoiDiagnostics()
    pending_areas = _PendingAreas()
    pbf_path = Path(pbf_path)

    def emit(osm_type, osm_id, tags, geometry_wkt, geometry_source, classifications) -> None:
        geometry_wkt = _normalized_geometry_wkt(geometry_wkt, geometry_source)
        for classification in classifications:
            candidate = PoiCandidate(
                osm_type=osm_type,
                osm_id=osm_id,
                category=classification.category,
                kind=classification.kind,
                name=tags.get("name"),
                tags=normalize_source_tags(tags, classification),
                geometry_wkt=geometry_wkt,
                geometry_source=geometry_source,
            )
            candidates.setdefault(candidate.identity, candidate)

    wkt_factory = osmium.geom.WKTFactory()
    processor = osmium.FileProcessor(str(pbf_path)).with_locations().with_areas()
    for obj in processor:
        tags = {tag.k: tag.v for tag in obj.tags}
        object_name = type(obj).__name__
        if object_name == "Way":
            w = obj
            if filters.is_derelict(tags):
                continue
            kind = filters.classify_way(tags)
            if kind is not None:
                node_ids: list[int] = []
                geom: list[tuple[float, float]] = []
                for node_ref in w.nodes:
                    try:
                        lat = node_ref.location.lat
                        lon = node_ref.location.lon
                    except osmium.InvalidLocationError:
                        continue
                    node_ids.append(node_ref.ref)
                    geom.append((lat, lon))
                if len(geom) >= 2:
                    ways.append(
                        WaterwayWay(
                            osm_id=w.id,
                            kind=kind,
                            name=tags.get("name"),
                            tags=tags,
                            node_ids=node_ids,
                            geometry=geom,
                            dimensions=filters.extract_dimensions(tags),
                            has_tunnel=tags.get("tunnel") == "yes",
                            has_movable_bridge=(
                                "bridge:movable" in tags or tags.get("bridge") == "movable"
                            ),
                        )
                    )
            classifications = classify_poi(tags)
            for diagnostic in classifications.skips:
                diagnostics.record(
                    diagnostic.reason, f"way/{w.id}:{diagnostic.key}={diagnostic.value}"
                )
            if classifications:
                if tags.get("highway") in {"footway", "path", "pedestrian"}:
                    geometry_wkt = _create_wkt(wkt_factory, "create_linestring", w)
                    if geometry_wkt is None:
                        diagnostics.record("invalid_geometry", f"way/{w.id}")
                    else:
                        emit(
                            OsmElementType.WAY,
                            w.id,
                            tags,
                            geometry_wkt,
                            "derived_path",
                            classifications,
                        )
                else:
                    pending_areas.add((OsmElementType.WAY, w.id), node_count=len(w.nodes))
        elif object_name == "Node":
            n = obj
            classifications = classify_poi(tags)
            for diagnostic in classifications.skips:
                diagnostics.record(
                    diagnostic.reason, f"node/{n.id}:{diagnostic.key}={diagnostic.value}"
                )
            if classifications and n.location.valid:
                emit(
                    OsmElementType.NODE,
                    n.id,
                    tags,
                    wkt_factory.create_point(n),
                    "point",
                    classifications,
                )
            kind = filters.classify_node(tags)
            if kind is not None and n.location.valid:
                nodes.append(
                    WaterwayNode(
                        osm_id=n.id, lat=n.location.lat, lon=n.location.lon, tags=tags, kind=kind
                    )
                )
        elif object_name == "Relation":
            classifications = classify_poi(tags)
            for diagnostic in classifications.skips:
                diagnostics.record(
                    diagnostic.reason,
                    f"relation/{obj.id}:{diagnostic.key}={diagnostic.value}",
                )
            if classifications:
                pending_areas.add((OsmElementType.RELATION, obj.id), node_count=None)
        elif object_name == "Area":
            osm_type = OsmElementType.WAY if obj.from_way() else OsmElementType.RELATION
            osm_id = obj.orig_id()
            key = (osm_type, osm_id)
            classifications = classify_poi(tags)
            if classifications and pending_areas.should_emit(key):
                geometry_wkt = _create_wkt(wkt_factory, "create_multipolygon", obj)
                if geometry_wkt is not None:
                    emit(osm_type, osm_id, tags, geometry_wkt, "area", classifications)
                    pending_areas.mark_emitted(key)

    for (osm_type, osm_id), node_count in pending_areas.unresolved():
        if osm_type == OsmElementType.RELATION:
            reason = "incomplete_relation_geometry"
        else:
            reason = "missing_area_geometry" if (node_count or 0) < 2 else "invalid_geometry"
        diagnostics.record(reason, f"{osm_type.value}/{osm_id}")

    routable = {WaterwayKind.CANAL, WaterwayKind.RIVER, WaterwayKind.FAIRWAY}
    ways.sort(key=lambda w: (0 if w.kind in routable else 1, w.osm_id))

    fetched_at = datetime.fromtimestamp(pbf_path.stat().st_mtime, tz=UTC).isoformat()
    ordered_candidates = sorted(
        candidates.values(),
        key=lambda candidate: (
            candidate.osm_type.value,
            candidate.osm_id,
            candidate.category.value,
            candidate.kind,
        ),
    )
    candidates.clear()
    poi_ingest_report = diagnostics.build_report()
    if profile_counts is not None:
        profile_counts.update(
            ways=len(ways),
            nodes=len(nodes),
            candidates=len(ordered_candidates),
            pending_areas=len(pending_areas),
            skipped_reasons=dict(poi_ingest_report.skipped_counts),
        )
    pending_areas.release()
    del diagnostics
    return WaterwayFeatures(
        ways=ways,
        nodes=nodes,
        source="geofabrik",
        fetched_at=fetched_at,
        bbox=None,
        poi_candidates=ordered_candidates,
        poi_ingest_report=poi_ingest_report,
    )


def prepare_great_britain_pbf(pbf_path: Path, profiler: BuildProfiler) -> Path:
    """Create the immutable filtered PBF consumed by all Great Britain passes."""
    pbf_path = Path(pbf_path)
    base = pbf_path.name.split(".")[0]
    filtered = pbf_path.parent / (base + "_waterways.osm.pbf")
    counts = {}
    with profiler.phase("tags_filter", counts=lambda: counts):
        if profiler.enabled:
            counts["input_bytes"] = pbf_path.stat().st_size
        run_tags_filter(pbf_path, filtered)
        if profiler.enabled:
            counts["output_bytes"] = filtered.stat().st_size
    return filtered


def read_great_britain_waterways(filtered_pbf: Path, profiler: BuildProfiler) -> WaterwayFeatures:
    """Read, prune, and navigability-filter Great Britain graph inputs."""
    counts = {}
    with profiler.phase("waterway_processing", counts=lambda: counts):
        features = read_waterway_features(filtered_pbf, profile_counts=counts)
        counts.update(input_nodes=len(features.nodes), input_ways=len(features.ways))
        features = prune_non_navigable_infra(features)
        features = filter_navigable_ways(features)
        counts.update(output_nodes=len(features.nodes), output_ways=len(features.ways))
    return features


def read_great_britain(
    pbf_path: Path | None = None, *, profiler: BuildProfiler | None = None
) -> WaterwayFeatures:
    """Tags-filter then read, then prune infra nodes on non-navigable ways
    and filter navigable ways. pbf_path defaults to POUND_PBF_PATH env or
    data/great-britain.osm.pbf. Filtered output lands beside it as
    great-britain_waterways.osm.pbf (gitignored).

    Ordering: prune BEFORE filter. prune needs boat=no ways present to decide
    "all incidents non-navigable"; see the spec's load-bearing ordering note.
    """
    if pbf_path is None:
        pbf_path = Path(os.environ.get("POUND_PBF_PATH", "data/great-britain.osm.pbf"))
    pbf_path = Path(pbf_path)
    profiler = profiler or BuildProfiler()
    base = pbf_path.name.split(".")[0]
    filtered = pbf_path.parent / (base + "_waterways.osm.pbf")
    filter_counts = {}
    with profiler.phase("tags_filter", counts=lambda: filter_counts):
        if profiler.enabled:
            filter_counts["input_bytes"] = pbf_path.stat().st_size
        run_tags_filter(pbf_path, filtered)
        if profiler.enabled:
            filter_counts["output_bytes"] = filtered.stat().st_size

    processing_counts = {}
    with profiler.phase("pbf_processing", counts=lambda: processing_counts):
        if profiler.enabled:
            features = read_pbf(filtered, profile_counts=processing_counts)
        else:
            features = read_pbf(filtered)
    # prune BEFORE filter: see spec's load-bearing ordering note.
    prune_counts = {"input_nodes": len(features.nodes), "input_ways": len(features.ways)}
    with profiler.phase("prune", counts=lambda: prune_counts):
        features = prune_non_navigable_infra(features)
        prune_counts.update(output_nodes=len(features.nodes), output_ways=len(features.ways))

    navigable_counts = {"input_nodes": len(features.nodes), "input_ways": len(features.ways)}
    with profiler.phase("navigable_filter", counts=lambda: navigable_counts):
        features = filter_navigable_ways(features)
        navigable_counts.update(output_nodes=len(features.nodes), output_ways=len(features.ways))
    return features
