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

**Alignment guard (required, performed in `read_pbf`):** `pound/ingest/osm.py::read_pbf`
currently builds `node_ids` from **all** refs (`[n.ref for n in w.nodes]`) but
`geometry` only from refs whose location is valid — so the two lists can differ
in length when a referenced node lacks coordinates. The noded emission loop
assumes a 1-to-1 zip. **The prune MUST happen in `read_pbf`, not in the build**:
`WaterwayWay` (`pound/ingest/ir.py:45-54`) carries only `node_ids: list[int]`
and `geometry: list[tuple]` with **no per-ref location-validity flag** — by
the time the build receives the IR the validity info is gone and a build-layer
lockstep filter is unimplementable (an implementer forced into it would fall
back to `zip(node_ids, geometry)` truncation, the exact silent-misalignment
failure this guard exists to prevent). **Move the guard into `read_pbf`:** build
both `node_ids` and `geometry` from the *same* single pass over `w.nodes` that
keeps the `(n.ref, (n.location.lat, n.location.lon))` pair only when
`n.location.valid`, so the two lists are aligned by construction. This means
`WaterwayWay.node_ids` no longer lists every raw ref (only the locatable ones)
— the correct IR invariant for the noded build; the reader is still a faithful
producer of the *locatable* geometry, which is all the build can use anyway.
`read_pbf` is added to the migration table (§5); `overpass.py::parse` (dev
path) builds `node_ids` from `el.get("nodes", [])` and `geometry` from
`out geom` results that include a point for every node, so it is already
aligned and needs no change. The build then assumes `len(node_ids) ==
len(geometry)` and zips freely.

