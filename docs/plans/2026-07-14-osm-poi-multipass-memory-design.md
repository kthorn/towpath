# OSM POI Multi-Pass Memory Design

> **Status:** approved in session; implementation pending
> **Builds on:** `docs/completed/2026-07-12-osm-poi-ingest-design.md` and the Stage 1
> memory-cleanup commits on `plan/osm-poi-ingest`

## 1. Goal and measured blocker

Make the all-England OSM POI artifact build complete on the current 7.50 GiB developer host with
peak RSS at or below both 6 GiB and 70% of physical RAM (5.25 GiB on this host), while preserving
the existing graph, POI, diagnostic, ordering, attachment, metadata, and artifact contracts.

Stage 1 removed avoidable copies and shortened Python lifetimes, but the measured England build
still peaked at 6,919,480 KiB (6.60 GiB) and took 12:40.62. The build completed and strictly
reloaded, with 695,932 graph nodes, 695,510 edges, 525,211 accepted POIs, and zero hard validation
failures. The dominant boundaries were:

- PBF processing: 3,042,282 retained candidates, 118,907 unresolved areas, and 6.06 GiB RSS;
- lock attachment: 6.13 GiB cumulative RSS before POI attachment;
- POI attachment: 525,211 accepted POIs and the final 6.60 GiB peak.

The remaining blocker is architectural: a single area-enabled pass retains millions of candidates
until the graph is ready, then constructs the attachment index and accepted POIs in the same
process lifetime. More local collection tuning cannot responsibly promise the required reduction.

## 2. Decision

Use three sequential passes over one immutable tags-filtered PBF:

1. read waterways and infrastructure only, then build and annotate the graph;
2. stream node and path-derived POIs without area assembly and attach them immediately;
3. stream area way/relation POIs with area assembly and attach them immediately.

The graph and one reusable navigable-edge attachment index survive the POI passes. Only accepted
POIs, deterministic identity winners, bounded diagnostics, and scalar summaries survive each
candidate callback. No complete `PoiCandidate` collection is constructed.

This approach is preferred over a disk-backed candidate spool because it directly removes the
measured lifetime without introducing a new storage format, cleanup protocol, or cache invalidation
contract. Separate subprocesses are also deferred: they release allocators more aggressively but
would require transferring or rebuilding the large graph and attachment index. If this design still
misses the gate, benchmark pyosmium's disk-backed node-location storage before considering a custom
spill database or subprocess architecture.

## 3. Components and ownership

The Overpass path and its pure APIs remain unchanged. Bulk ingestion gains internal components with
explicit ownership:

- `read_waterway_features()` reads only waterway ways and infrastructure/place nodes needed for
  graph construction. It does not classify or retain POIs.
- `PoiAttachmentIndex` owns the sorted canonical edge keys and BNG STRtree geometry used by both
  POI passes. It is built once after locks and annotations are complete.
- `stream_linear_pois()` reads nodes and eligible path ways without `.with_areas()`. It classifies,
  normalizes, attaches, and discards one source feature at a time.
- `stream_area_pois()` uses an area-enabled processor for POI ways/relations. Completed areas are
  attached on callback; unresolved sources produce the existing diagnostic reasons.
- `PoiBuildAccumulator` owns accepted POIs, identity winners, exact duplicate/rejection counts, and
  bounded examples. It never owns the source waterway IR or an unbounded candidate list.

Pass-local processors, native location indexes, pending-area state, source tags, WKT strings, and
temporary Shapely geometries are released at the end of their pass. The final artifact necessarily
retains accepted `PointOfInterest` models, but rejected candidates and their source geometry do not
survive their callback.

## 4. Streaming attachment and parity

Both POI passes call one primitive that accepts a single `PoiCandidate`, repairs and validates its
geometry, applies the category corridor, queries `PoiAttachmentIndex`, and returns either an
attached `PointOfInterest` or a structured rejection. It preserves the current BNG distance,
canonical-edge tie break, nearest-node tie break, representative-point behavior, projected
coordinate, and source tags.

Identity remains `(osm_type, osm_id, kind)`. The accumulator stores one accepted winner per
identity. On collision only, it compares the incumbent and challenger by the existing legacy
candidate JSON ordering; the earlier serialized candidate wins. Duplicate counts include every
extra occurrence even when the incumbent remains. After all passes, accepted winners are sorted by
`(osm_type.value, osm_id, kind)` before artifact preparation.

Diagnostics preserve exact counts and the five lexicographically smallest distinct examples per
reason. Pass-local diagnostics merge by summing counts and applying the same bounded-set rule.
Area bookkeeping stores only source identity and optional node count, removes emitted entries
immediately, and retains emitted identities only as long as duplicate area callbacks are possible.

Regional and fixture parity must be exact for graph nodes/attributes, canonical edges/attributes,
ordered full POIs, validation metadata, and POI summary metadata. Only `artifact_revision` and
`built_at` are ignored.

## 5. Failure handling and profiling

The build reports these phases as flushed JSON Lines:

- `tags_filter`
- `waterway_processing`
- `graph_build`
- `graph_annotation`
- `lock_attachment`
- `linear_poi_processing`
- `area_poi_processing`
- `artifact_validation`
- `artifact_serialization`

Phase `ru_maxrss` values are cumulative Python-process high-water snapshots and do not include the
osmium subprocess; `/usr/bin/time -v` is authoritative for the acceptance gate. Phase counts include
scanned source objects, classified candidates, accepted POIs, duplicates, unresolved areas, and
skipped reasons.

Malformed individual OSM geometry remains nonfatal and updates the existing structured diagnostic.
PBF corruption, pyosmium failure, inconsistent edge-index mappings, invalid graph references, and
artifact validation errors emit a failed phase and abort. No partial artifact is treated as valid.
This work does not add a new atomic-write contract unless implementation evidence shows the current
writer already provides an appropriate seam.

## 6. Performance gate

Before the full refactor, benchmark raw non-area and area-enabled scans that do not retain
candidates. Use those measurements to project total scan cost and stop for review if it is likely to
exceed twice the measured Stage 1 England runtime.

Final acceptance requires:

- exact regional artifact parity;
- England peak RSS at or below 5.25 GiB on this host and never above 6 GiB;
- strict artifact reload and zero hard validation failures;
- total England runtime no greater than 25:21, with a target below 19 minutes;
- completed profile records through serialization.

Any regional runtime regression above 10% must be explained before the England run. A memory miss
after this design triggers a measured disk-backed pyosmium location-index evaluation rather than an
unplanned custom spool layer.

## 7. Testing

All implementation follows red-green-refactor. Unit tests pin pass routing, immediate disposal,
edge-index reuse, cross-pass duplicate winners, merged diagnostics, failure records, and absence of
partial artifacts. Bulk fixtures compare the streaming output with the Stage 1 single-pass output
for complete POIs, ordering, summaries, diagnostics, malformed areas, incomplete relations,
repaired polygons, paths, thresholds, and reversed duplicates.

Regional verification uses one immutable filtered Oxford PBF for both revisions so `fetched_at`
remains identical. Both builds run under `/usr/bin/time -v`, and the artifact comparator must exit
zero. The England build runs only after focused bulk tests, the full default suite, Ruff, and
`git diff --check` pass.

## 8. Scope boundaries

This design does not change the artifact schema, Overpass behavior, taxonomy, tag-filter expression,
routing behavior, public pure lock API, category radii, or generated-data policy. It does not add a
candidate database, persistent scan cache, multiprocessing, UI behavior, or remote deployment work.
Temporary PBFs, artifacts, benchmarks, and profiles remain under `/tmp` and are never committed.
