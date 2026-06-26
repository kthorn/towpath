# Pound — Bulk Ingest, Production Loading & Minimal Routing (Scope D) Design

> **Status:** Design (pre-implementation). Brainstormed 2026-06-25; pending
> `writing-plans`. Supersedes the Scope C deferral notes (`d4f0233`):
> production artifact loading, real-data ingest, and a playable routing
> surface all land here.

## 1. Context & motivation

Scope C (merged as PR #1, `2504cef`) landed a verified engine: real Dijkstra
over a built NetworkX graph, the lock-aware cost model, build-time
connectivity validation, pickle artifact save/load, place snapping, and greedy
day chunking. **The interactive/playable surface after Scope C is near zero:**

- `plan_route`'s production branch (`plan_route(constraints)` with no test-only
  `_graph`/`_features` kwargs) raises `RuntimeError("artifact loading not
  wired in this scope")` — the final whole-branch review (commit `d4f0233`)
  deliberately deferred artifact loading to "a Scope D concern, designed against
  a real caller, not blind."
- There is no route CLI. Only `pound-ingest oxford` (ingest) and
  `pound-ingest build oxford` (build artifact) exist; nothing *consumes* the
  artifact to emit a route.
- The only working input is the hand-curated Oxford fixture (~4 edges, ~130 m,
  ~7-minute route). Live Overpass fetch failed with HTTP 406 in Scope B and was
  skipped; `pound-ingest build oxford` cannot produce a real region artifact
  today. A 7-minute synthetic route is not "real-world testing."
- Connectivity joins way-ends by **exact coordinate equality** (Scope C OQ-3),
  which works on the hand-curated fixture but "will not on raw/bulk data, which
  needs tolerance-snap — deferred to the bulk-path scope." That scope is now.

**Goal of Scope D:** land full-GB (starting with a Geofabrik **England**
extract) ingest, bulk connectivity, a comprehensive offline place gazetteer,
production artifact loading, and a *minimal* `pound-plan` CLI — so that real,
real-world routes can be produced and eyeballed end to end. **Explicitly
deferred to later scopes:** amenities (§5.4 and §3.2 CRT), mooring-aware day
placement ("end near winding hole"), rings (`end=None` round trips), the
external oracle (§8), the geocoder (network place resolution), full-GB scale
beyond England, and `rtree`/`STRtree` spatial indexing.

The consumer-facing exit criterion is deliberately modest: **the CLI must be
good enough to verify that the engine works on real routing, not good enough
to plan a trip with.** A REST API will eventually supersede it for product use.

## 2. Scope boundary

**In scope (this plan):**

- **Full-GB ingest path** — `osmium tags-filter` (CLI) → filtered PBF →
  `pyosmium` stream → `WaterwayFeatures`. Starting data: a Geofabrik **England**
  extract (manual `curl`/`wget` to a gitignored path; full GB is a later URL
  swap). New module `pound/ingest/osm.py`; `ingest/overpass.py` kept for
  dev/fine-grained pulls.
- **Bulk connectivity snapping** — node-ref equality as primary, coordinate
  tolerance-snap as a fallback that is **reported on, not silent**. Replaces
  Scope C's exact-coordinate equality, which only works on hand-curated
  fixtures. This is a correctness gate: without it, real OSM data fragments and
  routing silently fails.
- **Manual join curation** — a small `pound/data/overrides.json` in the repo
  listing explicit joins/splits by node/way id, applied after node-ref equality
  and before/instead of tolerance-snap for the cases it covers. Suppresses
  false joins at aqueducts and overpasses; connects genuine gaps in OSM. The
  validation report grows a self-renewing curation queue.
- **Comprehensive offline gazetteer** — at build time, extract *every*
  `place=*` node in the England extract (~30k) into `{name → (lat,lon)}`,
  embedded in the artifact on `graph.graph["gazetteer"]`. This is the
  **only resolver that ships**: place resolution stays pure and offline.
- **Place-name retention on graph nodes** — each waterway node that coincides
  with a `place=*` node carries `name` as a node attribute, so legs render
  "Oxford → Banbury" from the graph alone. Pure data-preservation, independent
  of resolution strategy.