1. For each OSM node id in `node_ids` (after alignment), resolve-or-create an
   internal uid via **two cooperating indexes**:
   - `osm_id(str) → uid` — keyed by the stringified OSM id (`str(ref)`,
     matching the existing `osm_node_ids` set convention at `build.py:122-124`;
     bulk refs arrive as ints, fixture `nodes` as JSON ints, so stringifying
     keeps the index type-consistent — mixing `str`/`int` keys would silently
     break shared-end resolution).
   - `coord(tuple) → uid` — keyed by `_node_key(lat, lon)` (rounded coord).
   - **Resolve-or-create checks BOTH indexes and unifies them:** for a node
     with OSM id `X` at coord `C`, look up `osm_idx[X]` and `coord_idx[C]`.
     - If either returns a uid, **reuse that uid** (and if the two indexes
       disagree, union them — see below).
     - Else mint a new uid, record `lat`/`lon`/`osm_node_ids={str(X)}`, and
       insert BOTH `osm_idx[X] → uid` and `coord_idx[C] → uid`.
   - When two **distinct** OSM ids round to the same coord (e.g. two ways that
     don't share an OSM node id but meet at the same coordinate), the
     `coord_idx` collapses them to one uid — the existing way's uid is reused,
     and the new way's OSM id is **added to that uid's `osm_node_ids` set**.
     This is the **exact-coordinate authority preserved and applied always** —
     not only to id-less ways, but to id-having ways whose distinct ids happen
     to coincide (the common case at a chain junction edited by two mappers,
     and the Oxford fixture's 1001→1002 / 1002→1003 junctions). Without this,
     the fixture chain would split into three components despite coincident
     coords.
   - This makes shared junctions (by OSM id, by coordinate, or both — endpoint
     or internal) collapse to one graph node **for free**, at emission time —
     no Phase 1 contraction step. Phase 2's exact-coord authority is now just
     the coord half of this index; it is not a separate phase.
2. For each consecutive pair `i, i+1` of node ids, emit an edge `uid_i → uid_{i+1}`:
   - **Skip consecutive duplicate ids** (`node_ids[i] == node_ids[i+1]`) and
     consecutive coords that round equal — these would emit a zero-length /
     self-loop edge and could trip the `self_loops > 0` / `zero_length_edges > 0`
     gate. Dedupe-then-iterate; the gate remains honest.
   - `length_m` = haversine of that segment's two coords (per-segment, not
     whole-way). Routing cost is now honest.
   - Inherit way-level attrs onto the edge: `osm_way_id`, `name`, `kind`,
     `dimensions`, `has_tunnel`, `has_movable_bridge`, `locks=0` (filled
     later by `attach_locks`), `geometry` = the segment's two coords.
   - **Noding + `attach_locks` lock-gate snapping:** `attach_locks`'s
     `_edge_point_dist_m` (`graph/locks.py:19-24`) returns the min distance
     to any point in the edge `geometry` list. With per-segment 2-point
     geometry it compares only the two segment endpoints. In practice OSM
     `lock_gate` nodes are themselves OSM nodes, so under noding a gate node
     becomes a graph node that is an endpoint of some segment edge — distance
     0 to that edge, attaches cleanly (strictly better than the old
     whole-way-geometry point-list approach for the common case). The rare
     mid-segment gate (a gate node that is *not* an OSM node) is theoretical
     only and not represented in any fixture. No code change; noted as a
     behavior refinement.
3. Skip closed rings (first coord == last coord, for a ring node-id sequence
   that returns to its start): area polygons (lock-chamber outlines, basins,
   wetlands) are never routable. Unchanged from current behavior.

**Ways with `node_ids == []`** (the Overpass `out geom` dev path): handled by
the same dual-index emission — the `osm_id` index is simply empty for these
ways, so resolve-or-create falls through to the `coord → uid` index and mints
uids by rounded coordinate; consecutive coords become edges. Two id-less ways
meeting at the same coord collapse via `coord_idx` as above. This path is
defensive scaffolding, not load-bearing (§2); the dual-index emission covers it
uniformly with the id-having path.

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
- `length_m`: keep the existing edge's value. Two coincident segments span the
  same two endpoints, so their haversine lengths are equal by construction;
  the only divergence is digitization precision (sub-metre), which is below
  the routing cost model's resolution. Stated explicitly to avoid leaving it
  implicit.
- `osm_way_id`: single-valued on the edge; on collision, **keep the LOCK way's
  id when exactly one colliding party has `kind == LOCK`** (the lock is the
  load-bearing tag for `attach_locks`, which matches lock ways by `osm_way_id`;
  keeping a canal's id on a merged LOCK edge would let the lock way fall into
  `orphan_lock_ways` and leave the merged LOCK edge with `locks=0` — a real
  regression on the measured lock+canal coincident pairs). Otherwise keep the
  existing (first-emitted) edge's `osm_way_id`. The dropped way's id is
  recoverable via the OSM id sets on the endpoint uids for traceability.
- `locks`: **at merge time, if either colliding way has `kind == LOCK`, set the
  merged edge's `locks = max(existing, 1)` immediately** — the lock is intrinsic
  to the segment, and this keeps the count correct even in the (rare) case where
  `attach_locks`'s way-loop later misses the merged edge by id. (Edges start at
  `locks=0`; this only fires on a LOCK-involving collision.)
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
| `pound/route/snap.py` (whole module: `snap_place` + the duplicate `build_gazetteer`) and `tests/route/test_snap.py` | `snap_place` does a coord-tuple graph-node lookup (`if node not in graph.nodes`) that breaks under internal uids and violates criterion 4 (no `(lat,lon)` graph keys). It is PR2's slated deletion (superseded by `route/resolve.py`); deleting it now removes a known-broken coord-key consumer rather than leaving it dangling. The `build_gazetteer` in `route/snap.py` is a stale duplicate of `graph/gazetteer.py`'s; the graph one is the live one. PR2 builds `resolve.py` fresh. |

### 3.5 What stays / what's added

- `_node_key(lat, lon)` rounding helper: **stays**, used only on the id-less
  dev path (§3.2) and by `graph/gazetteer.py`'s separate coordinate-keyed
  place dict (unaffected — it keys a *dict*, not the graph).
- `_haversine_m`: stays, now called per-segment.
- `attach_locks`, `build_gazetteer`, `validate_graph`, `save_artifact`/
  `load_artifact`: **unchanged in signature and behavior**; they are key-agnostic
  (read `osm_way_id` on edges; key a separate gazetteer *dict* rather than the
  graph; count nodes via `graph.nodes(data=True)`). They keep working against
  internal-uid keys. **`attach_locks` has one behavior change** (see below).
- `validate_graph` report: `component_count`/`component_sizes` stay (advisory,
  §3.6). `tolerance_snaps_*`/`overrides_applied` keys are **removed**.
- New graph attribute: `g.graph["node_count_osm"]` / `["edge_count_segments"]`
  for sanity reporting (optional, if useful for the build report).

**Two body rewrites required by the noded model (signature unchanged; behavior
preserved or corrected):**

