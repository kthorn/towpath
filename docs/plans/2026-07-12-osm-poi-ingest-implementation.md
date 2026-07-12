# OSM POI Ingest and Spatial Lookup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a strictly validated routing artifact containing canal-relevant OSM POIs and add Shapely-backed graph spatial lookup without changing route endpoint semantics.

**Architecture:** Both Overpass and pyosmium emit one source-neutral POI candidate IR through shared pure classifiers. Offline Shapely processing normalizes geometry, filters candidates against indexed navigable edges, and attaches retained POIs to the graph; the artifact stores a graph, normalized POIs, and metadata, while runtime indexes are rebuilt once after loading.

**Tech Stack:** Python 3.12, Pydantic 2, NetworkX 3, Shapely 2, pyproj 3, pyosmium, osmium-tool, pytest, Ruff.

**Design source:** `docs/plans/2026-07-12-osm-poi-ingest-design.md`

**Implementation rules:** Use @superpowers:test-driven-development for every behavior change, @superpowers:systematic-debugging for unexpected failures, and @superpowers:verification-before-completion before claiming completion. Keep network access confined to ingest. Do not edit or commit downloaded PBFs or generated artifacts.

### Task 1: Add Shapely and define the POI contracts

**Files:**
- Modify: `pyproject.toml`
- Modify: `pound/ingest/ir.py`
- Modify: `tests/ingest/test_ir.py`

**Steps:**

1. Add failing model tests for `PoiCategory`, `OsmElementType`, `PoiCandidate`, and
   `PoiIngestReport`, and `PointOfInterest`, including coordinate bounds, nonnegative distances,
   valid attachment tuples, capped deterministic diagnostic examples, and identity
   `(osm_type, osm_id, kind)`.
2. Run: `/home/kurtt/towpath/.venv/bin/pytest tests/ingest/test_ir.py -v`
   Expected: FAIL because the models do not exist.
3. Add `shapely>=2.1,<3` and `pyproj>=3.7,<4` to core dependencies. Add the enums/models from the design, using a
   `WktGeometry` string field on candidate IR so Pydantic data stays serialization-friendly.
4. Give `WaterwayFeatures.poi_candidates` and `poi_ingest_report` default factories temporarily so
   existing reader tests can migrate incrementally; prune/filter model copies must preserve both,
   and strict artifact validation is added later.
5. Run the focused tests and Ruff for the changed files; expect PASS.
6. Commit: `feat(ingest): define OSM POI contracts`

### Task 2: Centralize POI classification and normalized tags

**Files:**
- Create: `pound/ingest/pois.py`
- Create: `tests/ingest/test_pois.py`

**Steps:**

1. Write table-driven failing tests for every allowlisted mapping in design section 3. Include
   precedence cases, `mooring=no`, bus platforms without bus evidence, parking exclusion, unknown
   values, private/no-foot entrances, and selected-tag filtering.
2. Run: `/home/kurtt/towpath/.venv/bin/pytest tests/ingest/test_pois.py -v`
   Expected: FAIL because `classify_poi()` and `normalize_source_tags()` do not exist.
3. Implement pure `classify_poi(tags) -> list[PoiClassification]`, because one source element may
   legitimately provide multiple kinds. Keep ordered rule tables/constants in this module.
4. Implement `normalize_source_tags(tags, classification)` using only the operational keys and the
   classification-driving keys. Add `corridor_m(category)` returning `250.0` or `1000.0`.
5. Return structured skip reasons (`unknown_value`, `excluded_parking`, `insufficient_bus_evidence`,
   `explicitly_unavailable`) for build reporting rather than logging inside pure functions.
6. Run focused tests and Ruff; expect PASS.
7. Commit: `feat(ingest): classify canal-relevant POIs`

### Task 3: Parse Overpass POI nodes, ways, and relations

**Files:**
- Modify: `pound/ingest/overpass.py`
- Modify: `tests/ingest/test_overpass.py`
- Create: `tests/fixtures/poi_overpass_sample.json`

**Steps:**

1. Create a compact fixture with all categories, point nodes, a closed area way, a concave polygon,
   a multipolygon relation with member geometry, duplicates, parking, and an unknown shop value.
2. Write failing query assertions for explicit `nwr` POI clauses and pedestrian path/constraint
   clauses. Do not use an unrestricted `nwr[amenity]` or `nwr[shop]` query.