- **Contract evolution** — `plan_route` becomes pure-by-construction over
  *resolved* start/end graph nodes; a new `route/resolve.py` owns place
  resolution (offline only in this scope). `CanalConstraints` survives as the
  CLI/UI-level convenience type; a new `ResolvedConstraints` is the pure
  routing input. The Scope A frozen contract (§1) evolves deliberately and is
  documented as doing so.
- **Production artifact loading** — `plan_route`'s production branch loads the
  artifact (graph + embedded gazetteer) on demand; the Scope C `RuntimeError`
  is retired.
- **Minimal `pound-plan` CLI** — `pound-plan <start> <end> [--days N] …`
  resolves → snaps → routes → prints a human-readable `RouteResult`. A test
  harness, not a product surface. No `--json`; no fancy formatting; explicitly
  a future-replaceable layer that a REST API will sit beside or supersede.

**Explicitly deferred (out of scope):** amenities (§5.4 and §3.2 CRT open
data), mooring-aware day placement, rings (still `NotImplementedError`), the
external oracle (§8), the geocoder (network place resolution — explicit
`# future: GeocodeResolver` seam left in `resolve.py`), full-GB scale beyond
the England extract, `rtree`/`shapely`/`STRtree` spatial indexing (linear
nearest-node is ms at England scale), and the `CanalConstraints.allow_derelict`
routing flag (accepted by schema, honored in a future scope — see §7).

**Two-PR seam (decided):** the natural cut is

- **PR 1 — Ingest + bulk graph build + artifact + augmented validation.**
  Delivers `ingest/osm.py`, bulk connectivity (node-ref + tolerance-snap +
  overrides), augmented `validate_graph`, artifact with embedded gazetteer +
  node names, `pound-ingest build england`. Exit: `build england` produces an
  `england.pkl` whose validation report shows a sane connected graph with ~30k
  gazetteer entries and a queue of unresolved tolerance-snaps; real-data
  routing is possible in a REPL. **No `pound-plan` yet.**
- **PR 2 — Production loading + `route/resolve.py` + minimal `pound-plan` CLI.**
  Delivers the contract evolution (`ResolvedConstraints` + pure `plan_route`),
  `OfflineResolver`, the minimal CLI, and retirement of the Scope C
  `_graph`/`_features` test kwargs. Exit: `pound-plan Oxford Banbury --days 3`
  prints a real route over the England artifact, end to end, no Python.

The seam concentrates engineering risk (bulk ingest, connectivity, tolerance
tuning — the messy-real-data work) in PR1, and keeps PR2 mechanical once PR1's
artifact is trusted. PR2's plan can even be revised against what PR1's
validation report reveals about real gazetteer size and snap behavior.

## 3. The ingest pipeline (`osmium tags-filter` → `pyosmium` → `WaterwayFeatures`)

New module `pound/ingest/osm.py` — the bulk reader, alongside `overpass.py`
(kept for dev/fine-grained pulls). Mirrors `overpass.parse`'s contract: it
populates the same `WaterwayFeatures` IR via the same pure `filters` functions.

### Pipeline (offline, called by `pound-ingest build england`)

1. **`osmium tags-filter` (CLI subprocess) → filtered PBF.** Shell out once
   with a fixed OSM-filter expression. Output: `waterways_<region>.osm.pbf`
   written next to the input in the gitignored `pound/data/`. This is the
   §3.1 "filter before anything else" step — keeps the Python path off the
   full ~1.5 GB extract. The full England extract is a **manual prerequisite**
   (curl/wget to a gitignored path; `POUND_PBF_PATH` env var overrides the
   default `pound/data/england.osm.pbf`); the build CLI prints the exact
   download URL and expected size if the file is missing and exits, rather
   than owning a 1.5 GB downloader (fetch/retry/resume belongs to tooling
   outside this scope).