- **`attach_node_names` (`graph/gazetteer.py`) — body rewrite required.** The
  current body does `if key in place_coords` where `key` is the graph node KEY
  and `place_coords` is keyed by rounded coord tuples (`_node_key(n.lat,`...
  `n.lon)`). Under internal uids the key is never a coord tuple, so the
  membership test is always `False` and **zero names are attached** — silently
  breaking `named_nodes_in_graph`, the gazetteer-coverage report, and
  `test_pipeline_integration`'s `named_nodes_in_graph >= 2` assertion. The
  earlier claim that this function is "key-agnostic (reads `lat`/`lon` node
  attrs)" was wrong — it compares the key, not the attrs. **Rewrite the loop to
  read each node's `lat`/`lon` attrs, round via `_node_key`, and look that up
  in `place_coords`** (`for uid, nd in graph.nodes(data=True):
  coord = _node_key(nd["lat"], nd["lon"]) …`). The separate `place_coords` dict
  stays coord-keyed (it is not the graph). This preserves the function's
  contract and its named-node count.
- **`attach_locks` (`graph/locks.py`) — set `locks=1` on ALL matching edges.**
  The current body does `match = next((d for … if d["osm_way_id"] == way.osm_id), None)`
  and sets `locks=max(match["locks"],1)` on that **first** match only. Under the
  endpoint-only build each way is one edge, so the first match is the only
  match. Under the noded build a lock chamber way with N `node_ids` produces
  **N−1 edges all carrying the same `osm_way_id`**; setting `locks=1` on only
  the first segment under-counts multi-segment chambers (the staircase-fixture
  chambers are 2-pt so tests pass unchanged, but bulk England lock chambers
  with >2 nodes would silently undercount). **Iterate all matching edges**
  (`for _, _, d in g.edges(data=True): if d["osm_way_id"] == way.osm_id:`
  `d["locks"] = max(d["locks"], 1)`) and set per edge; `lock_ways_attached`
  counts the way once (guard with a matched flag), not per segment. This is a
  bugfix the noded build exposes; the staircase fixture asserts `locks` on the
  single chamber edge and stays green.
- **`attach_locks` lock-NODE loop — tie-break by `kind`, not by emission order.**
  The second loop in `attach_locks` (`locks.py:38-50`) attaches `lock=yes`
  *gate nodes* to the nearest edge, using strict `<` for `best_dist`. Under
  noding a gate node that IS an OSM node becomes a graph node incident to
  multiple edges (the lock segment AND any coincident canal spur sharing that
  junction), all at distance 0 — strict `<` ties break by insertion order
  (whichever way emitted first), so on real England data a coincident canal
  spur with a lower `osm_way_id` than the lock way would win the tie and get
  `locks=1` set on the spur. **Break ties by `kind == LOCK` preferred**, then by
  shorter segment, then by first-seen. (The Oxford fixture happens to put the
  lock way 1003 at a lower `osm_way_id` than the coincident canal spur 1007, so
  it currently wins by insertion order — but that's luck, not a guarantee; the
  tie-break makes it deterministic.) `test_non_lock_edges_have_zero_locks`
  (`tests/graph/test_locks.py:45-49`) currently excludes edge 1007 from its
  iteration — widen it to cover all non-LOCK edges so the spur-contention
  regression would be caught.

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