3. Write failing parse tests asserting exact candidate identities, kinds, geometry sources, WKT
   geometry types, selected tags, relation handling, and deterministic ordering. Add area elements
   with absent and incomplete member geometry and assert they are skipped with the corresponding
   structured reason rather than treated as point POIs. Assert counts and capped source-identity
   examples appear in `WaterwayFeatures.poi_ingest_report`.
4. Run: `/home/kurtt/towpath/.venv/bin/pytest tests/ingest/test_overpass.py -v`
   Expected: FAIL on missing query clauses/candidates.
5. Add query clauses from the allowlist and require `out geom` (or equivalent complete member
   geometry recursion) for POI ways and relations. Factor node/way/relation geometry decoding into
   private helpers; use Shapely only to construct WKT, not to perform corridor filtering in the
   reader.
6. Pass every tagged feature through `classify_poi()`, emit one candidate per classification, and
   sort by `(osm_type, osm_id, category, kind)`. Accumulate reader-stage skips in
   `PoiIngestReport`; do not log-and-discard them.
7. Preserve existing waterway parsing and prune/filter ordering unchanged.
8. Run focused tests and Ruff; expect PASS.
9. Commit: `feat(ingest): parse Overpass POI geometry`

### Task 4: Parse bulk PBF area and point POIs

**Files:**
- Modify: `pound/ingest/osm.py`
- Modify: `tests/ingest/test_osm.py`
- Modify: `tests/fixtures/tiny_bulk.osm`

**Steps:**

1. Extend the XML fixture with every category, a closed area way, a multipolygon relation,
   pedestrian restrictions, parking, and malformed/incomplete examples.
2. Add failing tests that pin explicit `TAGS_FILTER_EXPR` clauses, candidate identities, geometry
   types, relation deduplication, and parity with the Overpass fixture after excluding source-only
   fields.
3. Run the bulk file: `/home/kurtt/towpath/.venv/bin/pytest tests/ingest/test_osm.py -v --run-bulk`
   Expected: FAIL on absent candidates. If pyosmium/osmium-tool are unavailable, document and run
   the reader unit seam with fakes rather than weakening the marker.
4. Extend `TAGS_FILTER_EXPR` with explicit node/way/relation clauses. Ensure referenced geometry
   needed for selected ways/relations is retained by osmium-tool.
5. Use pyosmium area assembly (`FileProcessor.with_areas()` or the installed equivalent), emitting
   each OSM area once. Convert point, way, and assembled area geometry to WKT and use the shared
   classifier/tag normalizer.
6. Keep waterway `node_ids`/geometry alignment and existing prune-before-filter behavior intact.
7. Run bulk tests, then the Overpass/bulk parity assertion and Ruff; expect PASS.
8. Commit: `feat(ingest): import POIs from bulk OSM`

### Task 5: Normalize geometry and attach POIs to waterways

**Files:**
- Create: `pound/graph/pois.py`
- Create: `tests/graph/test_pois.py`

**Steps:**

1. Write failing tests for point and polygon distance, concave polygon representative points,
   `make_valid()` recovery, empty geometry skips, exact 250 m/1,000 m boundaries, deterministic
   edge/node tie-breaking, path-derived closest points, duplicate identities, and input immutability.
   Include an asymmetric known graph edge and assert `(lat, lon)` graph tuples become `(lon, lat)`
   Shapely coordinates before projection and round-trip without an axis swap.
2. Run: `/home/kurtt/towpath/.venv/bin/pytest tests/graph/test_pois.py -v`
   Expected: FAIL because the module does not exist.
3. Implement WGS84 to EPSG:27700 conversion using `pyproj.Transformer.from_crs(...,
   always_xy=True)` with `shapely.transform`. Never approximate metre distances in longitude/latitude
   degrees. Centralize named graph `(lat, lon)` to Shapely `(lon, lat)` helpers and their inverse;
   do not construct Shapely graph geometry directly from stored tuples.
4. Build an STRtree over navigable graph edge `LineString`s and stable edge-key mappings.
5. Implement `attach_pois(graph, candidates) -> PoiBuildResult` returning normalized POIs plus a
   summary. Measure areas using full geometry, use `representative_point()` for displayed location,
   and use nearest points for waterway projection/path-derived access.
6. Enforce category corridors inclusively (`distance <= threshold`), deterministic deduplication,
   `(distance, min_uid, max_uid)` edge selection, and `(distance, uid)` endpoint selection.
