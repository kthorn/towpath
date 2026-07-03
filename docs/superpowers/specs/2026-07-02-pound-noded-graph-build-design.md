# Pound — Noded Graph Build (Connectivity Rewrite) Design

> **Status:** Refined (single user brainstorm session, 2026-07-02). Supersedes
> the connectivity sections of the Scope D PR1 design
> (`2026-06-25-pound-bulk-ingest-and-routing-design.md` §connectivity) and
> retires its Phase 1 / Phase 3 machinery. Builds on the boatability-filter
> work (PR #3, archived spec `docs/completed/2026-06-28-boatability-filter-and-phase3-perf-design.md`) which stays valid.
> Pending `writing-plans`.

## 1. Context & motivation

A post-PR-#3 end-to-end verification build — the first e2e test of
`pound-ingest build england` since #3 merged — surfaced a **fundamental
connectivity defect**, not a tuning problem:

- `pound-ingest build england --tolerance-m 1` → **3,762 components**;
  `--tolerance-m 10` → **3,623 components**. The largest piece is 4,237 nodes
  (16% of the graph); **2,242 components are isolated single edges** (size 2).
- The live-testing doc (`docs/testing/2026-06-26-scope-d-pr1-live-testing.md`)
  had read "component_count=thousands" as "needs curation." The verification
  build proved that diagnosis wrong.

A second defect surfaced during the same verification: at `--tolerance-m 10`
the build **crashed** with `KeyError` in `_contract` (Phase 3 snap-build loop
mutating the graph while iterating a pre-computed candidate list). This was
fixed in `cb6918f` (regression test `test_overlapping_snap_candidates_share_node`),
but the fix only made the crash recoverable; it did not address the
fragmentation, because the fragmentation is not a tolerance-snap issue at all.

### Root cause (measured against the Geofabrik England extract)

The current `build_graph` emits **only each way's first and last coordinate**
as graph nodes; intermediate OSM nodes are discarded. Each routable way becomes
one edge end-to-end. This throws away the junctions that connect the network:

| Signal | Measured |
|---|---:|
| Routable ways (canal/river/fairway/lock) | 23,173 |
| Ways that share an OSM node id at an endpoint with another way | 20,789 (90%) |
| **Node ids shared at an endpoint by some ways but INTERNAL to others** | **3,261 (15%)** |
| Phase 1 (node-ref authority) contraction groups produced on bulk data | **0** (every OSM id → one coord; no groups to contract) |
| Ways appearing as the internal side of a mixed junction | 2,015 |

15% of all shared junctions are unreachable by the endpoint-only build: a way
whose both endpoints land at *internal* positions of their neighbors becomes a
detached single edge. That is the origin of the 2,242 size-2 components.

### The fix, validated by reconstruction

Rebuilding the graph the **noded** way (every OSM node id → graph node;
consecutive ids → edges) collapses the network honestly:

| | Endpoint-only build (tol=10) | Noded reconstruction |
|---|---:|---:|
| Components | 3,623 | **1,669** |
| Largest component | 4,237 nodes (16%) | **240,902 nodes (34.5%)** |
| Components > 200 nodes | 7 | **316** |
| Ways touching the largest component | — | 10,708 (46%) |
| Largest contiguous node-chain (pseudo-diameter) | — | 17,227 hops |

The noded graph's giant component spans N54.19°–S51.08°, W3.19°–E0.99°
(345 km × 289 km) with 4,395 canal ways — the real Midlands canal network
joined up. The remaining 1,669 fragments are genuine geographic isolation
(Devon/Cornwall, Exe, Severn-tributary sub-networks), not build bugs.

## 2. Goal & non-goals

**Goal:** rewrite `pound/graph/build.py::build_graph` as a *noded* build:
every OSM node id along a routable way becomes a graph node keyed by a
synthetic internal uid; consecutive ids become edges with per-segment length
and inherited way-level attributes. Join at emission by shared OSM id (and by
exact rounded coordinate, for id-less dev data). Remove the Phase 1, Phase 3,
tolerance-snap, and `overrides.json` curation machinery that operated on the
broken endpoint-only model.

**Non-goals (explicitly deferred):**

- **Curation / genuine-gap bridging.** No `overrides.json`, no `join`/`split`,
  no tolerance-snap curation queue. Components and genuine gaps are reported as
  advisory. The curation question reopens only when PR2's `pound-plan` surfaces
  a real route that fails across a genuine gap — at which point a thin curation
  seam can be added against a real signal, not a queue of artifacts.
- **`pound-ingest oxford` Overpass dev path as load-bearing.** It stays as
  network-gated scaffolding for fine-grained pulls but stops being a
  contract-shaping concern (PR2 does not consume it; no production caller).
- **Amenities, geocoder, rings, full-GB beyond England.** Unchanged from the
  Scope D spec's deferred list.

## 3. Design

### 3.1 Node-key contract: internal unique ids (decision D)

Graph nodes are keyed by a **synthetic internal uid**, not by coordinate
tuple and not by raw OSM id.

- A monotonic counter (e.g. `itertools.count()`) assigns each emitted graph
  node a stable internal id, regardless of provenance — one OSM id, several
  OSM ids aliasing at one coordinate, an exact-coord join of two id-less ways,
  or (future) a synthetic curator node with no OSM id at all.
- `lat`, `lon`, and `osm_node_ids: set[str]` become **node attributes**, not
  the key.
- **This breaks the Scope C `(lat, lon)`-tuple key contract.** Consumers that
  hardcoded coordinate keys must migrate to attribute-based access
  (`g.nodes[uid]["lat"]`). Scope is bounded (see §5): no production caller
  assumes coordinate keys today; only the Oxford fixture + 3 test files do.
  PR2 (`ResolvedConstraints`, `resolve_place`) is not yet implemented and will
  adopt internal-id node references from the start.

**Why not coordinate keys (B):** two distinct OSM ids can round to the same
`(lat, lon)`; keying by coordinate silently aliases them and loses which OSM
node a graph node represents. Keying by raw OSM id couples the graph to a
foreign key space and cannot represent synthetic curator nodes. Internal ids
are source-agnostic and survive both aliasing and future synthetic nodes.

### 3.2 Emission model: noded, segment-level edges (decision A)

For each routable way with `node_ids` of length N and a matching geometry of N
coordinate points:

1. For each OSM node id in `node_ids`, resolve-or-create an internal uid:
   - Maintain an `osm_id → uid` index. If the id is already in the index
     (shared with another way, or shared internally — it doesn't matter),
     reuse its uid. Else mint a new uid and record `lat`/`lon`/`osm_node_ids`.
   - This makes shared junctions (endpoint or internal) collapse to one graph
     node **for free**, at emission time — no Phase 1 contraction step.
2. For each consecutive pair `i, i+1` of node ids, emit an edge `uid_i → uid_{i+1}`:
   - `length_m` = haversine of that segment's two coords (per-segment, not
     whole-way). Routing cost is now honest.
   - Inherit way-level attrs onto the edge: `osm_way_id`, `name`, `kind`,
     `dimensions`, `has_tunnel`, `has_movable_bridge`, `locks=0` (filled
     later by `attach_locks`), `geometry` = the segment's two coords.
3. Skip closed rings (first coord == last coord, for a ring node-id sequence
   that returns to its start): area polygons (lock-chamber outlines, basins,
   wetlands) are never routable. Unchanged from current behavior.

**Ways with `node_ids == []`** (the Overpass `out geom` dev path): emit each
rounded coordinate as an internal node keyed through a `coord → uid` index;
consecutive coords become edges. Exact-coordinate equality between two id-less
ways collapses to one uid for free (Phase 2 preserved, in coord space). This
path is defensive scaffolding, not load-bearing (§2).

### 3.3 Edge collision: merge attrs (decision A.iii)

When emitting segment A→B and another way already produced edge A→B (the same
two uids) — the ~16 contiguous-overlap / 2 fully-coincident pairs measured in
the England extract — **merge attributes** rather than silently overwriting or
dropping the duplicate:

- `kind`: prefer the more-specific of the two. Measured coincident pairs on
  the England extract were exactly `lock`+`canal` (a lock way duplicated with a
  canal way) and `river`+`canal` (a navigation dual-classified). Specificity:
  `LOCK > CANAL` and `LOCK > RIVER` (a lock IS the canal/river segment there
  and carries `lock_name`/`lock_ref`). For the unresolved `river` vs `canal`
  case (the Calder-and-Hebble dual-classification), prefer `CANAL` (the routing
  intent of this project is canal-boat navigation over inland waterways; a
  `canal` tag is the stronger navigability signal). `FAIRWAY` did not appear in
  any measured collision; if it ever does, treat it as less specific than `LOCK`
  and otherwise keep the existing edge's kind (no speculative ordering beyond
  what the data showed).