2. **`pyosmium` stream → IR.** Stream-parse the filtered PBF, emit
   `WaterwayWay`/`WaterwayNode` via `filters.classify_way`/`classify_node`/
   `extract_dimensions`. Unlike the Overpass reader, this one **fills
   `node_ids`** (the IR's forward-compat slot), because pyosmium gives way-node
   refs. Output: `source="geofabrik"`, `fetched_at` = PBF mtime, `bbox` =
   extract bbox. The IR `WaterwayFeatures` type is unchanged.

### OQ-D1 — the `osmium tags-filter` expression

Pinned expression (verified against the Oxford fixture: the filtered set
round-trips to the same `WaterwayFeatures` shape as the Overpass reader, any
divergence fails loudly):

```
w/waterway=canal,river,fairway,lock,derelict_canal,lock_gate
w/disused:waterway, abandoned:waterway
w/lock=yes
w/bridge:movable, bridge=movable
w/maxwidth, maxlength, maxdraft, maxheight, width, maxdraught, depth
n/waterway=lock_gate, lock=yes, mooring, leisure=marina
n/place
```

Rationale: navigable waterway ways + derelict/disused markers (so `filters`
can EXCLUDE them by default, design §3.1) + maxdim tags on ways + lock/lock
gate/movable-bridge/mooring nodes + **every `place=*` node** for the
comprehensive gazetteer. `n/place` is load-bearing — without it the
gazetteer is empty and `pound-plan` cannot resolve any name.

### OQ-D2 — connectivity: node-ref primary, coordinate-snap fallback (reported)

With `node_ids` filled, two ways to join way-ends:

- **(a) Node-ref equality** — two ways share an OSM node id. What raw OSM
  routing assumes; the *correct* source of truth. Works when OSM is well-noded
  (the §3.1 caveat warns it isn't always).
- **(b) Coordinate tolerance-snap** — two way-ends within ε metres join
  regardless of node id. Robust to gaps; risks *false joins* at aqueducts and
  crossings where two waterways touch in coordinates but aren't actually
  connected.

**Decision:** node-ref equality primary; any way-end not joined to at least
one neighbor triggers a tolerance-snap candidate; both the node-ref-joined
edges and the tolerance-snapped edges flow into the `validate_graph` report
(Scope C's `validate/connectivity.py`, augmented — see §5). Tolerance-snap is
a **candidate generator, not an authority** (R3): false joins at aqueducts
cannot be self-resolved, so they are surfaced for manual curation rather than
silently shipped.

### Manual join curation: `pound/data/overrides.json`

A small, human-authored, diff-friendly file in the repo:

```jsonc
// shape is illustrative; exact schema pinned in the implementation plan
{
  "join":  [["<node_or_way_id_a>", "<node_or_way_id_b>"], ...],  // connect despite no shared id/coords
  "split": [["<way_id_a>", "<way_id_b>"], ...]                    // suppress a false tolerance-snap
}
```

Applied after node-ref equality, before/instead of tolerance-snap for the
cases it covers. `split` entries suppress a tolerance-snap false positive (the
aqueduct case); `join` entries connect genuine gaps in OSM. The file is
likely empty or near-empty for the first England build — the *mechanism* ships
so curation has somewhere to land. A maintenance object that grows with
coverage (accepted editorial work — the alternative is silent wrong routes,
which is worse in a routing engine).

## 4. The artifact, the comprehensive gazetteer, and the contract evolution

### Artifact grows up

Scope C's `artifact.py` pickled `{graph, metadata}`. Two holes for production:
no gazetteer (place names can't resolve), no `features` (the metadata-only
pickle can't say what's in it). Three things now ride in the artifact:

- **`graph`** — the NetworkX graph, unchanged from Scope C *except* each
  waterway node that coincides with a `place=*` node now carries `name` as a
  node attribute (`g.nodes[key]["name"] = "Oxford"`). Honors "keep place names
  on nodes." Pure data-preservation; legs render "Oxford → …" from the graph
  alone.
- **`gazetteer`** — `{place_name: node_key}`, built at build time from
  **every** `place=*` node in the England extract (~30k entries), not just ones
  near waterways. Embedded on `graph.graph["gazetteer"]` (one file, no drift,
  rides inside the pickle via NetworkX's graph-level attrs).
- **`metadata`** — `{source, fetched_at, built_at, version, validation}` as
  before; `validation` carries the augmented `validate_graph` report (§5).

One file, one load. `load_artifact(path) -> (graph, metadata)`; the gazetteer
is on `graph.graph["gazetteer"]`. `WaterwayFeatures` is **not** persisted — it
served its purpose at build time (graph + gazetteer derive from it), and
re-pickling it would carry tens of MB to recover data now in the graph. This
is the "what do we throw away" answer: we throw away `WaterwayFeatures`
itself, but only *after*Breadcrumb the gazetteer and node names into the
artifact.

### Contract evolution — `plan_route` becomes pure by construction

This is the Scope A contract change accepted deliberately. Three types:

- **`CanalConstraints`** (exists, frozen in §6) — **stays as the CLI/UI-level
  convenience type** still carrying `start: str, end: str | None, days,
  hours_per_day, boat_*`. The Agent Core / future UI's surface.
- **NEW `ResolvedConstraints`** (in `pound/schemas.py` — the contract home)
  — the pure-routing input: `start_node: tuple[float,float]`,
  `end_node: tuple[float,float]`, `days: int`, `hours_per_day: float`,
  `boat_*: float | None`. **No `start: str`.** Carrying resolved graph node
  keys (coordinate tuples) means `plan_route` literally cannot need a name
  lookup.
- **NEW `route/resolve.py`** — owns place → node resolution. Public function
  `resolve_place(name: str, graph) -> node_key`. Ships **`OfflineResolver`
  only** in this scope: dict-lookups the embedded `graph.graph["gazetteer"]`,
  then nearest-graph-node-within-tolerance if the place coordinate isn't
  already a node key. **No network, no `Geocoder` protocol** — an explicit
  `# future: GeocodeResolver (network)` seam is left in the docstring so the
  deferred geocoder has a clear landing spot.

- **`plan_route(constraints: ResolvedConstraints, *, graph) -> RouteResult`**
  — now takes resolved nodes + the loaded graph. Routing runs Dijkstra over the
  graph; leg names come from the `name` node attribute. **Zero network, zero
  LLM, hermetic by construction.** The Scope C `_graph`/`_features` test kwargs
  go away — tests inject the loaded artifact (or an in-memory graph) instead,
  which is honest. A `plan_route_from_constraints(c: CanalConstraints, *,
  graph, resolver) -> RouteResult` **convenience** is kept as the
  `CanalConstraints → resolve → plan_route` bridge the CLI uses and the Agent
  Core originally targeted, so the contract evolution is additive, not
  breaking, at the convenience layer.

**Contract migration note (for the design doc):** the §1 frozen contract
changes from `plan_route(CanalConstraints) -> RouteResult` to
`plan_route(ResolvedConstraints, *, graph) -> RouteResult`, with
`resolve_place(name, graph) -> node_key` as the bridge. The §10 "no-network
request-time path" rule now specifically describes the *routing computation*,
with resolution as an explicit pre-step — also pure in this scope (offline
gazetteer), but with a documented seam for a future network geocoder.

### Resolved micro-questions (decided during brainstorming)

1. **`ResolvedConstraints` location** → `pound/schemas.py` (contract home).
2. **Node-key shape** → keep `tuple[float, float]` (no new `NodeKey` type; YAGNI).
3. **Gazetteer embedding** → `graph.graph["gazetteer"]` (one pickle, no drift).
4. **Geocoder** → **deferred** to a later scope. `OfflineResolver` only ships.
5. **`plan_route`'s old `CanalConstraints`-accepting signature** → keep a
   `plan_route_from_constraints(c, *, graph, resolver)` convenience so the
   CLI/Agent Core path is unchanged at the convenience layer; the underlying
   `plan_route(resolved)` is pure.

## 5. Connectivity & build validation

The validation surface grows because real data is messy where the curated
fixture wasn't. For real England data the `validate_graph` report becomes
*load-bearing* — it's how you trust a route before shipping it, and how the
manual-curation loop knows what to triage.

### Augmented `validate_graph` report (additive keys, none removed)

All Scope C keys retained (`component_count`, `largest_component_size`,
`component_sizes`, `orphan_lock_ways`, `orphan_lock_nodes`, `derelict_edges`,
`edges_missing_dims`, `zero_length_edges`, `self_loops`, `total_edges`,
`total_nodes`). New keys:

- **`overrides_applied: int`** — joins/splits found in `overrides.json` and
  applied.
- **`tolerance_snaps_used: list`** — way-end joins that fell back to coordinate
  tolerance (no shared node id) and were *not* suppressed by an override. Real
  connections; flagged for human review.
- **`tolerance_snaps_unresolved: list`** — the curation queue: tolerance-snaps
  that built but aren't confirmed by an override and aren't node-ref-joined.
  This is the queue triaged into `overrides.json` next round.
- **`place_nodes_seen: int` / `place_nodes_in_gazetteer: int`** — sanity check
  that the comprehensive gazetteer captured ~all `place=*` nodes (a big
  discrepancy means the tags-filter dropped places or build skipped them).
- **`named_nodes_in_graph: int`** — how many graph nodes carry a `name` (the
  §4 data-preservation freebie); should be a subset of
  `place_nodes_in_gazetteer`.

### OQ-D3 — tolerance value

`tolerance_m` default `10.0` (same order as Scope C's lock-node tolerance,
different purpose). **Exposed as a build CLI flag** (`--tolerance-m`) so a
strict build can dial it to `0` (node-ref only; report everything as a snap
candidate) and a permissive one can dial it up. The **report is the authority,
not the threshold** — the threshold controls noise; the report is the feedback
loop that tells you whether 10 m is too high or too low. Tuned against real
England data by hand (see §7), not pinned once.

### OQ-D4 — derelict handling at bulk scale

**Decision:** drop derelict/disused ways at the filter stage (current Scope C
behavior). The osmium path brings ~thousands of `disused:waterway`/
`abandoned:waterway`/`waterway=derelict_canal` ways; `classify_way` returns
`None` for them and they never reach the graph. `CanalConstraints.allow_derelict`
(a §6 schema field) is **accepted by the schema, honored in a future scope** —
routing over derelict canals is a future feature; carrying a derelict skeleton
now adds artifact weight for a flag nothing reads yet. The `validate_graph`
`derelict_edges: 0` assertion stays as a sanity gate that derelict didn't
leak into the routable graph.

## 6. The minimal `pound-plan` CLI

The playable surface. Thin shell over `load_artifact` + `resolve_place` +
`plan_route`. The CLI is a **test harness, not a product surface** — explicitly
a future-replaceable layer that a REST API will sit beside or supersede.

### Command shape

```
pound-plan <start> <end> [--days N] [--hours-per-day H]
           [--boat-beam M] [--boat-draft M] [--boat-length M] [--boat-height M]
           [--artifact PATH]          # default: pound/artifacts/england.pkl
```

Plain human-readable stdout only: per-leg list + totals + day breakdown +
warnings. **No `--json`** (a future REST API serializes the `RouteResult`
itself; the CLI doesn't prefigure it). **No fancy formatting** — not a table,
not pretty-printed, just "good enough to eyeball that the engine works on real
data," not "good enough to plan a trip with."

### Flow

parse args → `CanalConstraints(start, end, days, …)` →
`load_artifact(artifact_path)` → for start & end: `resolve_place(name, graph)`
(offline gazetteer + nearest-snap) → `ResolvedConstraints(start_node,
end_node, days, …)` → `plan_route(resolved, graph=graph)` → print `RouteResult`.

If a name isn't in the gazetteer → clear error ("'X' not found in gazetteer;
this build covers N places; try a different name or wait for geocoding
support"), not a silent network attempt.

### Not in the CLI (deliberately)

No geocoder, no map rendering, no interactive place picker, no amenity
display, no `--json`. The CLI is "type two place names, get a route to
eyeball." Anything beyond is a later scope.

## 7. Testing strategy, dependencies & risks

### Testing strategy (hermetic by default; real-data tuning by hand)

Three layers, matching the §7.2 philosophy Scope C established:

1. **Unit tests (hermetic, fixture-scale):** the curated Oxford fixture grows
   to carry a third `place=*` node (so snapping has something to chew on) and
   *one* deliberate tolerance-snap case (two way-ends with no shared node id
   but within tolerance) to exercise the bulk connectivity fallback. New tests:
   - `tests/ingest/test_osm.py` — `pyosmium` reader over a tiny synthetic PBF
     (or the Oxford fixture round-tripped through `osmium tags-filter`): same
     `WaterwayFeatures` shape as the Overpass reader.
   - `tests/graph/test_build_bulk.py` — node-ref-joined edges + tolerance-snap
     edges + an `overrides.json` that suppresses a false snap + each reported
     in `validate_graph`.
   - `tests/route/test_resolve.py` — `OfflineResolver` hits gazetteer exactly;
     nearest-node-within-tolerance path; clear error on unknown name.
   - `tests/route/test_plan_route.py` grows — contract migration: pure
     `plan_route(resolved, graph=…)` with `_graph`/`_features` kwargs retired;
     an injected in-memory graph + resolver is the new test seam.
   - `tests/ingest/test_cli.py` — `pound-ingest build england` with
     monkeypatched `osmium` + `pyosmium` reads (no real PBF) writing to
     `tmp_path`.
   - `tests/cli/test_plan_cli.py` (new dir) — `pound-plan Oxford Hayfield
     --days 1` against an artifact the test builds in `tmp_path`, asserts the
     printed `RouteResult`.
2. **Integration gate (fixture-scale, in CI):** `pound-ingest build` over the
   Oxford fixture → artifact → `pound-plan Oxford Hayfield` → asserts the
   §7.2 structural invariants over the *real built artifact path*, not
   injection. Proves the production pipeline works without needing the 1.5 GB
   file.
3. **Real-data tuning (human, not CI):** `pound-ingest build england` produces
   a validation report you read; `tolerance_snaps_unresolved` is the triage
   queue; `overrides.json` grows by hand. No CI asserts against real England —
   §7.2's "trust the graph before trusting routes" is a human gate here, with
   the report as the evidence. **This is the playable testing:** eyeball real
   routes for sanity, tune `--tolerance-m` against the report, curate
   `overrides.json` from the unresolved queue.

### OQ-D5 — PR1's exit gate

**Decision:** **soft** exit gate for the real England build (build runs, report
looks sane, route in a REPL manually to eyeball), with a **fixture-scale
pipeline test** shipped in CI. CI runs the pipeline code (build → artifact →
plan) against the small Oxford fixture as a regression gate; `pyosmium`-needing
tests get a `--run-bulk` skip marker (parallel to Scope B's `--run-network`)
when `pyosmium` is absent (R1). The real England build needs the 1.5 GB file
and isn't gated in CI — its correctness is the fixture test plus human
eyeballing of the report. Matches §7.2's "structural invariants over the
fixture, trust humans on real-data tuning."

### Dependencies (new)

- **`pyosmium`** (Python lib, §10) — PBF streaming. Compiled (libosmium
  binding); wheels exist for CPython 3.12 on common platforms but can fail on
  niche ones (R1). Documented in README; tests needing it carry a
  `--run-bulk` skip marker.
- **`osmium-tool` (system CLI)** — installed as a prereq (apt/brew/conda). The
  README gains a "Prerequisites" section. `pyosmium`'s pip package does **not**
  include the CLI — they're separate. The one non-`uv` install in the project.
- **No new request-time deps.** Geocoder deferred; `rtree`/`shapely`/`STRtree`
  deferred; CRT data deferred. `networkx` + `pydantic` stay.

### Risks (named, not buried)

- **R1 — `pyosmium` install friction.** Compiled component; wheels may fail on
  niche platforms. Mitigation: `--run-bulk` skip marker on needing tests;
  README prerequisites; the fixture-scale integration test does *not* need
  `pyosmium` if the Oxford fixture's PBF (or a synthetic) is checked in.
- **R2 — `osmium tags-filter` expression is wrong.** If the filter drops a tag
  class the routable graph silently loses ways. Mitigation: the Oxford fixture
  round-trips through the same `tags-filter` expression and asserts the same
  `WaterwayFeatures` shape as the Overpass reader; divergence fails loudly.
  Plus `place_nodes_seen` vs `place_nodes_in_gazetteer` catches dropped places.
- **R3 — Tolerance-snap false joins at aqueducts/overpasses.** Tolerance is
  *candidate* not *authority*; `overrides.json` `split` entries suppress them;
  `tolerance_snaps_unresolved` is the review queue. **Residual accepted:** a
  wrong join that looks resolved (within tolerance, no nearby override) ships
  as a real edge and routes boats over an aqueduct. The manual curation loop
  is the only way to catch these; the system surfaces them as well as it can,
  does not pretend to resolve them.
- **R4 — Contract evolution breaks the Agent Core.** `plan_route`'s signature
  changes; anything built against the Scope A stub breaks. Mitigation:
  `plan_route_from_constraints(c, *, graph, resolver)` convenience keeps the
  old call surface; the `CanalConstraints → plan_route` path still works, it
  just now flows `CanalConstraints → resolve → plan_route` internally. Tests
  calling `plan_route(c, _graph=…, _features=…)` break — the test seam moves.
  Accepted (that's the point).
- **R5 — England extract specifics.** Geofabrik's "England" sub-extract
  boundary vs the canal network's geographic reality (canals cross into Wales
  — the Llangollen, the Montgomeryshire). A Birmingham → Llangollen route
  might find the path clipped at the extract edge. Mitigation: documented as
  a known limitation of the *test* extract; full GB swap is the fix. Residual:
  a route that "should" work fails with "no path" near the seam. Accepted for
  the test-extract period.
- **R6 — Performance at England scale.** Pickle load of a ~10⁵-node graph +
  Dijkstra over England (~seconds) + linear nearest-node (~ms) — all bounded;
  not a real risk at this scale. The first build might take *minutes*
  (pyosmium streaming 10⁵ ways). Acceptable for an offline build; the artifact
  is the cache. No action.

## 8. Summary of decisions resolved during brainstorming

| Question | Decision |
|---|---|
| Scope boundary (Q1) | Ingest + production loading + minimal CLI; amenities, mooring-aware day placement, **and rings** all deferred to later scopes |
| Real-data source (Q3) | Manual curl/wget of Geofabrik **England** extract to gitignored path; `POUND_PBF_PATH` overridable; full GB is a later URL swap |
| Bulk ingest mechanism (Q2) | `osmium tags-filter` (CLI) → filtered PBF → `pyosmium` stream; `osmium-tool` a documented system prereq |
| Place resolution (Q4/Q5) | Resolution moves *out* of `plan_route`; `plan_route` is pure-by-construction over `ResolvedConstraints`; `route/resolve.py` ships `OfflineResolver` only; geocoder deferred |
| Gazetteer location (Q4) | Comprehensive offline gazetteer embedded on `graph.graph["gazetteer"]` (one pickle, no drift); built from every `place=*` node in the extract |
| Place names on nodes | Each waterway node coinciding with a `place=*` node carries `name` as a node attribute (data preservation) |
| Connectivity (OQ-D2) | Node-ref equality primary; coordinate tolerance-snap fallback that is **reported on**, not silent |
| Manual curation | `pound/data/overrides.json` (joins/splits by id), applied after node-ref, before/instead of tolerance-snap; validation report grows a self-renewing curation queue |
| Tolerance (OQ-D3) | Default `10.0`, `--tolerance-m` flag-exposed; the report is the authority (tuned by hand against real data, not pinned) |
| Derelict (OQ-D4) | Drop at filter (current behavior); `allow_derelict` accepted by schema, honored in a future scope |
| PR split | PR1 = ingest + bulk build + artifact + validation (REPL-routable); PR2 = resolve + production loading + minimal CLI (the playable thing) |
| PR1 exit gate (OQ-D5) | Soft exit for the real England build (human eyeballing the report) + fixture-scale pipeline test in CI; `--run-bulk` skip marker for `pyosmium`-needing tests |
| CLI scope | Test harness, not product surface. Plain human-readable stdout, no `--json`, no fancy formatting. REST API supersedes later. |