7. Run focused tests and Ruff; expect PASS.
8. Commit: `feat(graph): attach nearby POIs to waterways`

### Task 6: Replace tuple artifacts with strict GraphArtifact validation

**Files:**
- Modify: `pound/graph/artifact.py`
- Modify: `tests/graph/test_artifact.py`

**Steps:**

1. Replace legacy-compatibility tests with failing tests for `GraphArtifact`, exact top-level keys,
   required metadata, POI parsing, invalid graph types, duplicate identities, bad attachments,
   over-threshold distances, non-finite coordinates, unexpected fields, and rebuild-oriented errors.
2. Run: `/home/kurtt/towpath/.venv/bin/pytest tests/graph/test_artifact.py -v`
   Expected: FAIL because loading still returns a tuple and accepts legacy blobs.
3. Add frozen `GraphArtifact` and `InvalidArtifactError`. Change `save_artifact(graph, pois, path,
   metadata)` to serialize exactly `graph`, `pois`, `metadata`, generating one artifact revision when
   absent.
4. Make `load_artifact(path) -> GraphArtifact` validate structure and semantic invariants. Do not
   add schema-version metadata or a fallback path.
5. Keep pickle trust explicit in the module docstring: only locally produced artifacts are valid.
6. Run focused tests and Ruff; expect PASS.
7. Commit: `refactor(graph): validate the POI artifact schema`

### Task 7: Wire POI attachment into builds and reporting

**Files:**
- Modify: `pound/ingest/cli.py`
- Modify: `pound/ingest/summarize.py`
- Modify: `pound/validate/connectivity.py`
- Modify: `tests/ingest/test_cli.py`
- Modify: `tests/ingest/test_summarize.py`
- Modify: `tests/ingest/test_pipeline_integration.py`
- Modify: `tests/validate/test_connectivity.py`

**Steps:**

1. Add failing tests for build order, POI summary output, required metadata, strict validation
   failures, and an end-to-end artifact containing attached fixture POIs.
2. Run the four focused test files; expect FAIL on missing POI build wiring.
3. In `_build_from_features()`, build/annotate the graph first, call `attach_pois()`, merge POI
   validation into the build report, and save the new artifact only after all fatal gates pass.
4. Add summary counts by category/kind, rejected-by-corridor, malformed geometry, incomplete
   relation, unknown tag/value, and representative examples capped to a small deterministic count.
5. Remove metadata `version`; retain source/fetch/build timestamps, validation, `poi_summary`, and
   artifact revision.
6. Run focused tests and Ruff; expect PASS.
7. Commit: `feat(ingest): build and report POI artifacts`

### Task 8: Migrate all artifact consumers atomically

**Files:**
- Modify: `pound/route/cli.py`
- Modify: `pound/route/locate_cli.py`
- Modify: `pound/web/app.py`
- Modify: `tests/route/test_cli.py`
- Modify: `tests/route/test_locate_cli.py`
- Modify: `tests/web/conftest.py`
- Modify: `tests/web/test_startup.py`
- Modify: `tests/web/test_static.py`
- Modify: `tests/web/test_candidates_api.py`

**Steps:**

1. Run `rg -n "load_artifact|save_artifact" pound tests` and use the result as a migration checklist.
2. Update tests first to construct complete artifacts and access `.graph`, `.pois`, and `.metadata`;
   run the focused CLI/web tests and confirm they fail against old call sites.
3. Update every production loader/saver. Web startup should wrap `InvalidArtifactError` with the
   artifact path while preserving rebuild guidance.
4. Store the artifact container or its three fields in app state without mutating them.
5. Re-run the `rg` checklist and all focused CLI/web tests; expect PASS and no tuple unpacking.
6. Commit: `refactor: migrate artifact consumers to GraphArtifact`

### Task 9: Add reusable runtime graph spatial indexes

**Files:**
- Create: `pound/graph/spatial.py`
- Create: `tests/graph/test_spatial.py`
- Modify: `pound/route/candidates.py`
- Modify: `pound/route/resolve.py`
- Modify: `tests/route/test_candidates.py`
- Modify: `tests/route/test_resolve_coord.py`

**Steps:**

1. Add failing tests for immutable node/edge index construction, empty graphs, deterministic nearest
   node ties, edge projection, and indexed-versus-exhaustive equality on fixture, high-latitude,
   antimeridian, exact-tie, and seeded random graphs. Add an asymmetric graph-node axis-order test.
   Pin a positive initial radius, expansion through at least two radii, `limit > node_count`,
   pole-crossing and split-antimeridian envelopes, and whole-world termination.