- `dimensions`: union-tighten — for each of `max_beam_m`/`max_length_m`/
  `max_draft_m`/`max_height_m`, keep the **min** non-`None` value (the tighter
  constraint is the real one; a wider listed value is stale/optimistic).
- `name`: keep the first non-`None`.
- `has_tunnel` / `has_movable_bridge`: logical OR across the two ways.
- `osm_way_id`: this is single-valued on the edge today; on collision, keep
  the existing one (the edge already represents that way; the second way's
  `osm_way_id` is recoverable via the OSM id sets on the endpoint uids if ever
  needed for traceability). Documented as a known minor info loss.
- Non-overlapping attrs (e.g. a lock's `lock_name`) that exist only on one
  side: keep as-is from whichever side carries them. (`lock_name` is not an
  edge attribute today; if `attach_locks` later sets it, OR-merge applies.)

`nx.Graph` (not `MultiGraph`) remains correct: coincident edges collapse to
one edge, so there is no parallel-edge case.

### 3.4 What gets removed

| Removed | Why |
|---|---|
| Phase 1 node-ref authority (`id2keys`, `_contract` for snap_groups) | Produces 0 groups on bulk data; noding makes shared ids real nodes for free. |
| Phase 3 tolerance-snap candidate pass + `_contract` snap loop | The curation queue was a symptom of dropped junctions; deferred per §2. |
| `load_overrides`, `overrides.json` join/split, `_key_for_osm_id` | No curation in this scope. `pound/data/overrides.json` (fixture-pendant entry) becomes empty or is deleted. |
| `build_graph` kwargs `tolerance_m`, `overrides` | No consumers remain. |
| Graph attrs `tolerance_snaps_used`, `tolerance_snaps_unresolved`, `overrides_applied` | Replaced by advisory component reporting (§3.5). |
| `--tolerance-m`, `--max-unresolved-snaps`, `--overrides` CLI flags | Removed from `pound-ingest build`; gate reframed (§3.6). |

### 3.5 What stays / what's added

- `_node_key(lat, lon)` rounding helper: **stays**, used only on the id-less
  dev path (§3.2) and by `graph/gazetteer.py`'s separate coordinate-keyed
  place dict (unaffected — it keys a *dict*, not the graph).
- `_haversine_m`: stays, now called per-segment.
- `attach_locks`, `attach_node_names`, `build_gazetteer`, `validate_graph`,
  `save_artifact`/`load_artifact`: **unchanged in signature**; they are
  key-agnostic (read `osm_way_id` on edges; read `lat`/`lon` node attrs; key a
  separate gazetteer dict). They keep working against internal-uid keys.
- `validate_graph` report: `component_count`/`component_sizes` stay (advisory,
  §3.6). `tolerance_snaps_*`/`overrides_applied` keys are **removed**.
- New graph attribute: `g.graph["node_count_osm"]` / `["edge_count_segments"]`
  for sanity reporting (optional, if useful for the build report).

### 3.6 Hard-fail gate, reframed (decision A)

`pound-ingest build` keeps a hard-fail gate, narrowed to **real defects**:

- `derelict_edges > 0` → FAIL (a derelict way leaked through the filter —
  filter is broken).
- `self_loops > 0` → FAIL (a closed-ring way became a self-loop — ring-skip
  regressed).
- ~~`tolerance_snaps_unresolved > --max-unresolved-snaps`~~ → **removed**.

**Removed:** `--max-unresolved-snaps`, `--overrides`, `--tolerance-m` CLI
flags. `validate_graph`'s `component_count`/`component_sizes`/`edges_missing_dims`/
`ambiguous_place_names` are **advisory** (reported, never gate). The report
stays the authority for understanding fragmentation; the gate catches only
constructive bugs.

## 4. Oxford fixture migration (decision A)

The Oxford fixture migrates from hybrid (`node_ids=None` on most ways, real
`nodes` only on ways 1003/1007) to **full `node_ids` everywhere**, mirroring
the bulk Geofabrik shape (which is the shape that matters; §2).

- Every way gains a `nodes` array matching its `geometry` length. Coord-shaped
  node ids are minted deliberately so the intended topology is preserved:
  - Chain 1001 (3 geom pts) → 3 node ids → **2 edges** under noding.
  - 1002, 1003 (2 pts each) → 1 edge each.
  - **The pendant joins the chain for free**: give way 1007's near-end the
    *same* OSM id as way 1003's near-end. No override, no tolerance-snap —
    the junction is real. This deletes the
    `pound/data/overrides.json` `"join": [["3002","7001"]]` entry (the only
    entry; file becomes empty or is removed).
  - Way 1004 (disused) and 1005 (derelict_canal) stay filtered out as before.
  - Duke's Cut 1006 stays isolated (genuine geographic island in the fixture).
- Re-derived assertions (the noded chain has more edges than the endpoint
  model): `test_build_main_chain...edge counts` and
  `test_build_main_chain_and_pendant_...` re-derive against the new fixture in
  the implementation plan. `tolerance_snaps_*` assertions across the bulk
  test-file are deleted; genuine-gap advisory-component assertions replace
  them where they tested properties that still hold.

## 5. Downstream impact & migration surface

Bounded — confirmed by grep. **No production code assumes `(lat, lon)` keys:**

- `attach_locks` — reads `osm_way_id` on edges, sets attrs; key-agnostic.
- `attach_node_names` — reads `lat`/`lon` node attrs and a coord-keyed *place
  dict* (not the graph); key-agnostic for the graph itself.
- `build_gazetteer` — returns a *separate* `dict[name, coord]`; not the graph.
- `validate_graph`, `save_artifact`/`load_artifact` — key-agnostic.

**Migrations required:**

| Surface | Change |
|---|---|
| Oxford fixture (`tests/fixtures/oxford_overpass_sample.json`) | Full `node_ids`; pendant shares 1003's near-end id (§4). |
| `tests/graph/test_build_bulk.py` (43 coord-key assertions) | Rewrite to attribute-based assertions (`g.nodes[uid]["lat"]`); re-derive edge counts; delete tolerance-snap/override tests. |
| `tests/graph/test_build.py` | Re-derive edge/node counts for noded chain. |
| `tests/graph/test_gazetteer.py`, `tests/route/test_snap.py` | Attribute-based; snap_place is PR2's to delete, untouched here but its key assumptions move to attributes. |
| `tests/validate/test_connectivity.py` | One `g.add_node((51.7,-1.2), …)` → internal-uid node; delete `tolerance_snaps_*` assertions; keep component/advisory assertions. |
| `tests/graph/test_locks.py` (1 coord ref), `tests/ingest/test_overpass.py` (1) | Minor; attribute-based. |
| `pound/ingest/cli.py` | Drop `--tolerance-m`/`--max-unresolved-snaps`/`--overrides`; drop the snap gate condition; keep derelict/self_loops gate. |
| `pound/data/overrides.json`, `pound/graph/build.py::load_overrides` | Delete (file) and remove (function). |

**Unchanged & still valid:** the boatability filter, `prune_non_navigable_infra`,
the grid-bucket perf index (now applied per-segment if at all — see OQ-1), the
`docs/completed/…` boatability spec.

## 6. Acceptance criteria

The rewrite is done when **all** hold:

1. `pound-ingest build england --out /tmp/england.pkl` exits 0, writes an
   artifact, in ≤ ~2 min (perf preserved), with:
   - `derelict_edges == 0`, `self_loops == 0` (gate green).
   - `component_count` ≤ ~1,669 ± noise; largest component ≥ ~240k nodes
     (the Midlands network joined up — matches the reconstruction measurement
     within tolerance).
2. The Oxford fixture builds under the noded model with the re-derived
   (higher) edge counts; pendant joins 1003 without `overrides.json`.
3. Full suite green: `pytest` (≥ the pre-rewrite count, minus deleted
   tolerance-snap tests, plus noded regression tests), `ruff check .` clean.
4. No production reference to `(lat, lon)` graph keys remains (grep-verified):
   only attribute access (`g.nodes[uid]["lat"]`) and the separate
   coordinate-keyed gazetteer *dict*.
5. A new regression test asserts the noded build joins an
   internal-junction way (a way sharing an OSM id only at an internal
   position of another way) — the exact defect this rewrite fixes.

## Open questions (resolved as below)

- **OQ-1 — Does the grid-bucket spatial index survive?** It was a Phase-3
  tool (finding dangling-tip snap candidates). With Phase 3 removed, it has no
  consumer in this scope. **Decision:** remove it from `build_graph` now
  (YAGNI — no consumer); the perf it delivered was for the deleted snap pass.
  If a future curation seam needs nearest-node search, reintroduce it there
  with a real consumer. The build is already ~2 min without it.
- **OQ-2 — `osm_way_id` on merged edges (§3.3).** Keeping the first way's id
  on collision is a minor info loss for traceability. **Decision:** accept it
  now; the second way's `osm_way_id` is recoverable via endpoint `osm_node_ids`
  sets if a future debugging need arises. Do not add a multi-id edge field
  speculatively (YAGNI).
- **OQ-3 — `node_ids == []` dev path fates.** Kept as defensive scaffolding
  (§3.2) but not load-bearing. **Decision:** keep the coord-keyed fallback
  branch; it costs little and keeps `pound-ingest oxford` from crashing on
  id-less Overpass data. But no test is required to exercise it as a contract
  path — it's scaffolding, and PR2 does not consume `pound-ingest oxford`.