- Every way gains a `nodes` array matching its `geometry` length. Node ids
  are minted deliberately so the intended topology is preserved by the
  dual-index emission (§3.2) — by shared OSM id where a junction should be
  unambiguous, and by coincident coord (distinct ids, same coord) where it
  should exercise the `coord → uid` authority:
  - **Chain junctions join by shared OSM id** (clean and unambiguous): give
    1001's last id == 1002's first id, and 1002's last id == 1003's first id.
    (They also coincide by coord, so this is belt-and-suspenders, but shared
    ids make the join intent explicit rather than relying on coord rounding.)
    1001 (3 geom pts) → 3 node ids → **2 edges** under noding; 1002, 1003
    (2 pts each) → 1 edge each.
  - **The pendant joins the chain for free by shared OSM id**: give way
    1007's near-end the *same* OSM id as way 1003's **far** node (id `3002`,
    at coord `51.754,-1.264` — verified against the existing `overrides.json`
    join entry `[["3002","7001"]]`; 1003's *near* node is `5003` at
    `51.753,-1.263`, which 1007 does not coincide with, so the shared id must
    be 3002). **Set 1007's near coordinate to exactly `51.754,-1.264`** — drop
    the deliberate `51.75401,-1.26399` offset. That offset existed only to
    demonstrate the tolerance-snap that this rewrite removes; under noding it
    would make the shared-id uid's coord order-dependent (if 1007 emits before
    1003, the uid for 3002 would inherit 1007's coord and miss the Hayfield
    place-name match in `attach_node_names`). Exact coord makes name
    attachment deterministic. No override, no tolerance-snap — the junction
    is real. This deletes the `pound/data/overrides.json` `"join"` entry (the
    only entry; file becomes empty or is removed).
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
| Oxford fixture (`tests/fixtures/oxford_overpass_sample.json`) | Full `node_ids`; pendant shares 1003's *far*-end id 3002 (§4). |
| `pound/graph/gazetteer.py::attach_node_names` | **Body rewrite** (signature unchanged): read each node's `lat`/`lon` attrs, round via `_node_key`, look up in `place_coords` — the current key-membership test silently sets zero names under uids (§3.5). |
| `pound/graph/locks.py::attach_locks` | **Body change** (signature unchanged): set `locks=1` on **all** edges matching `osm_way_id`, not just the first — multi-segment chambers undercount otherwise (§3.5). |
| `pound/route/snap.py`, `tests/route/test_snap.py` | **Delete** (whole module + test): `snap_place` does a coord-tuple graph-node lookup that breaks under uids and violates criterion 4; PR2 builds `resolve.py` fresh (§3.4). |
| `pound/ingest/cli.py` | Drop `--tolerance-m`/`--max-unresolved-snaps`/`--overrides`; drop the snap gate condition; keep derelict/self_loops gate. |
| `pound/data/overrides.json`, `pound/graph/build.py::load_overrides` | Delete (file) and remove (function). |
| `pound/ingest/osm.py::read_pbf` | **Alignment-guard move (§3.2):** build `node_ids` and `geometry` from the *same* pass over `w.nodes` that keeps the `(n.ref, (n.location.lat, n.location.lon))` pair only when `n.location.valid`, so the two lists are aligned by construction (currently `node_ids` takes all refs, `geometry` only valid-location refs). `pound/ingest/overpass.py::parse` (dev path) is already aligned and unchanged. |
| `tests/graph/test_build_bulk.py` | ~50 references to `tolerance_m` / `tolerance_snaps_*` / `load_overrides` / `_contract` / grid-bucket machinery to delete, plus a small number of coord-key graph accesses, rewritten to attribute-based assertions (`g.nodes[uid]["lat"]`); re-derive edge counts; delete tolerance-snap/override tests. (The file has ~0 direct `g.nodes[(coord)]`-style accesses; the "43 coord-key assertions" wording in earlier drafts was loose.) |
| `pound/route/plan.py`, `tests/route/test_plan_route.py` | **Migrate, do not delete.** `plan.py:17` imports `build_gazetteer, snap_place` from the deleted `route/snap.py`; `plan.py:47-48` calls `snap_place`; `plan.py:165-170` `_name_for` compares `key == node_key` (coord tuple) and falls back to `f"{node_key[0]},{node_key[1]}"` — both break under internal uids. Re-point the `build_gazetteer` import to `graph/gazetteer.py` (the live one); replace `snap_place` usage with an inline attribute-based resolve (or leave `plan_route`'s production `RuntimeError` path as-is and only fix the test-only `_graph`/`_features` path); rewrite `_name_for` to read `g.nodes[uid]["lat"]`/`["lon"]` — **note `_name_for` has no `graph` parameter today; add one (private fn, signature change is fine) or do the lookup inline in the leg-assembly loop**. **Keep the `_graph`/`_features` test kwargs** — PR2 retires them; do not pre-empt PR2's contract change here. **`build_gazetteer` return-type caveat:** `graph/gazetteer.py::build_gazetteer` returns `dict[str, tuple | list[tuple]]` (ambiguous names → `list`), unlike the deleted`route/snap.py` one which returned `dict[str, tuple]`.`_name_for`'s`key == node_key` comparison always fails for `list`-valued entries → ambiguous-named legs silently fall through to the coord-string fallback. Document as a **known interim regression**; PR2's`OfflineResolver`owns the real ambiguous-name handling (`resolve_place` raises on list-valued entries). `test_plan_route.py`'s call sites migrate to attribute-based node lookup; **`_long_plan` synthetic-scaling tests need re-derivation** (see below). |
| `pound/graph/build.py` module docstring | **Rewrite** (currently lines 1-43 describe the old three-phase / tolerance-snap / coord-key model — actively misleading after the rewrite). |
| `tests/graph/test_build.py` | Re-derive edge/node counts for noded chain. |
| `tests/graph/test_gazetteer.py` | Attribute-based; update `g.nodes[key].get("name")`-style asserts to `g.nodes[uid].get("name")`. |
| `tests/validate/test_connectivity.py` | One `g.add_node((51.7,-1.2), …)` → internal-uid node; **rewrite, don't wholesale delete, `test_report_has_bulk_connectivity_keys` and `test_report_defaults_when_graph_has_no_bulk_attrs`** — they also assert the *surviving* keys (`place_nodes_seen`, `place_nodes_in_gazetteer`, `named_nodes_in_graph`, `ambiguous_place_names`); rewrite them to assert that surviving subset and drop only the removed-snap-key assertions, so coverage for the surviving keys isn't lost; keep the other component/advisory tests (`test_component_count_is_two`, `test_no_derelict_edges`, `test_missing_dims_count`, `test_no_zero_length_or_self_loops`, `test_orphans_carry_through`, `test_totals_present`); **`edges_missing_dims` count changes 4→5** — way 1001 (no dims) yields 2 dimless segment-edges under noding, so the new expected value is 5 (1001×2, 1003, 1006, 1007); **`test_component_count_is_two`'s `largest_component_size == 5` becomes 6** — noding gives the main chain+pendant component 6 nodes (ids `a, b, c` from 1001's 3 pts, `5003`, `3002`, `7002`); Duke's Cut stays the 2nd component so `component_count` stays 2; `test_totals_present` edge/node counts re-derive too (edges 5→6, nodes 7→8). |
| `tests/ingest/test_cli.py` | Remove the 3 `--tolerance-m`/`--max-unresolved-snaps``/`--overrides` invocations and the two `test_build_england_…`gate tests that assert the **removed** unresolved-snap gate (`test_build_england_writes_artifact_and_passes_gate`,`test_build_england_fails_when_unresolved_exceeds_threshold`); the passing-gate test stays, reframed around derelict/self_loops; the threshold-fails test is deleted (no such gate). |
| `tests/ingest/test_pipeline_integration.py` | Remove `--max-unresolved-snaps`/`--overrides` flag args and the `tolerance_snaps_unresolved==[]`/`tolerance_snaps_used`-truthy asserts from the passing test; **delete** `test_build_oxford_gate_fails_when_pendant_left_unresolved` (asserts the removed snap-gate fire — the pendant now joins for free under noding, so there is no gate to fire); the remaining `named_nodes_in_graph>=2` assert depends on the `attach_node_names` rewrite above. |
| `tests/graph/test_locks.py` | **Mostly unchanged** — chambers are 2-pt and route through the §3.2 id-less dev branch (1 edge/chamber); asserts are `osm_way_id`-based, no coord keys. **One change:** widen `test_non_lock_edges_have_zero_locks` to cover edge 1007 too (it currently excludes it), so the §3.5 lock-node tie-break regression (canal spur spuriously getting `locks=1`) would be caught. |
| `tests/ingest/test_overpass.py` | **Unchanged** — exercises `parse()` against fixture elements, no graph-node-by-coord lookup; adding `nodes` arrays to the fixture requires no change here. |
| `tests/graph/test_artifact.py` | **Unchanged** — `build_graph(parse(...))` is called with no kwargs (fine either way); asserts only self-consistent `loaded_g.number_of_edges() == g.number_of_edges()`; its embedded gazetteer dict overwrite `{"Oxford": (51.75, -1.26)}` is keyed by *name* (a coord-valued *dict*, not a graph-node coord key) — unaffected by uid keys. Listed for completeness so the implementer knows it's audited. |

**`_long_plan` test re-derivation (in `tests/route/test_plan_route.py`):** the
`_long_plan` helper (`test_plan_route.py:88`) scales every Oxford edge to
~13 km (~162 min/edge) and its docstring says "3-edge path" (Oxford→Hayfield
= ways 1001→1002→1003, one edge per way under the *endpoint* build). Under
**noding**, way 1001 (3 geometry points) becomes **2** segment edges, so the
Oxford→Hayfield path becomes **4 edges, not 3**. Two assertions break on the
new edge count and must be re-derived:

- `test_multiday_splits_legs_within_budget` (days=3, hours_per_day=3 → 180 min
  budget): 4 edges × 162 min; greedy with max_days=3 folds the 4th edge into
  day 3 → `day.cruising_minutes == 324 > 180` → the `<= 3.0*60` assertion
  fails. Re-derive by lowering the scaled `length_m` — with `CRUISE_KMH = 4.8`
  (`pound/route/cost.py:9`), 90 min/edge ≈ **7.2 km/edge** is the ceiling for
  two edges/day within a 180-min budget (the ~9.7 km figure in earlier drafts
  was wrong: 9.7 km/edge ≈ 121 min, 2 edges/day ≈ 242 min > 180). Or
  alternatively assertion-adjust to the 4-edge chunking.
- `test_days_not_padded_beyond_route` (days=5, expects `len(r.days)==3`):
  4 edges → 4 days, not 3 → `len(r.days)==3` fails. Re-derive the expected
  count to 4.
- Update the `_long_plan` docstring ("3-edge path" → "4-edge path under noding").
- `test_days_partition_legs_exactly`, `test_days_count_never_exceeds_constraints_days`,
  `test_day_index_sequential` survive (they assert structural invariants, not
  specific edge counts) but re-verify.

**Unchanged & still valid:** the boatability filter, `prune_non_navigable_infra`,
the grid-bucket perf index (now applied per-segment if at all — see OQ-1), the
`docs/completed/…` boatability spec.

**Out-of-scope (noted, not migrated):** `scripts/curate_snaps.py` and
`scripts/diagnose_england_build.py` reference the removed `tolerance_m`/
`tolerance_snaps_unresolved`/`load_overrides` machinery. They are **untracked**
(not part of the committed repo) ad-hoc helpers from the live-testing sessions;
the implementer may delete or ignore them. They are not on the acceptance
path.

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
   tolerance-snap tests, plus noded regression tests), `ruff check .` clean
   (with the untracked `scripts/` helpers deleted per the OQ-1 note).
4. No production reference to `(lat, lon)` graph keys remains (grep-verified):
   only attribute access (`g.nodes[uid]["lat"]`) and the separate
   coordinate-keyed gazetteer *dict*. (`pound/route/snap.py` is deleted (§3.4);
   `pound/route/plan.py`'s `_name_for` migrated to attribute access (§5).)
5. A new regression test asserts the noded build joins an
   internal-junction way (a way sharing an OSM id only at an internal
   position of another way) — the exact defect this rewrite fixes.
6. A regression test asserts the edge-collision merge (§3.3): a `lock`-tagged
   edge coincident with a `canal`-tagged edge resolves to one edge with
   `kind == LOCK`, the **LOCK way's `osm_way_id`** kept (so `attach_locks`
   finds it), and `locks == 1` on the merged edge both at build time (§3.3
   merge sets it) and after `attach_locks`.
7. A regression test asserts the `attach_locks` lock-node tie-break (§3.5):
   with a `lock=yes` gate node coincident with both a LOCK segment and a canal
   spur, `locks == 1` lands on the LOCK segment and the canal spur stays at
   `locks == 0` (deterministic, not emission-order-dependent).

## Open questions (resolved as below)

- **OQ-1 — Does the grid-bucket spatial index survive?** It was a Phase-3
  tool (finding dangling-tip snap candidates). With Phase 3 removed, it has no
  consumer in this scope. **Decision:** remove it from `build_graph` now
  (YAGNI — no consumer); the perf it delivered was for the deleted snap pass.
  If a future curation seam needs nearest-node search, reintroduce it there
  with a real consumer. The build is already ~2 min without it.

> **Note on existing helper scripts:** `scripts/curate_snaps.py` and
> `scripts/diagnose_england_build.py` reference the removed `tolerance_m` /
> `tolerance_snaps_unresolved` / `load_overrides` machinery, and
> `curate_snaps.py:113` raises a `B905` ruff lint. They are **untracked** ad-hoc
> helpers from the live-testing sessions (not committed to the repo, but on
> disk under `scripts/`). The implementer should **delete them** before
> asserting acceptance criterion 3 (`ruff check .` clean), since `ruff` scans
> untracked files too; they carry no committed value.

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