2. Run the focused graph/route tests; expect FAIL because `GraphSpatialIndex` does not exist.
3. Implement `GraphSpatialIndex` with a WGS84 `(lon, lat)` node STRtree, an EPSG:27700 navigable-edge
   STRtree, and stable integer position-to-UID/edge mappings. Never rely on Python object identity for
   geometry mapping.
4. Change `nearest_coord_candidates()` to accept the index. Expand a conservative spherical-radius
   WGS84 envelope, exact-rank returned UIDs with `_haversine_m()`, and stop only when at least `k`
   nodes are present and the kth exact distance is within the searched radius. Double the radius as
   needed; define effective `k = min(limit, node_count)`; cover every longitude at a pole; split
   antimeridian envelopes; and query the whole-world envelope once before terminating. Preserve
   exact `(haversine_distance, uid)` ordering and output distances.
5. Route `resolve_coord()` through the same nearest-node primitive; keep existing tolerance and
   error semantics.
6. Run focused tests and Ruff; expect PASS.
7. Commit: `perf(route): index nearest canal nodes and edges`

### Task 10: Construct indexes once during web startup

**Files:**
- Modify: `pound/web/app.py`
- Modify: `pound/web/api.py`
- Modify: `tests/web/test_startup.py`
- Modify: `tests/web/test_candidates_api.py`
- Modify: `tests/web/test_concurrency.py`

**Steps:**

1. Add failing tests that index construction occurs once per lifespan, candidate requests receive
   the shared index, concurrent requests do not mutate it, and results match existing API fixtures.
2. Run focused web tests with a timeout appropriate to the known baseline stall; expected initial
   FAIL on missing index state. If they hang before assertions, use @superpowers:systematic-debugging.
3. Build `GraphSpatialIndex` after strict artifact load, store it on `app.state`, and pass it through
   the API handler to candidate lookup.
4. Keep all index objects request-read-only and keep `/api/canal-route` behavior unchanged.
5. Run focused web tests and Ruff; expect PASS.
6. Commit: `perf(web): reuse artifact spatial indexes`

### Task 11: Document operation and verify the complete change

**Files:**
- Modify: `README.md` if present, otherwise the existing local operating guide under `docs/`
- Modify: `docs/plans/2026-07-12-osm-poi-ingest-design.md` only for implementation-discovered facts

**Steps:**

1. Document Shapely/pyproj dependencies, osmium-tool requirements, artifact rebuild requirement,
   POI categories/radii, CLI summary fields, and the no-untrusted-pickle constraint.
2. Run focused default tests:
   `/home/kurtt/towpath/.venv/bin/pytest tests/ingest tests/graph tests/route -v`
   Expected: PASS with only configured dependency/network skips.
3. Run focused web tests:
   `/home/kurtt/towpath/.venv/bin/pytest tests/web -v`
   Expected: PASS. Diagnose any reproduced baseline stall before continuing.
4. Run bulk tests in an environment with the bulk extra and osmium-tool:
   `/home/kurtt/towpath/.venv/bin/pytest --run-bulk tests/ingest/test_osm.py tests/graph/test_pois.py -v`
   Expected: PASS.
5. Run: `/home/kurtt/towpath/.venv/bin/ruff check .`
   Expected: PASS.
6. Run the full default suite: `/home/kurtt/towpath/.venv/bin/pytest`
   Expected: PASS.
7. Build an artifact to an untracked temporary path, never over a committed/generated user artifact:
   `pound-ingest build england --out /tmp/pound-england-poi-check.pkl --pbf pound/data/england.osm.pbf`
   Expected: successful validation plus nonzero deterministic category summaries. This is optional
   when bulk prerequisites or source data are unavailable; record the reason and do not claim it ran.
8. Inspect `git diff --check`, `git status --short`, and the complete diff. Confirm no PBF, pickle,
   credentials, or unrelated files are included.
9. Commit documentation: `docs: explain OSM POI artifact builds`

## Execution handoff

Implement in the isolated worktree with @superpowers:executing-plans, using TDD task by task and
review checkpoints after Tasks 4, 6, 8, and 10. Before implementation, send the design and this plan
for the user's external review and incorporate only technically verified feedback using
@superpowers:receiving-code-review.
