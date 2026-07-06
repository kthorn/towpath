# Pound — Noded Graph Build (Connectivity Rewrite) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `pound/graph/build.py::build_graph` as a *noded* build — every OSM node id along a routable way becomes a synthetic internal-uid graph node; consecutive ids become per-segment edges with honest haversine length and inherited way-level attrs; junctions (by OSM id, by rounded coordinate, or both — endpoint or internal) collapse at emission via two cooperating indexes. Remove the Phase 1 contraction, Phase 3 tolerance-snap, `overrides.json`, and grid-bucket machinery that operated on the broken endpoint-only model, so `pound-ingest build england` joins the real Midlands canal network into one ~240k-node giant component instead of 3,623 fragments.

**Architecture:** The build pipeline becomes `ingest/osm.py` (bulk reader, now builds `node_ids` and `geometry` from one aligned pass so `len(node_ids)==len(geometry)`) → `graph/build.py` (dual-index `resolve_or_create`: `osm_idx[str(id)]→uid` + `coord_idx[rounded_coord]→uid`; per-segment edges; edge-collision merge; closed-ring skip; **no** phases, snaps, overrides) → `graph/gazetteer.py::attach_node_names` (body rewrite: read `lat`/`lon` node attrs instead of comparing the key) → `graph/locks.py::attach_locks` (**flight-level chamber model**: a flight = connected component of LOCK ways chained by shared endpoints; `chambers = max(1, distinct_gates_on_flight − 1)`; per-segment attribution loads 1 lock on the segment whose downstream endpoint is a chamber's downstream gate; lock-node tie-break by `kind==LOCK` preferred) → `validate/connectivity.py` (drop snap/override report keys; keep advisory component reporting) → `graph/artifact.py` (unchanged). `route/snap.py` is **deleted** (its coord-tuple graph-node lookup breaks under uids); `route/plan.py` migrates off `snap_place` to an attribute-based inline resolve and off the stale `snap.build_gazetteer` import to `graph/gazetteer.py`. The Oxford fixture gains full `node_ids` arrays mirroring the bulk Geofabrik shape; the staircase fixture gains the boundary gate nodes its chamber count requires. Node keys become synthetic **internal uids** (monotonic counter), with `lat`/`lon`/`osm_node_ids` as node attributes — the Scope C `(lat,lon)`-tuple graph-key contract is broken and migrated for all consumers.

**Tech Stack:** Python 3.12+, Pydantic v2, NetworkX 3+, `pyosmium` (optional `bulk` extra), `osmium-tool` (system CLI prereq), pytest, ruff. No new request-time deps; `requests` stays offline-ingest-only; the request-time path stays pure-Python.

## Staging decision (flagged for the user before execution)

The spec's end state is **internal-uid graph node keys** (§3.1). The migration surface for that contract change is atomic — switching `build_graph`'s node-key type from coordinate-tuple to uid simultaneously breaks `attach_node_names`, `snap.py`, `plan.py::_name_for`, and the coord-key assertions in two test files, so those must all land together. To keep every commit green and every task a clean reviewer gate, the core rewrite is split into **two staged tasks**:

- **Task 2 (Stage A — noded topology, coordinate keys):** Lands the noded emission model, dual-index collapse, segment edges, edge-collision merge, fixture migration, `attach_locks` fixes, `validate`/`cli`/`overrides` cleanup, the three regression tests, and all count re-derivations — while keeping graph node keys as the rounded `(lat,lon)` coordinate tuple. Under coordinate keys the existing `attach_node_names` membership test (`if key in place_coords`), `snap.py::snap_place`, `plan.py::_name_for`, and the coord-key test assertions all still pass unchanged, so this task is independently **green** and independently reviewable.
- **Task 3 (Stage B — internal-uid node-key migration):** Switches graph node keys to the monotonic internal uid and migrates the consumers the spec requires migrated anyway: `attach_node_names` body rewrite (read attrs), delete `route/snap.py` + `tests/route/test_snap.py`, `plan.py` attribute-based resolve + `_name_for` signature, and the coord-key assertions in `test_gazetteer.py` / `test_connectivity.py`. Also independently **green**.

Each stage is a meaningful reviewer-rejectable unit (a reviewer can reject Stage A's coordinate-key choice without considering Stage B, or reject Stage B's uid approach on its merits), and neither writes throwaway consumer code — Stage A *defers* the consumer rewrites that Stage B performs, it does not write-then-rewrite them. The final state matches the spec exactly. If you prefer one atomic core commit instead of this staging, say so before execution and Tasks 2+3 collapse into a single (large) task.

## Global Constraints

- Python 3.12+; `uv` for env/deps. Base `uv sync` works with **no** `pyosmium` (it lives under `[project.optional-dependencies]` `bulk`).
- `osmium-tool` is a **system** CLI prereq (apt/brew/conda), the one non-`uv` install; README already documents it.
- The request-time path stays pure-Python, no network, no LLM — this plan migrates `route/plan.py`'s providers but does not change its `RuntimeError` production-artifact-loading path (PR2's concern).
- `build_graph` must remain safe on **empty `node_ids`** (the Overpass `out geom` dev path): the `osm_id` index is simply empty for id-less ways and resolve-or-create falls through to the `coord → uid` index. No code path may assume `node_ids` is non-empty.
- The noded emission loop assumes **`len(way.node_ids) == len(way.geometry)`**. This invariant is established in the readers (`overpass.parse` already satisfies it; `read_pbf` is fixed in Task 1 to build both lists from one aligned pass), never repaired in the build — a build-layer lockstep filter is unimplementable (`WaterwayWay` carries no per-ref validity flag) and would silently truncate.
- OSM data is ODbL: the committed fixture keeps its ODbL note; `pound/data/*` stays gitignored **except** `.gitkeep`. `pound/data/overrides.json` is **deleted** in this plan (no curation in scope).
- The real England extract (~1.5 GB at `pound/data/england.osm.pbf`) is a **manual prerequisite** — `pound-ingest build england` does not download it; `POUND_PBF_PATH` overrides the default.
- CI never asserts against real England — correctness there is the fixture-scale suite plus human eyeballing of the build report. `pyosmium`-needing tests get the `bulk` marker, auto-skipped without `--run-bulk` or when `pyosmium` isn't importable.
- Per AGENTS.md: commit messages conventional-style (`feat:`, `test:`, `chore:`, `refactor:`, `docs:`); frequent small commits; temp files via `mktemp` when needed; GitHub Actions pinned by SHA (N/A — no GH Actions here).
- The `osmium tags-filter` expression (`TAGS_FILTER_EXPR` in `osm.py`) is **unchanged** — it already produces the locatable-geometry the noded build needs.

## Open question flagged to the user before execution

- **OQ-A — `attach_locks` lock-count model: flight-level chamber count with per-segment attribution (decision, measured against the real England PBF; diverges from spec §3.5 literal wording).** Spec §3.5 instructs `attach_locks` to set `locks=1` on *all* edges matching `osm_way_id` (Model B). That overcounts the **215 of 1,993** England LOCK-classified ways with >2 nodes (87 with 7 nodes — a single physical chamber would bill 6× `LOCK_MINUTES` = 72 min). Kurt (2026-07-03) rejected one-lock-per-`osm_way_id` (Model A, under-counts multi-chamber ways) AND one-lock-per-segment (Model B) in favour of a **chamber-count model**: "for each lock, count entrance and exit, then reduce to 1 lock per chamber… for a staircase, handle the case where one chamber's exit is the next ones entrance… if we have three lock gates in a row, that has to be two chambers."
  **Measurement on `pound/data/england.osm.pbf` (2026-07-03) — what the data forces:** 1,993 LOCK-classified ways (England has **zero** `waterway=lock` ways; chambers are `waterway=canal` (1,712) or `waterway=river` (142) **+ `lock=yes`**). 3,373 `lock_gate`/`lock=yes` nodes (3,269 sit on a lock way). **173 staircase junctions share an endpoint; 79 of those endpoints ARE gate nodes, and 179 gate nodes are referenced by ≥2 lock ways** — i.e. one chamber's exit IS the next chamber's entrance (Kurt's exact case), so a per-way gate count **double-counts** shared gates. **1,598 ways have adjacent gate-gate ref pairs** (chamber-boundary gates with no shape node between). Per-way gate counting handles neither; the counting unit must be the **flight**.
  **Decision — Model D + attribution (iii):** a **flight** = a connected component of LOCK ways chained by shared endpoints (linear — zero branch endpoints exist in England). For each flight, `chambers = max(1, G − 1)` where G = count of **distinct** gate nodes (`waterway=lock_gate` or `lock=yes`) referenced along the flight's ways (shared + adjacent gates counted once). "Three gates in a row → two chambers" holds exactly. **Per-segment attribution:** for each segment edge in the flight whose **downstream endpoint node is a gate**, set `locks=1` (you bill a chamber when you exit through its downstream gate; direction-insensitive — routes in either direction read the one `locks` attr). **Floor:** a flight that got 0 lock edges (the **244 gateless flights** + 23 single-gate-`G<2` flights — gates not mapped) gets `locks=1` on its first segment edge by `osm_way_id`-then-segment order.
  **England aggregate:** chambers = **1,960** (distribution: 1,851 flights ×1, 31 ×2, 11 ×3, 1 ×4, 2 ×5; vs Model B's 2,927 which overcounts shape-node single chambers, and Model A's 1,993 which undercounts 45 multi-chamber flights). The 2,040 of an earlier per-way draft double-counted the 179 shared gates.
  **Fixture consequence — staircase fixture MUST be augmented** (see Task 2 Step 6b): the current staircase fixture has only **1 gate node** (6003 at the chamber1/2 boundary). Under Model D, G=1 → `max(1,0)` = **1 chamber**, breaking `test_staircase_counts_three_locks` (asserts `sum==3`). The fixture was built around Model A (one chamber per way) and is missing its boundary gates; to make it physically honest under Model D it gains **3 gate nodes** at the chamber boundaries → 4 gates → 3 chambers, and `test_staircase_counts_three_locks`'s `sum==3` AND `len(lock_edges)==3` stay green.
  **Regression tests (Task 2 Step 9):** `test_multi_node_lock_way_counts_chambers_by_gates` (a 4-node, 3-gate LOCK way → 2 lock edges on the two downstream-gate segments), `test_three_lock_gates_in_a_row_yields_two_chambers` (Kurt's prescription), `test_flight_level_shared_gate_counted_once` (two LOCK ways sharing a gate endpoint → that gate bounds both chambers once, not twice — the cross-way staircase case), `test_gateless_flight_floors_to_one_lock` (the 244-gateless-flights floor). Acceptance crit 6 (collision-merge `locks=max(existing,1)` at §3.3 sets `locks=1` at *build* on the LOCK `osm_way_id` edge) and crit 7 (lock-node tie-break) both stay green.
  **This diverges from spec §3.5's literal "set on all matching edges" wording and the spec's "Iterate all matching edges"/"set per edge"/"`lock_ways_attached` counts the way once (guard with a matched flag), not per segment" lines.** Those spec lines were written before the measurement; they are superseded by this OQ-A decision. The spec doc (`docs/superpowers/specs/2026-07-02-pound-noded-graph-build-design.md` §3.5) is updated in Task 2 Step 2b so plan and spec do not drift.

## File Structure

```
pound/
├── pound/
│   ├── graph/
│   │   ├── build.py            # MODIFY (Task 2, Task 3): dual-index noded emission + collision merge; remove phases/grid/overrides/_contract/load_overrides; Stage A coord keys, Stage B uid keys
│   │   ├── gazetteer.py        # MODIFY (Task 3): attach_node_names body rewrite (read lat/lon attrs); build_gazetteer/ambiguous_place_names unchanged
│   │   ├── locks.py            # MODIFY (Task 2): flight-level chamber model (max(1, distinct_gates-1)) with per-downstream-gate-segment attribution + gateless-flight floor + LOCK tie-break
│   │   └── artifact.py         # NO CHANGE
│   ├── ingest/
│   │   ├── osm.py              # MODIFY (Task 1): read_pbf alignment guard — build node_ids+geometry from one valid-location pass
│   │   ├── overpass.py         # NO CHANGE (already aligned)
│   │   ├── cli.py              # MODIFY (Task 2): drop --tolerance-m/--max-unresolved-snaps/--overrides + snap gate; keep derelict/self_loops gate
│   │   └── ir.py               # NO CHANGE
│   ├── route/
│   │   ├── snap.py             # DELETE (Task 3) entire module
│   │   └── plan.py             # MODIFY (Task 2 re-point gazetteer import; Task 3 inline resolve + _name_for(graph))
│   └── validate/
│       └── connectivity.py     # MODIFY (Task 2): drop tolerance_snaps_*/overrides_applied report keys; keep advisory component keys
├── pound/data/
│   └── overrides.json          # DELETE (Task 2)
│   └── .gitkeep                # EXISTS
├── scripts/
│   ├── curate_snaps.py         # DELETE (Task 2): untracked ad-hoc helper referencing removed machinery; ruff B905
│   └── diagnose_england_build.py # DELETE (Task 2): same
├── tests/
│   ├── fixtures/
│   │   ├── oxford_overpass_sample.json  # MODIFY (Task 2): full node_ids arrays; pendant near-end shares id 3002 + exact coord 51.754,-1.264
│   │   ├── staircase_overpass_sample.json # MODIFY (Task 2 Step 6b): add 3 boundary gate nodes (4 gates total) so 3 chambers hold under Model D
│   │   └── tiny_bulk.osm       # NO CHANGE
│   ├── graph/
│   │   ├── test_build.py       # MODIFY (Task 2): re-derive node 7->8 / edge 5->6; rename five_edges test; add assert edge==6
│   │   ├── test_build_bulk.py  # MODIFY (Task 2): delete all phase/snap/override/grid tests; add noded tests + crit 5/6 regression + crit 7
│   │   ├── test_gazetteer.py   # MODIFY (Task 3): coord-key asserts -> uid-based lookup
│   │   ├── test_locks.py       # MODIFY (Task 2): widen test_non_lock_edges to include 1007
│   │   └── test_artifact.py    # NO CHANGE
│   ├── validate/
│   │   └── test_connectivity.py # MODIFY (Task 2): re-derive counts + drop snap-key asserts; MODIFY (Task 3): coord-key add_node -> uid
│   ├── route/
│   │   ├── test_snap.py       # DELETE (Task 3) with the module
│   │   └── test_plan_route.py # MODIFY (Task 2): _long_plan 3-edge->4-edge re-derive + docstring rewrite; raise days=3->4
│   └── ingest/
│       ├── test_cli.py        # MODIFY (Task 2): drop the 3 flag invocations + 2 removed-gate tests
│       ├── test_pipeline_integration.py # MODIFY (Task 2): drop flag args + snap asserts; delete pendant-unresolved gate test
│       └── test_osm.py        # MODIFY (Task 1): add alignment-guard regression test (bulk-marked)
```

---

### Task 1: `read_pbf` alignment guard — `len(node_ids) == len(geometry)` by construction

**Files:**

- Modify: `pound/ingest/osm.py:79-105` (the `_Handler.way` body in `read_pbf`)
- Test: `tests/ingest/test_osm.py` (add a `bulk`-marked regression test; the existing `tiny_bulk.osm` fixture has all nodes locatable so the guard is otherwise untested)

**Interfaces:**

- Consumes: nothing new — depends only on the existing `WaterwayWay` IR (`pound/ingest/ir.py`).
- Produces: `WaterwayWay.node_ids` and `.geometry` guaranteed aligned (`len(node_ids) == len(geometry)`, element-wise paired) for every way. `node_ids` now lists **only locatable** refs (not every raw ref) — the correct IR invariant for the noded build; the reader remains a faithful producer of the locatable geometry, which is all the build can use.

**Why this task first:** It is purely additive, independent of the build rewrite, follows a clean red→green TDD cycle, and the noded emission loop in Task 2 assumes the alignment it guarantees. `overpass.parse` (the dev path) already satisfies it; `read_pbf` does not — today `node_ids = [n.ref for n in w.nodes]` takes every ref while `geometry` keeps only valid-location refs, so the two lists diverge in length when a referenced node lacks coordinates.

- [ ] **Step 1: Write the failing regression test**

Append to `tests/ingest/test_osm.py` (after the existing `pytestmark = pytest.mark.bulk`):

```python
def test_read_pbf_aligns_node_ids_with_geometry_when_one_ref_lacks_location(tmp_path):
    """The noded build zips node_ids with geometry 1-to-1. If a way references
    a node whose location is invalid/unset, read_pbf must EXCLUDE that ref from
    BOTH lists (not include it in node_ids alone), so the two stay paired by
    construction. tiny_bulk.osm has every node locatable, so this needs a PBF
    whose raw refs > locatable refs."""
    from pound.ingest.osm import read_pbf

    # Minimal OSM XML: way 1001 refs nodes 1, 2, 3 where node 2 has NO lat/lon.
    # Locatable refs = {1, 3}; raw refs = {1, 2, 3}. node_ids must == [1, 3]
    # and geometry must have 2 points, paired (1->coord1, 3->coord3).
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="alignment fixture">
  <node id="1" lat="51.7500000" lon="-1.2600000" version="1"/>
  <node id="2" version="1"/>
  <node id="3" lat="51.7520000" lon="-1.2620000" version="1"/>
  <way id="1001" version="1">
    <nd ref="1"/><nd ref="2"/><nd ref="3"/>
    <tag k="waterway" v="canal"/><tag k="name" v="Alignment Way"/>
  </way>
</osm>
"""
    pbf = tmp_path / "unaligned.osm"
    pbf.write_text(xml)
    feats = read_pbf(pbf)
    assert len(feats.ways) == 1
    way = feats.ways[0]
    assert len(way.node_ids) == len(way.geometry), (way.node_ids, way.geometry)
    assert way.node_ids == [1, 3]
    assert way.geometry == [(51.75, -1.26), (51.752, -1.262)]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/ingest/test_osm.py::test_read_pbf_aligns_node_ids_with_geometry_when_one_ref_lacks_location --run-bulk -v`

Expected: FAIL — `assert [1, 2, 3] == [1, 3]` (current `node_ids = [n.ref for n in w.nodes]` keeps the un-locatable ref 2, so `len==3` vs `len(geometry)==2`).

- [ ] **Step 3: Implement the alignment guard in `read_pbf`**

In `pound/ingest/osm.py`, replace the `_Handler.way` body's geometry + node_ids construction. The current code is:

```python
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
```

Replace it with a single pass that keeps a ref only when its location is valid, building both lists from the same kept pairs so they are aligned by construction:

```python
        def way(self, w):
            tags = {t.k: t.v for t in w.tags}
            if filters.is_derelict(tags):
                return
            kind = filters.classify_way(tags)
            if kind is None:
                return
            # Build node_ids and geometry from ONE pass over w.nodes, keeping the
            # (ref, (lat, lon)) pair only when n.location.valid. This guarantees
            # len(node_ids) == len(geometry), element-wise paired — the invariant
            # the noded build zips on. node_ids lists locatable refs only (not
            # every raw ref): the reader cannot represent un-locatable refs in the
            # geometry anyway, so including them in node_ids alone would silently
            # misalign the two lists.
            node_ids: list[int] = []
            geom: list[tuple[float, float]] = []
            for n in w.nodes:
                if not n.location.valid:
                    continue
                node_ids.append(n.ref)
                geom.append((n.location.lat, n.location.lon))
            if len(geom) < 2:
                return
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
```

- [ ] **Step 4: Run the new and existing osm tests to confirm green**

Run: `pytest tests/ingest/test_osm.py --run-bulk -v`

Expected: PASS — the new alignment test passes; `test_read_pbf_populates_node_ids_and_features` and the round-trip test still pass (tiny_bulk.osm has all nodes locatable, so the aligned pass yields the same `node_ids`/`geometry` as before).

- [ ] **Step 5: Run the full suite to confirm nothing else broke**

Run: `pytest -q`

Expected: PASS (same count as before this task; the non-bulk tests are unaffected and the bulk tests now also pass under `--run-bulk`).

- [ ] **Step 6: Commit**

```bash
git add pound/ingest/osm.py tests/ingest/test_osm.py
git commit -m "fix(ingest): align read_pbf node_ids with geometry (valid-location pass only)"
```

---

### Task 2 (Stage A): Noded `build_graph` rewrite — coordinate keys — fixture migration — coupled consumer/test re-derivations — regression tests — cleanup

**Files:**

- Modify: `pound/graph/build.py` (full body rewrite + module docstring)
- Modify: `pound/graph/locks.py` (flight-level chamber model: flights, `max(1, distinct_gates−1)`, per-downstream-gate-segment attribution, gateless-flight floor, LOCK tie-break)
- Modify: `tests/fixtures/staircase_overpass_sample.json` (Step 6b: add 3 boundary gate nodes → 4 gates → 3 chambers under Model D)
- Modify: `pound/validate/connectivity.py` (drop snap/override report keys)
- Modify: `pound/ingest/cli.py` (drop 3 flags + snap gate)
- Modify: `pound/route/plan.py` (re-point `build_gazetteer` import to `graph/gazetteer.py`)
- Modify: `tests/fixtures/oxford_overpass_sample.json` (full `node_ids`; pendant shares id 3002 + exact coord)
- Modify: `tests/graph/test_build.py` (re-derive counts; rename five-edges test)
- Modify: `tests/graph/test_build_bulk.py` (delete phase/snap/override/grid tests; add noded tests + crit 5/6/7)
- Modify: `tests/graph/test_locks.py` (widen `test_non_lock_edges_have_zero_locks` to include 1007; re-derive if needed)
- Modify: `tests/validate/test_connectivity.py` (re-derive counts; drop snap-key asserts; keep surviving-key assertions)
- Modify: `tests/ingest/test_cli.py` (drop 3 flag invocations + 2 removed-gate tests)
- Modify: `tests/ingest/test_pipeline_integration.py` (drop flag args + snap asserts; delete pendant-unresolved test)
- Modify: `tests/route/test_plan_route.py` (`_long_plan` 3→4 edges; raise `days=3→4`; rewrite docstring)
- Delete: `pound/data/overrides.json`
- Delete: `scripts/curate_snaps.py`, `scripts/diagnose_england_build.py`

**Interfaces:**

- Consumes: `WaterwayFeatures` (`pound/ingest/ir.py`); every routable way with `len(node_ids) == len(geometry)` (Task 1); id-less ways (`node_ids == []`) take the coord-only branch.
- Produces: `build_graph(features) -> nx.Graph` with **no kwargs** (signatures `tolerance_m`/`overrides` gone). Graph node keys are rounded `(lat, lon)` coordinate tuples **in this task** (Stage B in Task 3 switches them to internal uids). Node attrs: `lat`, `lon`, `osm_node_ids: set[str]`. Edge attrs: `osm_way_id`, `name`, `kind`, `length_m`, `dimensions`, `has_tunnel`, `has_movable_bridge`, `locks`, `geometry` (the segment's two coords). Graph attrs: none of the old snap/override keys. `validate_graph` returns a dict **without** `tolerance_snaps_used`/`tolerance_snaps_unresolved`/`overrides_applied`.

**Atomicity note:** Switching `build_graph` to the noded body (and dropping its kwargs) breaks every test that calls `build_graph(...)` with old kwargs or asserts old counts, *simultaneously*. This task is therefore one green-commit unit: the steps below land edits in the order that keeps the path forward coherent, and the single `git commit` at Step N is the first point the whole suite is green again. Intermediate steps will have failing tests until the coupled edits are complete — that is expected, not a deviation from TDD (the "RED" here spans the coordinated edit set; the "GREEN" is the full-suite pass before commit).

- [ ] **Step 1: Replace `pound/graph/build.py` with the noded implementation (coordinate keys)**

Write the entire file as:

```python
"""WaterwayFeatures -> noded NetworkX graph (noded build, design §3.2-§3.5).

Every OSM node id along a routable way becomes a graph node; consecutive ids
become edges with per-segment haversine length and inherited way-level attrs.
Junctions collapse at emission via two cooperating indexes (OSM-id and
rounded-coordinate), so shared junctions — by OSM id, by coordinate, or both,
endpoint or internal — join for free, with NO contraction phase, NO
tolerance-snap pass, and NO overrides/curation. Closed-ring ways (first coord
== last) are area polygons, never routable, and are skipped.

Node keys are rounded (lat, lon) tuples in this stage; lat/lon and
osm_node_ids (set of stringified OSM ids) are node attributes. id-less dev
ways (Overpass `out geom`) resolve-or-create via the coordinate index alone.
Edge collision (two ways producing the same node pair) merges attributes
(kind by specificity, dimensions union-tightened, name first non-None,
tunnel/movable-bridge OR-ed; on a LOCK-involving collision the merged edge
keeps the LOCK way's osm_way_id and gets locks=1 immediately).
"""

import math
from dataclasses import replace

import networkx as nx

from pound.ingest.ir import WaterwayFeatures, WaterwayKind, WayDimensions

_ROUND = 7
_ROUTABLE = {WaterwayKind.CANAL, WaterwayKind.RIVER, WaterwayKind.FAIRWAY, WaterwayKind.LOCK}
# Edge-collision kind specificity (§3.3): LOCK > CANAL > RIVER > FAIRWAY.
# Calder-and-Hebble river-vs-canal dual-classification prefers CANAL (the
# stronger navigability signal for this project).
_KIND_RANK = {
    WaterwayKind.LOCK: 3,
    WaterwayKind.CANAL: 2,
    WaterwayKind.RIVER: 1,
    WaterwayKind.FAIRWAY: 0,
}


def _node_key(lat: float, lon: float) -> tuple[float, float]:
    return (round(lat, _ROUND), round(lon, _ROUND))


def _haversine_m(a, b) -> float:
    r = 6_371_000.0
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _min_nonnone(x: float | None, y: float | None) -> float | None:
    if x is None:
        return y
    if y is None:
        return x
    return min(x, y)


def _merge_dims(a: WayDimensions | None, b: WayDimensions | None) -> WayDimensions | None:
    if a is None:
        return b
    if b is None:
        return a
    return WayDimensions(
        max_beam_m=_min_nonnone(a.max_beam_m, b.max_beam_m),
        max_length_m=_min_nonnone(a.max_length_m, b.max_length_m),
        max_draft_m=_min_nonnone(a.max_draft_m, b.max_draft_m),
        max_height_m=_min_nonnone(a.max_height_m, b.max_height_m),
    )


def build_graph(features: WaterwayFeatures) -> nx.Graph:
    """Build a noded graph from WaterwayFeatures.

    Every OSM node id on a routable way is a graph node; consecutive ids are
    edges. Junctions collapse at emission via the osm-id and coordinate
    indexes — no separate contraction/snap/override phase. Safe on id-less
    ways (Overpass path): they mint nodes by rounded coordinate alone.
    """
    g = nx.Graph()
    osm_idx: dict[str, tuple] = {}      # str(osm id) -> node key
    coord_idx: dict[tuple, tuple] = {}  # rounded coord -> node key

    def _resolve_or_create(osm_id, lat, lon):
        sid = str(osm_id) if osm_id is not None else None
        coord = _node_key(lat, lon)
        key = None
        if sid is not None and sid in osm_idx:
            key = osm_idx[sid]
        if key is None and coord in coord_idx:
            key = coord_idx[coord]
        if key is None:
            key = coord  # coordinate-as-key stage
            g.add_node(key, lat=coord[0], lon=coord[1], osm_node_ids=set())
            coord_idx[coord] = key
        if sid is not None:
            osm_idx[sid] = key
            coord_idx.setdefault(coord, key)
            g.nodes[key]["osm_node_ids"].add(sid)
        return key

    def _merge_edge(u, v, way, length_m, seg_geom):
        d = g[u][v]
        existed_lock = d["kind"] == WaterwayKind.LOCK
        new_lock = way.kind == WaterwayKind.LOCK
        # kind: more-specific wins (LOCK>CANAL>RIVER>FAIRWAY; CANAL>RIVER for the
        # dual-classified case).
        if _KIND_RANK[way.kind] > _KIND_RANK[d["kind"]]:
            d["kind"] = way.kind
        # osm_way_id: keep the LOCK way's id when exactly one party is LOCK
        # (so attach_locks finds the merged LOCK edge by osm_way_id); else keep
        # the existing (first-emitted) id.
        if new_lock and not existed_lock:
            d["osm_way_id"] = way.osm_id
        # dimensions: union-tighten (min non-None per axis).
        d["dimensions"] = _merge_dims(d["dimensions"], way.dimensions)
        # name: keep first non-None.
        if d.get("name") is None and way.name is not None:
            d["name"] = way.name
        # tunnel / movable bridge: logical OR.
        d["has_tunnel"] = bool(d.get("has_tunnel") or way.has_tunnel)
        d["has_movable_bridge"] = bool(d.get("has_movable_bridge") or way.has_movable_bridge)
        # length_m: coincident endpoints => equal by construction; keep existing.
        # locks: a LOCK-involving collision sets max(existing, 1) at merge time.
        if existed_lock or new_lock:
            d["locks"] = max(d.get("locks", 0), 1)
        # geometry: keep the existing 2-point segment (coincident by construction).

    for way in features.ways:
        if way.kind not in _ROUTABLE:
            continue
        if len(way.geometry) < 2:
            continue
        # Closed-ring way: an area polygon (lock-chamber outline, basin, wetland,
        # water body), never a routable edge. A navigable ring is a graph cycle
        # of DISTINCT linear ways, not one closed way. Skipping keeps the
        # self_loops==0 gate honest and drops no routable geometry.
        if _node_key(*way.geometry[0]) == _node_key(*way.geometry[-1]):
            continue
        # resolve-or-create one graph node per OSM node id (id-less ways: per coord)
        uids = [
            _resolve_or_create(
                way.node_ids[i] if way.node_ids else None,
                way.geometry[i][0],
                way.geometry[i][1],
            )
            for i in range(len(way.geometry))
        ]
        for i in range(len(uids) - 1):
            u, v = uids[i], uids[i + 1]
            if u == v:
                continue  # consecutive duplicate id/coord -> zero-length self-loop; skip
            length_m = _haversine_m(way.geometry[i], way.geometry[i + 1])
            seg_geom = [way.geometry[i], way.geometry[i + 1]]
            if g.has_edge(u, v):
                _merge_edge(u, v, way, length_m, seg_geom)
            else:
                g.add_edge(
                    u,
                    v,
                    osm_way_id=way.osm_id,
                    name=way.name,
                    kind=way.kind,
                    length_m=length_m,
                    dimensions=way.dimensions,
                    has_tunnel=way.has_tunnel,
                    has_movable_bridge=way.has_movable_bridge,
                    locks=0,
                    geometry=seg_geom,
                )
    return g
```

Remove `load_overrides`, `_contract`, `_key_for_osm_id`, and the `json`/`Path` imports (no longer used). Remove the unused `replace` dataclass import if linters flag it — actually `replace` is unused; drop the `from dataclasses import replace` line.

- [ ] **Step 2: Rewrite `attach_locks` in `pound/graph/locks.py` (flight-level chamber model + per-segment attribution + LOCK tie-break)**

Replace the body of `attach_locks` (keep the module docstring, `_edge_point_dist_m`, imports, and the `tolerance_m` default). The full new function:

```python
def attach_locks(
    graph: nx.Graph, features: WaterwayFeatures, tolerance_m: float = 25.0
) -> tuple[nx.Graph, dict]:
    g = copy.deepcopy(graph)
    report = {
        "lock_ways_attached": 0,
        "lock_nodes_attached": 0,
        "orphan_lock_ways": [],
        "orphan_lock_nodes": [],
        "lock_gate_nodes": 0,
    }

    # --- Lock ways: flight-level chamber attribution (Model D + iii) --------
    # A FLIGHT is a connected component of LOCK ways chained by shared endpoints
    # (linear; England has zero branch endpoints). chambers = max(1, G-1) where
    # G = count of DISTINCT gate nodes (lock_gate or lock=yes) referenced along
    # the flight's ways — shared/adjacent gates counted once. "Three gates in a
    # row -> two chambers"; one chamber's exit gate being the next's entrance
    # (a gate node referenced by two ways) is counted once, not twice.
    # Attribution: for each chamber whose downstream boundary is a gate node, set
    # locks=1 on the segment edge whose downstream endpoint IS that gate (you
    # bill the chamber on exiting through its downstream gate; direction-
    # insensitive — routes in either direction read the one locks attr). A
    # gateless flight (G<2, gates not mapped) floors to 1 lock on its first
    # segment edge by (osm_way_id, segment index) order.
    gate_ids = {n.osm_id for n in features.nodes if n.kind in (NodeKind.LOCK_GATE, NodeKind.LOCK)}
    lock_ways = [w for w in features.ways if w.kind == WaterwayKind.LOCK]
    # Build adjacency by shared OSM node-id endpoint, then find flights (CCs).
    endpoint_ways: dict[int, set[int]] = {}
    for w in lock_ways:
        if not w.node_ids:
            continue
        for ref in (w.node_ids[0], w.node_ids[-1]):
            endpoint_ways.setdefault(ref, set()).add(w.osm_id)
    seen_way_ids: set[int] = set()
    flights: list[list[int]] = []  # each flight is a list of osm_way_ids
    for w in lock_ways:
        if w.osm_id in seen_way_ids or not w.node_ids:
            continue
        stack = [w.osm_id]
        seen_way_ids.add(w.osm_id)
        comp: list[int] = []
        while stack:
            wid = stack.pop()
            comp.append(wid)
            way = next(x for x in lock_ways if x.osm_id == wid)
            for ref in (way.node_ids[0], way.node_ids[-1]):
                for nb in endpoint_ways.get(ref, set()):
                    if nb not in seen_way_ids:
                        seen_way_ids.add(nb)
                        stack.append(nb)
        flights.append(comp)
    # id-less lock ways (Overpass dev path): each is its own flight.
    for w in lock_ways:
        if not w.node_ids and w.osm_id not in seen_way_ids:
            seen_way_ids.add(w.osm_id)
            flights.append([w.osm_id])

    # Index segment edges by (osm_way_id, segment_index). Segment index is the
    # position of the segment in its parent way's node ordering — recorded at
    # build time on the edge so multi-segment ways can be walked in order.
    # (build_graph emits edges with osm_way_id; segment_index is implicit in the
    # order edges appear in g.edges for a given osm_way_id, which NetworkX
    # preserves by insertion order. We group edges by osm_way_id and sort by
    # segment index, recoverable from each edge's downstream node's osm_node_ids.)
    way_edges: dict[int, list[tuple[object, object, dict]]] = {}
    for u, v, d in g.edges(data=True):
        wid = d.get("osm_way_id")
        if wid is not None:
            way_edges.setdefault(wid, []).append((u, v, d))

    def _attached_flag(vals):
        return any(d.get("locks", 0) >= 1 for _, _, d in vals)

    for flight in flights:
        # Collect this flight's ways in flight order, and their segment edges in
        # node order. For each way, sort its edges by segment index (the position
        # of the downstream node in the way's node_ids).
        flight_ways = [next(x for x in lock_ways if x.osm_id == wid) for wid in flight]
        # Per-way ordered segments: list of (way, u, v, d, downstream_ref)
        way_segments: list[tuple] = []
        for w in flight_ways:
            edges = list(way_edges.get(w.osm_id, []))
            if not edges or not w.node_ids:
                continue
            # Map each edge to its segment index via the downstream node's
            # osm_node_ids (the downstream node of segment i is node_ids[i+1]).
            def _seg_idx(edge):
                u, v, d = edge
                downstream_ids = g.nodes[v].get("osm_node_ids", set()) | g.nodes[u].get("osm_node_ids", set())
                idxs = [i + 1 for i, ref in enumerate(w.node_ids) if str(ref) in downstream_ids]
                return min(idxs) if idxs else 0
            edges.sort(key=_seg_idx)
            for i, (u, v, d) in enumerate(edges):
                # downstream ref is the vertex that is NOT shared with the
                # previous segment; approximate by reading node osm_node_ids.
                u_ids = g.nodes[u].get("osm_node_ids", set())
                v_ids = g.nodes[v].get("osm_node_ids", set())
                down_ref = w.node_ids[i + 1] if i + 1 < len(w.node_ids) else None
                way_segments.append((w, u, v, d, down_ref))
        # Set locks=1 on each segment whose downstream ref is a gate.
        lock_segments = []
        for (w, u, v, d, down_ref) in way_segments:
            if down_ref is not None and down_ref in gate_ids:
                d["locks"] = max(d.get("locks", 0), 1)
                lock_segments.append((w.osm_id, u, v, d))
        # Floor: gateless flight -> 1 lock on the first segment of the first way.
        if not lock_segments and way_segments:
            w0, u0, v0, d0, _ = way_segments[0]
            d0["locks"] = max(d0.get("locks", 0), 1)
            lock_segments.append((w0.osm_id, u0, v0, d0))
        # report: one lock_wayAttached per flight way that has >=1 matched edge.
        attached_ways = {wid for wid, _, _, _ in lock_segments}
        for w in flight_ways:
            if w.osm_id in attached_ways or way_edges.get(w.osm_id):
                if w.osm_id in attached_ways:
                    report["lock_ways_attached"] += 1
                else:
                    report["orphan_lock_ways"].append(w.osm_id)
            else:
                report["orphan_lock_ways"].append(w.osm_id)

    # --- Lock nodes: nearest-edge attach with LOCK tie-break (§3.5) --------
    # snap to the nearest edge within tolerance, breaking ties by kind==LOCK
    # preferred, then shorter segment, then first-seen. A gate node that is
    # itself an OSM node of two coincident edges (a LOCK chamber and a canal spur
    # sharing the junction) is distance 0 to both; without the kind tie-break,
    # insertion order would decide and a coincident canal spur could spuriously
    # win locks=1.
    for node in features.nodes:
        if node.kind == NodeKind.LOCK_GATE:
            report["lock_gate_nodes"] += 1
            continue  # gates don't increment lock count
        if node.kind != NodeKind.LOCK:
            continue
        best_edge = None
        best_key = None
        for u, v, d in g.edges(data=True):
            dist = _edge_point_dist_m(d.get("geometry", []), node.lat, node.lon)
            if dist > tolerance_m:
                continue
            is_lock = d.get("kind") == WaterwayKind.LOCK
            key = (dist, 0 if is_lock else 1, d.get("length_m", math.inf))
            if best_key is None or key < best_key:
                best_key = key
                best_edge = (u, v, d)
        if best_edge is not None:
            best_edge[2]["locks"] = max(best_edge[2].get("locks", 0), 1)
            report["lock_nodes_attached"] += 1
        else:
            report["orphan_lock_nodes"].append(node.osm_id)

    return g, report
```

**Rationale (flight-level Model D + per-segment attribution, measured):** see OQ-A above — England has 1,993 LOCK ways forming 1,896 flights; 179 gate nodes are shared across ways (one chamber's exit IS the next's entrance — Kurt's case) and 1,598 ways have adjacent gate-gate refs, both of which per-way counting mishandles. The flight-level model counts distinct gates once; per-segment attribution bills a chamber when the route exits through its downstream gate, so end-to-end flight traversal bills `chambers × LOCK_MINUTES` (the honest routing cost; partial mid-flight traversal — barely exercised in the data, since internal flight nodes are gates/shape nodes, not way-junctions — bills for chambers fully traversed). Aggregate England chambers = **1,960** (vs Model B's 2,927 which overcounts shape-node single chambers, and Model A's 1,993 which undercounts 45 multi-chamber flights). The staircase fixture (Task 2 Step 6b) is augmented to 4 gates → 3 chambers so `test_staircase_counts_three_locks` (`sum==3`, `len(lock_edges)==3`) stays green. See the four regression tests in Step 9 below (`test_multi_node_lock_way_counts_chambers_by_gates`, `test_three_lock_gates_in_a_row_yields_two_chambers`, `test_flight_level_shared_gate_counted_once`, `test_gateless_flight_floors_to_one_lock`).

(The `tolerance_m` candidate-cell perf index from the old build is not needed here; `attach_locks` already iterated every edge per node and that is fine for the fixture + the bulk lock-node counts are not acceptance-gated.)

- [ ] **Step 2b: Update the spec doc §3.5 to match this decision (plan/spec no drift)**

In `docs/superpowers/specs/2026-07-02-pound-noded-graph-build-design.md`, supersede the two `attach_locks` paragraphs in §3.5 ("Iterate all matching edges…"/"set per edge")/"`lock_ways_attached` counts the way once (guard with a matched flag), not per segment") and the matching §5 row (`pound/graph/locks.py::attach_locks`) with the Model D + per-segment-attribution algorithm and rationale above (the four-bullet measurement: 1,993 ways / 1,896 flights / 179 shared gates / 1,598 adjacent-gate ways; aggregate 1,960 chambers; the gateless-flight floor). Note this is an OQ-A decision dated 2026-07-03 that supersedes the spec's literal "set on all matching edges" wording; the staircase-fixture augmentation is reflected in §5's `staircase_overpass_sample.json` row (`MODIFY`, no longer `NO CHANGE`). This is a docs-only commit step — fold it into the Step 16 commit.

- [ ] **Step 3: Drop snap/override report keys in `pound/validate/connectivity.py`**

In `validate_graph`, remove the three lines that read the removed graph attrs and the three keys from the returned dict. Replace this block:

```python
    gg = graph.graph
    snaps_used = list(gg.get("tolerance_snaps_used", []))
    snaps_unresolved = list(gg.get("tolerance_snaps_unresolved", []))
    overrides_applied = int(gg.get("overrides_applied", 0))

    gaz = gg.get("gazetteer", {})
```

with:

```python
    gg = graph.graph
    gaz = gg.get("gazetteer", {})
```

and remove from the returned dict the three keys:

```python
        "overrides_applied": overrides_applied,
        "tolerance_snaps_used": snaps_used,
        "tolerance_snaps_unresolved": snaps_unresolved,
```

Keep every other key (`component_count`, `largest_component_size`, `component_sizes`, `orphan_*`, `derelict_edges`, `edges_missing_dims`, `zero_length_edges`, `self_loops`, `total_edges`, `total_nodes`, `place_nodes_seen`, `place_nodes_in_gazetteer`, `named_nodes_in_graph`, `ambiguous_place_names`).

- [ ] **Step 4: Drop the three CLI flags and the snap gate in `pound/ingest/cli.py`**

In `_build_from_features`, remove the overrides load and the `tolerance_m`/`overrides` kwargs. Replace:

```python
def _build_from_features(features, args) -> int:
    overrides_path = Path(args.overrides) if args.overrides else _DEFAULT_OVERRIDES
    overrides = load_overrides(overrides_path)
    graph = build_graph(features, tolerance_m=args.tolerance_m, overrides=overrides)
```

with:

```python
def _build_from_features(features, args) -> int:
    graph = build_graph(features)
```

Remove the snap-gate block — replace:

```python
    if len(validation["tolerance_snaps_unresolved"]) > args.max_unresolved_snaps:
        fail_reasons.append(
            f"tolerance_snaps_unresolved={len(validation['tolerance_snaps_unresolved'])} "
            f"> --max-unresolved-snaps={args.max_unresolved_snaps}"
        )
    if fail_reasons:
```

with:

```python
    if fail_reasons:
```

In `_register_build`, remove the three `b.add_argument` lines for `--tolerance-m`, `--max-unresolved-snaps`, and `--overrides`. Remove the now-unused imports: `from pound.graph.build import load_overrides` (keep `build_graph`), and the `Path` import if it becomes unused (it is still used for `args.pbf`/`args.out` — keep it). Remove `_DEFAULT_OVERRIDES`. Update the module docstring's `Usage:` lines to drop the three flags.

- [ ] **Step 5: Re-point `plan.py`'s `build_gazetteer` import to the live module**

In `pound/route/plan.py`, replace:

```python
from pound.route.snap import build_gazetteer, snap_place
```

with:

```python
from pound.graph.gazetteer import build_gazetteer
from pound.route.snap import snap_place
```

(`snap_place` stays imported for this stage — it still works under coordinate keys; Task 3 deletes it and inlines a resolve.) No other change to `plan.py` in this task: `_name_for` keeps its coordinate-key comparison (still valid under coordinate keys), and the list-valued gazetteer entry caveat (ambiguous names fall through to the coord-string fallback — the documented interim regression) carries through unchanged.

- [ ] **Step 6: Migrate the Oxford fixture to full `node_ids`**

Overwrite `tests/fixtures/oxford_overpass_sample.json` with the topology below. Chain junctions join by **shared OSM id** (1001's last == 1002's first == id `13`; 1002's last == 1003's first == id `5003`); the pendant joins the chain for free by sharing id `3002` with way 1003's **far** node at the exact coord `51.754,-1.264` (the deliberate sub-millimetre offset is dropped so the junction is real and `attach_node_names` is deterministic). Ways 1004/1005 stay filtered; Duke's Cut 1006 stays isolated. Place node `3002` (Hayfield) IS the junction node (referenced by ways 1003 and 1007), which is valid OSM.

```json
{
  "version": 0.6,
  "generator": "Overpass API (test fixture, hand-curated)",
  "osm3s": {
    "timestamp_osm_base": "2026-06-21T12:00:00Z",
    "copyright": "The data included in this document is from www.openstreetmap.org. The data is made available under users under the Open Database License (ODbL)."
  },
  "elements": [
    {
      "type": "way", "id": 1001,
      "nodes": [11, 12, 13],
      "tags": {"waterway": "canal", "name": "Oxford Canal"},
      "geometry": [
        {"lat": 51.7500, "lon": -1.2600},
        {"lat": 51.7510, "lon": -1.2610},
        {"lat": 51.7520, "lon": -1.2620}
      ]
    },
    {
      "type": "way", "id": 1002,
      "nodes": [13, 5003],
      "tags": {"waterway": "canal", "name": "Oxford Canal", "maxwidth": "2.1", "maxdraught": "0.9"},
      "geometry": [
        {"lat": 51.7520, "lon": -1.2620},
        {"lat": 51.7530, "lon": -1.2630}
      ]
    },
    {
      "type": "way", "id": 1003,
      "nodes": [5003, 3002],
      "tags": {"waterway": "lock", "name": "Hayfield Lock"},
      "geometry": [
        {"lat": 51.7530, "lon": -1.2630},
        {"lat": 51.7540, "lon": -1.2640}
      ]
    },
    {
      "type": "way", "id": 1004,
      "tags": {"waterway": "canal", "name": "Old Arm (disused)", "disused:waterway": "canal"},
      "geometry": [
        {"lat": 51.7600, "lon": -1.2700},
        {"lat": 51.7610, "lon": -1.2710}
      ]
    },
    {
      "type": "way", "id": 1005,
      "tags": {"waterway": "derelict_canal", "name": "Abandoned Branch"},
      "geometry": [
        {"lat": 51.7700, "lon": -1.2800},
        {"lat": 51.7710, "lon": -1.2810}
      ]
    },
    {
      "type": "way", "id": 1006,
      "nodes": [6001, 6002],
      "tags": {"waterway": "canal", "name": "Duke's Cut", "tunnel": "yes"},
      "geometry": [
        {"lat": 51.7400, "lon": -1.2500},
        {"lat": 51.7410, "lon": -1.2510}
      ]
    },
    {
      "type": "way", "id": 1007,
      "nodes": [3002, 7002],
      "tags": {"waterway": "canal", "name": "Marston Spur"},
      "geometry": [
        {"lat": 51.7540, "lon": -1.2640},
        {"lat": 51.7556, "lon": -1.2659}
      ]
    },
    {
      "type": "node", "id": 2001, "lat": 51.7535, "lon": -1.2635,
      "tags": {"waterway": "lock_gate"}
    },
    {
      "type": "node", "id": 2002, "lat": 51.7540, "lon": -1.2640,
      "tags": {"lock": "yes"}
    },
    {
      "type": "node", "id": 2003, "lat": 51.7450, "lon": -1.2550,
      "tags": {"mooring": "yes"}
    },
    {
      "type": "node", "id": 2004, "lat": 51.7480, "lon": -1.2580,
      "tags": {"amenity": "pub", "name": "The Navigation"}
    },
    {
      "type": "node", "id": 3001, "lat": 51.7500, "lon": -1.2600,
      "tags": {"place": "city", "name": "Oxford"}
    },
    {
      "type": "node", "id": 3002, "lat": 51.7540, "lon": -1.2640,
      "tags": {"place": "hamlet", "name": "Hayfield"}
    },
    {
      "type": "node", "id": 3003, "lat": 51.7556, "lon": -1.2659,
      "tags": {"place": "suburb", "name": "Marston"}
    }
  ]
}
```

Delete `pound/data/overrides.json` (its only entry `{"join": [["3002","7001"]]}` is obsolete — the junction is now real and joins for free) and remove the matching whitelist line from `.gitignore` if present (it whitelisted `!pound/data/overrides.json`).

- [ ] **Step 6b: Augment the staircase fixture with boundary gate nodes (Model D requires it)**

The current `tests/fixtures/staircase_overpass_sample.json` has three `waterway=canal + lock=yes` chamber ways (5101, 5102, 5103) but only **one** gate node (6003 at `52.001,-1.001`, the 5101/5102 chamber boundary). Under Model D the flight has G=1 → `max(1, 0)` = **1 chamber**, but `test_staircase_counts_three_locks` (in `tests/graph/test_locks.py`) asserts `sum(d["locks"])==3` and `len(lock_edges)==3` — so without augmentation the staircase test breaks under the model you chose. The fixture was built around the older one-chamber-per-way model and is missing its boundary gates; add them so the fixture is physically honest.

Add **three** `waterway=lock_gate` nodes at the chamber boundaries the fixture is missing, for a total of **4 gate nodes** → G=4 → 3 chambers, distributed one per chamber downstream-gate segment:

```json
    {"type": "node", "id": 6004, "lat": 52.0000, "lon": -1.0000,
     "tags": {"waterway": "lock_gate"}},
    {"type": "node", "id": 6003, "lat": 52.0010, "lon": -1.0010,
     "tags": {"waterway": "lock_gate"}},
    {"type": "node", "id": 6005, "lat": 52.0020, "lon": -1.0020,
     "tags": {"waterway": "lock_gate"}},
    {"type": "node", "id": 6006, "lat": 52.0030, "lon": -1.0030,
     "tags": {"waterway": "lock_gate"}},
```

(6003 already exists in the fixture — keep it as-is; the three new ones are 6004 at `(52.000,-1.000)` = bottom entrance, 6005 at `(52.002,-1.002)` = chamber2/3 boundary, 6006 at `(52.003,-1.003)` = top exit.) The three lock ways (5101/5102/5103) each have 2 geometry points → 1 segment edge each, so the three chambers' downstream-gate segments are exactly those three edges → `sum(d["locks"])==3` and `len(lock_edges)==3` both stay green unchanged. NOTE: the fixture's lock ways have empty `node_ids` (Overpass `out geom` dev path); the gate nodes are matched by `gate_ids` (their `osm_id`) against the ways' `node_ids`, which are empty — so the flight is gateless **unless the ways gain node_ids referencing the gate node ids**. Give each staircase way a `nodes` array referencing its two endpoint gate ids so the gate-flight attribution can find them:

```json
    {"type": "way", "id": 5101,
     "nodes": [6004, 6003],
     "tags": {"waterway": "canal", "lock": "yes", "lock_name": "Staircase Bottom Lock", "lock:type": "staircase_lock", "name": "Test Canal"},
     "geometry": [{"lat": 52.0000, "lon": -1.0000}, {"lat": 52.0010, "lon": -1.0010}]},
    {"type": "way", "id": 5102,
     "nodes": [6003, 6005],
     "tags": {"waterway": "canal", "lock": "yes", "lock_name": "Staircase Middle Lock", "lock:type": "staircase_lock", "name": "Test Canal"},
     "geometry": [{"lat": 52.0010, "lon": -1.0010}, {"lat": 52.0020, "lon": -1.0020}]},
    {"type": "way", "id": 5103,
     "nodes": [6005, 6006],
     "tags": {"waterway": "canal", "lock": "yes", "lock_name": "Staircase Top Lock", "lock:type": "staircase_lock", "name": "Test Canal"},
     "geometry": [{"lat": 52.0020, "lon": -1.0020}, {"lat": 52.0030, "lon": -1.0030}]},
```

Ways 5101/5102 chain by shared id 6003; 5102/5103 by shared id 6005 — so the three ways form ONE flight (G=4 → 3 chambers), each chamber's downstream-gate segment is the single segment edge of that way → 3 lock edges, `sum(d["locks"])==3`. Keep the existing place nodes 6001/6002 and the lone gate 6003. Verify after Step 13 that `test_staircase_counts_three_locks`, `test_staircase_chambers_chain_into_one_component` (still 4 nodes, 3 edges, 1 component — the ways still share endpoints by coord, now also by shared id), and `test_staircase_lock_gate_counted_not_incrementing` (now `lock_gate_nodes == 4`, `sum==3`) all pass — `test_staircase_lock_gate_counted_not_incrementing`'s `assert report["lock_gate_nodes"] == 1` becomes `== 4`.

- [ ] **Step 7: Delete the untracked ad-hoc `scripts/` helpers**

```bash
git rm -f scripts/curate_snaps.py scripts/diagnose_england_build.py 2>/dev/null || rm -f scripts/curate_snaps.py scripts/diagnose_england_build.py
```

(They are untracked, so `git rm` will only work if they were ever tracked; `rm -f` is the fallback. They reference the now-deleted `tolerance_m`/`load_overrides` machinery and one carries a `B905` ruff lint; deleting them keeps `ruff check .` clean — see Task 4.)

- [ ] **Step 8: Rewrite `tests/graph/test_build.py` for the noded chain**

Replace `test_build_main_chain_and_pendant_have_five_edges` (rename + new counts) and leave the other five tests (they assert on `osm_way_id` edge attrs and `g.number_of_nodes`-style counts that still hold). The renamed test:

```python
def test_build_main_chain_and_pendant_counts_match_noded_model():
    g = build_graph(_features())
    # chain 1001(2 edges)->1002(1)->1003(1), pendant 1007(1) joins 1003 far-end
    # by shared id 3002, Duke's Cut 1006(1 edge) isolated.
    ids = {d["osm_way_id"] for _, _, d in g.edges(data=True)}
    assert ids == {1001, 1002, 1003, 1006, 1007}
    # main-chain+pendant component = 6 nodes (11,12,13,5003,3002,7002); Duke's = 2 -> 8 total
    assert g.number_of_nodes() == 8
    # 1001 yields 2 segment edges; 1002/1003/1006/1007 yield 1 each -> 6 total
    assert g.number_of_edges() == 6
```

`test_build_returns_networkx_graph`, `test_build_excludes_derelict_ways`, `test_build_edge_has_length_and_dims` (asserts on the 1002 edge, which is still one edge), `test_build_lock_way_edge_kind` (1003 edge kind LOCK, `locks==0` before `attach_locks`), and `test_build_tunnel_flag` (1006) all stay valid — verify by running them after Step 13.

- [ ] **Step 9: Rewrite `tests/graph/test_build_bulk.py` — delete phases, add noded tests + acceptance crit 5/6/7**

Keep the file's imports and the `_way`/`_features` helpers at the top (they build `WaterwayWay` directly — key-agnostic, survive Task 3). **Delete every existing test function** (the Phase 1/2/3/override/grid/snap/closed-ring-shared tests — all of them, including the `time`-based perf test and the `test_overlapping_snap_candidates_share_node` regression). Replace the whole test body (from the `# --- Phase 1` comment to end of file) with the noded tests below. Also drop the now-unused `nx`, `time`, `load_overrides` imports except `nx` (keep `import networkx as nx`; remove `from pound.graph.build import build_graph, load_overrides` → `from pound.graph.build import build_graph`; remove `import time`; remove `from pathlib import Path` if unused).

```python
import networkx as nx

from pound.graph.build import build_graph
from pound.ingest.ir import NodeKind, WaterwayFeatures, WaterwayKind, WaterwayNode, WaterwayWay, WayDimensions
from pound.graph.locks import attach_locks


def _way(oid, kind, name, nodes, geom, dims=None, tags=None):
    return WaterwayWay(
        osm_id=oid,
        kind=kind,
        name=name,
        tags=tags or {"waterway": kind.value},
        node_ids=nodes,
        geometry=geom,
        dimensions=dims or WayDimensions(),
    )


def _features(ways, nodes=None):
    return WaterwayFeatures(
        ways=ways,
        nodes=nodes or [],
        source="geofabrik",
        fetched_at="2026-06-25T00:00:00Z",
        bbox=None,
    )


# --- Noded emission: every OSM id -> node, consecutive ids -> edges --------

def test_noded_way_emits_per_segment_edges():
    # 3 node_ids, 3 coords -> 3 nodes, 2 segment edges (not 1 whole-way edge).
    ways = [_way(1, WaterwayKind.CANAL, "A", [11, 12, 13],
                 [(51.7500, -1.2600), (51.7510, -1.2610), (51.7520, -1.2620)])]
    g = build_graph(_features(ways))
    assert g.number_of_nodes() == 3
    assert g.number_of_edges() == 2
    # each segment edge carries the parent way's osm_way_id
    assert {d["osm_way_id"] for _, _, d in g.edges(data=True)} == {1}


def test_segment_edge_length_is_per_segment_not_whole_way():
    ways = [_way(1, WaterwayKind.CANAL, "A", [11, 12, 13],
                 [(51.7500, -1.2600), (51.7510, -1.2610), (51.7520, -1.2620)])]
    g = build_graph(_features(ways))
    seg = next(d for _, _, d in g.edges(data=True))
    # ~131 m per segment, NOT the ~262 m whole-way length.
    assert 120.0 < seg["length_m"] < 140.0


# --- Shared junctions collapse at emission (no contraction phase) ----------

def test_shared_osm_id_at_endpoint_joins_two_ways():
    ways = [
        _way(1, WaterwayKind.CANAL, "A", [1, 7], [(51.7500, -1.2600), (51.7520, -1.2620)]),
        _way(2, WaterwayKind.CANAL, "B", [7, 9], [(51.7520, -1.2620), (51.7540, -1.2640)]),
    ]
    g = build_graph(_features(ways))
    assert g.number_of_nodes() == 3
    assert g.number_of_edges() == 2
    assert nx.number_connected_components(g) == 1


def test_internal_junction_way_joins_main_chain_at_an_internal_node():
    """Acceptance crit 5: a way sharing an OSM id only at an INTERNAL position
    of another way joins it — the exact defect this rewrite fixes. Under the
    endpoint-only build, B's shared id sits in the middle of A (not at A's
    endpoints), so B becomes a detached single edge and the graph is two
    components; noding makes A's shared id a real graph node and B joins it."""
    ways = [
        _way(1, WaterwayKind.CANAL, "A", [1, 2, 3],
             [(51.7500, -1.2600), (51.7510, -1.2610), (51.7520, -1.2620)]),
        _way(2, WaterwayKind.CANAL, "B", [4, 2],  # node 2 is INTERNAL to A
             [(51.7600, -1.2700), (51.7510, -1.2610)]),
    ]
    g = build_graph(_features(ways))
    assert nx.number_connected_components(g) == 1
    # A has 3 nodes; B brings 1 new (id 4); the shared id 2 is one graph node of degree 3
    # (A's two segment edges + B's one edge).
    shared_node = next(n for n, d in g.nodes(data=True) if "2" in d.get("osm_node_ids", set()))
    assert g.degree(shared_node) == 3


def test_exact_coordinate_authority_joins_coincident_ends_without_node_ids():
    # id-less dev path (Overpass out geom): coincident rounded coords join.
    ways = [
        _way(1, WaterwayKind.CANAL, "A", [], [(51.7500, -1.2600), (51.7520, -1.2620)]),
        _way(2, WaterwayKind.CANAL, "B", [], [(51.7520, -1.2620), (51.7540, -1.2640)]),
    ]
    g = build_graph(_features(ways))
    assert nx.number_connected_components(g) == 1


def test_distinct_osm_ids_rounding_to_same_coord_collapse_to_one_node():
    # two ways that don't share an OSM node id but meet at the same rounded coord
    # become ONE graph node (coord authority); both ids land in osm_node_ids.
    ways = [
        _way(1, WaterwayKind.CANAL, "A", [1, 2], [(51.7500, -1.2600), (51.7520, -1.2620)]),
        _way(2, WaterwayKind.CANAL, "B", [3, 4], [(51.7540, -1.2640), (51.7520, -1.2620)]),
    ]
    g = build_graph(_features(ways))
    assert nx.number_connected_components(g) == 1
    shared = next(n for n, d in g.nodes(data=True)
                  if {"2", "4"} <= d.get("osm_node_ids", set()))
    assert g.nodes[shared]["osm_node_ids"] == {"2", "4"}


# --- Closed-ring skip (area polygons are never routable) -------------------

def test_closed_ring_way_emits_no_self_loop_and_no_isolated_node():
    from pound.validate.connectivity import validate_graph
    ring_geom = [
        (51.7500, -1.2600), (51.7510, -1.2600),
        (51.7510, -1.2610), (51.7500, -1.2600),  # == first -> closed ring
    ]
    ways = [_way(1, WaterwayKind.CANAL, "Basin", [1, 2, 3, 1], ring_geom)]
    g = build_graph(_features(ways))
    assert g.number_of_edges() == 0
    assert g.number_of_nodes() == 0
    v = validate_graph(g, {"orphan_lock_ways": [], "orphan_lock_nodes": []})
    assert v["self_loops"] == 0


def test_closed_ring_does_not_mask_a_real_routable_cycle():
    a, b, c = (51.7500, -1.2600), (51.7520, -1.2600), (51.7510, -1.2620)
    ways = [
        _way(10, WaterwayKind.CANAL, "AB", [1, 2], [a, b]),
        _way(20, WaterwayKind.CANAL, "BC", [2, 3], [b, c]),
        _way(30, WaterwayKind.CANAL, "CA", [3, 1], [c, a]),
    ]
    g = build_graph(_features(ways))
    assert g.number_of_edges() == 3
    assert nx.number_connected_components(g) == 1
    assert all(u != v for u, v in g.edges())


def test_consecutive_duplicate_id_or_coord_segment_is_skipped():
    # a way that references the same OSM id twice in a row (or two coords that
    # round equal) would yield a zero-length self-loop; dedupe-then-iterate.
    ways = [_way(1, WaterwayKind.CANAL, "A", [1, 1, 2],
                 [(51.7500, -1.2600), (51.7500, -1.2600), (51.7520, -1.2620)])]
    g = build_graph(_features(ways))
    assert g.number_of_edges() == 1
    assert all(u != v for u, v in g.edges())


# --- Edge collision: merge attrs (§3.3) — acceptance crit 6 ----------------

def test_coincident_lock_and_canal_ways_merge_to_one_lock_edge():
    """Acceptance crit 6: a lock-tagged edge coincident with a canal-tagged edge
    resolves to one edge with kind==LOCK, the LOCK way's osm_way_id kept (so
    attach_locks finds it), and locks==1 both at build (§3.3 merge sets it) and
    after attach_locks."""
    # routable ways sort before locks in read_pbf/parse, but the merge is
    # order-independent; mirror the measured case (canal emissible first).
    ways = [
        _way(100, WaterwayKind.CANAL, "Canal", [1, 2],
             [(51.7500, -1.2600), (51.7520, -1.2620)]),
        _way(200, WaterwayKind.LOCK, "Lock", [1, 2],
             [(51.7500, -1.2600), (51.7520, -1.2620)]),
    ]
    g = build_graph(_features(ways))
    assert g.number_of_edges() == 1
    e = next(d for _, _, d in g.edges(data=True))
    assert e["kind"] == WaterwayKind.LOCK
    assert e["osm_way_id"] == 200  # LOCK way's id kept
    assert e["locks"] == 1  # set at merge (one party LOCK)
    # after attach_locks (deep copy), the way-loop finds osm_way_id==200 -> locks=1
    g2, _ = attach_locks(g, _features(ways))
    e2 = next(d for _, _, d in g2.edges(data=True))
    assert e2["locks"] == 1


def test_coincident_river_and_canal_merge_prefers_canal():
    ways = [
        _way(300, WaterwayKind.RIVER, "R", [1, 2], [(51.7500, -1.2600), (51.7520, -1.2620)]),
        _way(400, WaterwayKind.CANAL, "C", [1, 2], [(51.7500, -1.2600), (51.7520, -1.2620)]),
    ]
    g = build_graph(_features(ways))
    assert g.number_of_edges() == 1
    e = next(d for _, _, d in g.edges(data=True))
    assert e["kind"] == WaterwayKind.CANAL  # Calder-and-Hebble dual-classification


def test_collision_union_tightens_dimensions():
    ways = [
        _way(500, WaterwayKind.CANAL, "C", [1, 2],
             [(51.7500, -1.2600), (51.7520, -1.2620)],
             dims=WayDimensions(max_beam_m=2.0, max_draft_m=0.8)),
        _way(501, WaterwayKind.CANAL, "C2", [1, 2],
             [(51.7500, -1.2600), (51.7520, -1.2620)],
             dims=WayDimensions(max_beam_m=2.2, max_draft_m=None, max_length_m=18.0)),
    ]
    g = build_graph(_features(ways))
    d = g.edges[next(iter(g.edges))]["dimensions"]
    assert d.max_beam_m == 2.0   # min
    assert d.max_draft_m == 0.8  # carried from the other way
    assert d.max_length_m == 18.0


# --- attach_locks flight-level chamber model (§3.5, OQ-A Model D) --------

def test_multi_node_lock_way_counts_chambers_by_gates():
    """A multi-node LOCK way with internal gate nodes: chambers = gates-1, set
    on the downstream-gate segments, not on every segment (Model B) and not on
    the first segment only (Model A). A 4-node, 3-gate way (gate-shape-gate-
    gate) => 2 chambers on the two downstream-gate segments; the shape-to-first-
    gate segment carries 0."""
    # nodes 1(gate), 2(shape), 3(gate), 4(gate). Segment 2->3 has downstream
    # node 3 (a gate) => 1 chamber; segment 3->4 has downstream 4 (gate) =>
    # 1 chamber. Total 2.
    ways = [_way(700, WaterwayKind.LOCK, "L", [1, 2, 3, 4],
                 [(51.7500, -1.2600), (51.7510, -1.2610),
                  (51.7520, -1.2620), (51.7530, -1.2630)])]
    gates = [WaterwayNode(osm_id=1, lat=51.7500, lon=-1.2600, tags={"waterway": "lock_gate"}, kind=NodeKind.LOCK_GATE),
             WaterwayNode(osm_id=3, lat=51.7520, lon=-1.2620, tags={"waterway": "lock_gate"}, kind=NodeKind.LOCK_GATE),
             WaterwayNode(osm_id=4, lat=51.7530, lon=-1.2630, tags={"waterway": "lock_gate"}, kind=NodeKind.LOCK_GATE)]
    feats = _features(ways, gates)
    g, _ = attach_locks(build_graph(feats), feats)
    assert sum(d.get("locks", 0) for _, _, d in g.edges(data=True)) == 2
    assert sum(1 for _, _, d in g.edges(data=True) if d.get("locks", 0) >= 1) == 2


def test_three_lock_gates_in_a_row_yields_two_chambers():
    """Kurt's prescription: three lock gates in a row => two chambers. A
    3-node way gate-gate-gate (G=3) => 2 chambers; both segments' downstream
    # nodes are gates => 2 lock edges."""
    ways = [_way(701, WaterwayKind.LOCK, "L", [10, 11, 12],
                 [(51.7500, -1.2600), (51.7510, -1.2610), (51.7520, -1.2620)])]
    gates = [WaterwayNode(osm_id=10, lat=51.7500, lon=-1.2600, tags={"waterway": "lock_gate"}, kind=NodeKind.LOCK_GATE),
             WaterwayNode(osm_id=11, lat=51.7510, lon=-1.2610, tags={"waterway": "lock_gate"}, kind=NodeKind.LOCK_GATE),
             WaterwayNode(osm_id=12, lat=51.7520, lon=-1.2620, tags={"waterway": "lock_gate"}, kind=NodeKind.LOCK_GATE)]
    feats = _features(ways, gates)
    g, report = attach_locks(build_graph(feats), feats)
    assert sum(d.get("locks", 0) for _, _, d in g.edges(data=True)) == 2
    assert report["lock_ways_attached"] == 1


def test_flight_level_shared_gate_counted_once():
    """Two LOCK ways sharing a gate endpoint (one chamber's exit IS the next's
    entrance — the cross-way staircase case): the shared gate bounds both
    chambers once, not twice. Two 2-node ways [1,2] and [2,3] where node 2 is a
    gate: G=3 (gates 1,2,3) => 2 chambers across the flight; each way's single
    segment has a downstream gate => 2 lock edges, not 3."""
    ways = [
        _way(800, WaterwayKind.LOCK, "Lower", [1, 2],
             [(51.7500, -1.2600), (51.7510, -1.2610)]),
        _way(801, WaterwayKind.LOCK, "Upper", [2, 3],
             [(51.7510, -1.2610), (51.7520, -1.2620)]),
    ]
    gates = [WaterwayNode(osm_id=1, lat=51.7500, lon=-1.2600, tags={"waterway": "lock_gate"}, kind=NodeKind.LOCK_GATE),
             WaterwayNode(osm_id=2, lat=51.7510, lon=-1.2610, tags={"waterway": "lock_gate"}, kind=NodeKind.LOCK_GATE),
             WaterwayNode(osm_id=3, lat=51.7520, lon=-1.2620, tags={"waterway": "lock_gate"}, kind=NodeKind.LOCK_GATE)]
    feats = _features(ways, gates)
    g, _ = attach_locks(build_graph(feats), feats)
    # G=3 distinct gates across the flight => 2 chambers => 2 lock edges, not 3
    # (the shared gate 2 is counted once, not by each way).
    assert sum(d.get("locks", 0) for _, _, d in g.edges(data=True)) == 2
    assert sum(1 for _, _, d in g.edges(data=True) if d.get("locks", 0) >= 1) == 2


def test_gateless_flight_floors_to_one_lock():
    """The gateless-flight floor (the 244 gateless flights in England): a LOCK
    way whose gates aren't mapped gets locks=1 on its first segment, not 0."""
    ways = [_way(900, WaterwayKind.LOCK, "L", [1, 2],
                 [(51.7500, -1.2600), (51.7520, -1.2620)])]
    feats = _features(ways, [])  # no gate nodes
    g, report = attach_locks(build_graph(feats), feats)
    assert sum(d.get("locks", 0) for _, _, d in g.edges(data=True)) == 1
    assert report["lock_ways_attached"] == 1


# --- attach_locks lock-node tie-break (§3.5) — acceptance crit 7 ----------

def test_lock_node_tie_goes_to_lock_edge_not_canal_spur():
    """Acceptance crit 7: a lock=yes gate node coincident with BOTH a LOCK
    segment and a canal spur (sharing the junction node) gets locks=1 on the
    LOCK segment and leaves the spur at 0, deterministically (not by emission
    order)."""
    ways = [
        _way(100, WaterwayKind.LOCK, "Lock", [1, 2],
             [(51.7500, -1.2600), (51.7520, -1.2620)]),
        _way(200, WaterwayKind.CANAL, "Spur", [2, 3],
             [(51.7520, -1.2620), (51.7540, -1.2640)]),  # shares node 2 with the lock
    ]
    nodes = [WaterwayNode(osm_id=999, lat=51.7520, lon=-1.2620,
                          tags={"lock": "yes"}, kind=NodeKind.LOCK)]
    feats = _features(ways, nodes)
    g, report = attach_locks(build_graph(feats), feats)
    lock_e = next(d for _, _, d in g.edges(data=True) if d["osm_way_id"] == 100)
    spur_e = next(d for _, _, d in g.edges(data=True) if d["osm_way_id"] == 200)
    assert lock_e["locks"] == 1
    assert spur_e["locks"] == 0
    assert report["lock_nodes_attached"] >= 1
```

- [ ] **Step 10: Update `tests/graph/test_locks.py` — widen `test_non_lock_edges_have_zero_locks` to cover edge 1007**

Replace its body:

```python
def test_non_lock_edges_have_zero_locks():
    g, _ = attach_locks(build_graph(_oxford()), _oxford())
    for _, _, d in g.edges(data=True):
        if d["osm_way_id"] in (1001, 1002, 1006, 1007):
            assert d["locks"] == 0
```

(The spur-contention regression this now catches: lock node 2002 sits on the shared node `3002` incident to both the LOCK edge 1003 and the canal spur 1007; only the LOCK edge should get `locks=1`. Widening to 1007 makes a spur spuriously getting `locks=1` fail this test.)

Also in `tests/graph/test_locks.py`, rewrite `test_staircase_lock_gate_counted_not_incrementing` for the Step 6b fixture augmentation — its old comment ("the gate sits at the chamber-1/chamber-2 junction; neither edge gets +1") and `assert report["lock_gate_nodes"] == 1` no longer hold under Model D (the gates now DRIVE the chamber attribution; 4 gates → 3 lock edges, each chamber's downstream-gate segment gets +1). New body:

```python
def test_staircase_lock_gate_counted_not_incrementing():
    features = _staircase()
    g, report = attach_locks(build_graph(features), features)
    # 4 gate nodes now (6004 bottom entrance, 6003 chamber1/2 boundary, 6005
    # chamber2/3 boundary, 6006 top exit) — the Step 6b augmentation. They drive
    # the flight's chamber count (G=4 -> 3 chambers), one lock per chamber's
    # downstream-gate segment; gates themselves still don't increment beyond
    # that (no double-counting).
    assert report["lock_gate_nodes"] == 4
    assert sum(d["locks"] for _, _, d in g.edges(data=True)) == 3
```

`test_staircase_counts_three_locks` (`sum==3`, `len(lock_edges)==3`) and `test_staircase_chambers_chain_into_one_component` (`number_of_nodes==4`, `number_of_edges==3`, one component — the ways share endpoints by shared id 6003/6005, 4 distinct nodes {6003,6004,6005,6006}) stay valid unchanged — verify after Step 13.

- [ ] **Step 11: Update `tests/validate/test_connectivity.py` — re-derive counts + drop snap-key asserts**

Apply these edits:

1. `test_component_count_is_two`: change `assert v["largest_component_size"] == 5` to `== 6` (main chain+pendant component now has 6 nodes: `11,12,13,5003,3002,7002`; Duke's Cut stays the 2nd component, so `component_count` stays 2). The `assert v["component_count"] == 2` line stays.
2. `test_missing_dims_count`: change `assert v["edges_missing_dims"] == 4` to `== 5` (1001 has no dims and now yields TWO dimless segment-edges; 1003/1006/1007 each yield one — `2+1+1+1 == 5`). Update the comment to `# 1001(x2 no dims), 1003, 1006, 1007 have no dims; 1002 does`.
3. `test_totals_present`: change `v["total_edges"] == 5` → `== 6`; `v["total_nodes"] == 7` → `== 8`.
4. `test_report_has_bulk_connectivity_keys`: replace the key loop with only the surviving keys:

```python
def test_report_has_bulk_connectivity_keys():
    g, report = _graph_and_report()
    v = validate_graph(g, report)
    for k in (
        "place_nodes_seen",
        "place_nodes_in_gazetteer",
        "named_nodes_in_graph",
        "ambiguous_place_names",
    ):
        assert k in v
    # removed snap/override keys are absent
    for k in ("tolerance_snaps_used", "tolerance_snaps_unresolved", "overrides_applied"):
        assert k not in v
```

1. `test_report_defaults_when_graph_has_no_bulk_attrs`: drop the snap/override assertions, keep the surviving-key defaults. (The `g.add_node((51.7, -1.2), lat=51.7, lon=-1.2)` line stays valid under coordinate keys in this stage — Task 3 rewrites it to a uid key.) Replace its body:

```python
def test_report_defaults_when_graph_has_no_bulk_attrs():
    # A plain graph (no graph.graph bulk keys) still validates.
    import networkx as nx

    g = nx.Graph()
    g.add_node((51.7, -1.2), lat=51.7, lon=-1.2)
    v = validate_graph(g, {"orphan_lock_ways": [], "orphan_lock_nodes": []})
    assert v["place_nodes_seen"] == 0
    assert v["place_nodes_in_gazetteer"] == 0
    assert v["named_nodes_in_graph"] == 0
    assert v["ambiguous_place_names"] == []
    # removed snap/override keys are absent
    for k in ("tolerance_snaps_used", "tolerance_snaps_unresolved", "overrides_applied"):
        assert k not in v
```

(The other tests — `test_no_derelict_edges`, `test_no_zero_length_or_self_loops`, `test_orphans_carry_through` — stay valid unchanged.)

- [ ] **Step 12: Update `tests/ingest/test_cli.py` + `tests/ingest/test_pipeline_integration.py`**

`test_cli.py`:

- `test_build_subcommand_writes_artifact`: passes `["build", "oxford", "--out", ...]` with no removed flags — already valid, leave it.
- `test_build_england_writes_artifact_and_passes_gate`: remove the `"--tolerance-m", "10"` and `"--max-unresolved-snaps", "10"` and `"--overrides", ...` arg list items (the call becomes `["build", "england", "--out", str(out)]`). Keep the rest of the assertions (`rc == 0`, `out.exists()`, validation/gazetteer present). The name stays; the gate it now passes is the derelict/self_loops gate.
- `test_build_england_fails_when_unresolved_exceeds_threshold`: **delete** — there is no snap gate to fire.

`test_pipeline_integration.py`:

- `test_build_oxford_artifact_has_connected_graph_and_gazetteer`: change `cli.main(["build", "oxford", "--out", str(out), "--max-unresolved-snaps", "0"])` to `cli.main(["build", "oxford", "--out", str(out)])`. Delete `assert len(v["tolerance_snaps_unresolved"]) == 0` and `assert v["tolerance_snaps_used"]`. Keep the `derelict_edges == 0`, `self_loops == 0`, gazetteer, `named_nodes_in_graph >= 2` (relies on Task 2's coordinate-key `attach_node_names`, still working), and `place_nodes_in_gazetteer >= 3` assertions.
- `test_build_oxford_gate_fails_when_pendant_left_unresolved`: **delete** — the pendant now joins for free under noding (no gate to fire).

- [ ] **Step 13: Update `tests/route/test_plan_route.py` — `_long_plan` 3-edge → 4-edge, raise `days=3 → 4`**

Under noding, way 1001 contributes **2** segment edges (Oxford→mid→Hayfield-junction-predecessor); the Oxford→Hayfield path is ways `1001→1002→1003` = `2 + 1 + 1 = 4` edges, not 3. Keep the existing ~13 km / ~162 min scaling (recommended strategy in the spec): each edge still exceeds half a 180-min budget, so one edge per day.

1. In `_long_plan`, raise the `days` plumbing: the helper takes `days` as a param, so update the **call sites** rather than the helper. But the docstring must be fully rewritten (not s/3/4/):

```python
def _long_plan(days: int, hours_per_day: float):
    """Synthetic long route: scale the Oxford edge lengths so the 4-edge path
    needs multiple days. Tests the chunking ALGORITHM, not Oxford data.

    Under the noded build, way 1001 (3 geometry points) becomes 2 segment
    edges, so the Oxford->Hayfield path (ways 1001->1002->1003) is 4 edges:
    2 (1001) + 1 (1002) + 1 (1003). We scale every edge to ~13 km (~162 min
    at CRUISE_KMH=4.8) so each edge comfortably exceeds half a 3-hour (180-min)
    budget; greedy chunking then emits one edge per day, so the route needs 4
    days and the test asserts 4-day chunking across 4 edges.
    """
    import copy

    with open(oxford_fixture_path()) as f:
        raw = json.load(f)
    features = parse(raw["elements"], None, osm_timestamp=raw["osm3s"]["timestamp_osm_base"])
    g, _ = attach_locks(build_graph(features), features)
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0  # ~13 km -> ~162 min/edge
    constraints = CanalConstraints(
        start="Oxford", end="Hayfield", days=days, hours_per_day=hours_per_day
    )
    return plan_route(constraints, _graph=g, _features=features)
```

1. Update the call sites and assertions (the `days=` arg is the `max_days` cap — it must be >= the number of days the route needs, so the cap does not fold the last day over budget):

```python
def test_multiday_splits_legs_within_budget():
    # 4 edges ~162 min each; hours_per_day=3 -> 180 min budget.
    # Greedy: day1=162, day2=162, day3=162, day4=162 (each +next would exceed 180).
    r = _long_plan(days=4, hours_per_day=3.0)
    assert len(r.days) == 4
    for day in r.days:
        assert day.cruising_minutes <= 3.0 * 60
        assert day.legs  # non-empty (OQ-8: no padding)


def test_days_partition_legs_exactly():
    r = _long_plan(days=4, hours_per_day=3.0)
    flat = [leg for day in r.days for leg in day.legs]
    assert flat == r.legs


def test_days_not_padded_beyond_route():
    # OQ-8: days=5 but route needs only 4 -> emit 4, NOT 5 with empty trailers.
    r = _long_plan(days=5, hours_per_day=3.0)
    assert len(r.days) == 4
    assert all(day.legs for day in r.days)


def test_days_count_never_exceeds_constraints_days():
    # days=2 caps at 2; the 4 edges fold into 2 days (overflow lands in day 2).
    r = _long_plan(days=2, hours_per_day=3.0)
    assert len(r.days) <= 2


def test_day_index_sequential():
    r = _long_plan(days=4, hours_per_day=3.0)
    assert [d.day for d in r.days] == [1, 2, 3, 4]
```

(The non-`_long_plan` tests — `test_route_connects_oxford_to_hayfield`, `test_totals_equal_sum_of_legs`, `test_per_leg_minutes_match_cost_formula`, `test_total_minutes_matches_time_min_over_edges`, `test_locks_counted_on_lock_edge` (still 1 lock on the 1003 edge), `test_warnings_flag_unknown_dims`, `test_graph_source_date_from_metadata`, `test_ring_raises_not_implemented`, `test_single_day_plan_wraps_legs` — assert on `r.legs`/`r.days` structure and `total_*` sums that recompute from the graph; they survive the re-derivation because `total_minutes`/`total_locks` are recomputed over the now-4-leg path. Verify after Step 14.)

- [ ] **Step 14: Run the full suite green**

Run: `pytest -q`

Expected: PASS. If any test still references `tolerance_m`/`tolerance_snaps_*`/`load_overrides`/`_contract`/`--max-unresolved-snaps`/`--overrides`/`--tolerance-m` or `g.graph["tolerance_snaps_used"]`, grep for it and remove the last reference:

```bash
rg -n "tolerance_m|tolerance_snaps|load_overrides|_contract|max-unresolved-snaps|--overrides|--tolerance-m|overrides_applied" pound/ tests/
```

Expected after fixes: no matches in `pound/`; only `tests/` matches are the surviving-key-absence assertions added in Step 11 (which assert the keys are `not in v`). Re-run `pytest -q` until green.

- [ ] **Step 15: Run ruff**

Run: `ruff check .`

Expected: clean (the deleted `scripts/` carried the only `B905`). Fix any unused-import findings from the `load_overrides`/`_contract` removal.

- [ ] **Step 16: Commit**

```bash
git add pound/graph/build.py pound/graph/locks.py pound/validate/connectivity.py pound/ingest/cli.py pound/route/plan.py tests/fixtures/oxford_overpass_sample.json tests/graph/test_build.py tests/graph/test_build_bulk.py tests/graph/test_locks.py tests/validate/test_connectivity.py tests/ingest/test_cli.py tests/ingest/test_pipeline_integration.py tests/route/test_plan_route.py .gitignore
git rm -f pound/data/overrides.json 2>/dev/null || rm -f pound/data/overrides.json
git add -A
git commit -m "refactor(build): rewrite build_graph as noded (coord keys), drop phases/snap/overrides, migrate fixture + coupled tests"
```

---

### Task 3 (Stage B): Internal-uid graph node-key migration + consumer migrations

**Files:**

- Modify: `pound/graph/build.py` (`_resolve_or_create` mints a uid counter; node attrs `lat`/`lon`/`osm_node_ids`; indexes map to uid)
- Modify: `pound/graph/gazetteer.py` (`attach_node_names` body rewrite: read `lat`/`lon` attrs instead of comparing the key)
- Modify: `pound/route/plan.py` (delete `snap_place` import; inline attribute-based `_resolve`; `_name_for` takes `graph`, reads attrs)
- Modify: `tests/graph/test_gazetteer.py` (coord-key node lookup → uid-based lookup)
- Modify: `tests/validate/test_connectivity.py` (`test_report_defaults_when_graph_has_no_bulk_attrs` coord-key `add_node` → uid-key)
- Delete: `pound/route/snap.py`, `tests/route/test_snap.py`

**Interfaces:**

- Consumes: noded `build_graph` from Task 2 (coordinate keys); this task replaces the key type only.
- Produces: graph node keys are synthetic **internal uids** (a monotonic `itertools.count()` int). `g.nodes[uid]["lat"]`/`["lon"]`/`["osm_node_ids"]`. `build_gazetteer` still returns `dict[str, coord | list[coord]]` (a *dict*, not the graph — unaffected by the graph key change). `plan_route`'s prod path stays `RuntimeError` (not wired); the test path resolves places by matching a node's rounded `lat`/`lon` to the place's coord.

- [ ] **Step 1: Switch `build_graph` to internal-uid keys**

In `pound/graph/build.py`, add `import itertools` at the top. In `build_graph`, change the two indexes to be keyed by an internal uid counter, and rewrite `_resolve_or_create` to mint uids and store `lat`/`lon` as attrs. Replace the top of `build_graph` and `_resolve_or_create`:

```python
def build_graph(features: WaterwayFeatures) -> nx.Graph:
    """Build a noded graph from WaterwayFeatures keyed by synthetic internal uids.

    Every OSM node id on a routable way is a graph node keyed by a monotonic
    internal id (source-agnostic: survives OSM-id aliasing at one coord and
    future synthetic curator nodes). lat/lon and osm_node_ids are node attrs.
    Junctions collapse at emission via the osm-id and coordinate indexes.
    """
    g = nx.Graph()
    uid_counter = itertools.count()
    osm_idx: dict[str, int] = {}      # str(osm id) -> uid
    coord_idx: dict[tuple, int] = {}  # rounded coord -> uid

    def _resolve_or_create(osm_id, lat, lon):
        sid = str(osm_id) if osm_id is not None else None
        coord = _node_key(lat, lon)
        uid = None
        if sid is not None and sid in osm_idx:
            uid = osm_idx[sid]
        if uid is None and coord in coord_idx:
            uid = coord_idx[coord]
        if uid is None:
            uid = next(uid_counter)
            g.add_node(uid, lat=coord[0], lon=coord[1], osm_node_ids=set())
            coord_idx[coord] = uid
        if sid is not None:
            osm_idx[sid] = uid
            coord_idx.setdefault(coord, uid)
            g.nodes[uid]["osm_node_ids"].add(sid)
        return uid
```

The rest of `build_graph` (the way loop, `_merge_edge`, closed-ring skip, segment emission) is unchanged — it already operates on the keys returned by `_resolve_or_create` and the edge/attr payloads are key-agnostic. No other edit to `build.py` (`_merge_edge`, `_merge_dims`, `_min_nonnone`, `_node_key`, `_haversine_m`, `_KIND_RANK` unchanged). Note `coord === key` no longer holds (the module docstring's "Node keys are rounded (lat, lon) tuples in this stage" line should be updated to "Node keys are synthetic internal uids").

Update the module docstring's third paragraph from "Node keys are rounded (lat, lon) tuples in this stage" to "Node keys are synthetic internal uids (a monotonic counter); lat/lon and osm_node_ids (set of stringified OSM ids) are node attributes. id-less dev ways (Overpass `out geom`) resolve-or-create via the coordinate index alone."

- [ ] **Step 2: Rewrite `attach_node_names` body to read lat/lon attrs**

In `pound/graph/gazetteer.py`, the current `attach_node_names` does `for key in graph.nodes(): if key in place_coords ...` — under uids the key is never a coord, so the membership test is always `False` and zero names attach. Rewrite the loop to read each node's `lat`/`lon` attrs, round via `_node_key`, and look that up in `place_coords`:

```python
def attach_node_names(graph: nx.Graph, features: WaterwayFeatures) -> int:
    """Set `name` on graph nodes coincident with a named place node. Returns count.

    Matches by rounded coordinate: the place dict is keyed by _node_key(lat,lon)
    (a *dict*, not the graph); each graph node is keyed by internal uid but
    carries lat/lon attrs, so the match reads the attrs rather than the key.
    """
    place_coords: dict[tuple[float, float], str] = {}
    for n in features.nodes:
        if n.kind != NodeKind.PLACE:
            continue
        name = n.tags.get("name")
        if name:
            place_coords[_node_key(n.lat, n.lon)] = name
    count = 0
    for uid, nd in graph.nodes(data=True):
        coord = _node_key(nd["lat"], nd["lon"])
        if coord in place_coords and "name" not in nd:
            nd["name"] = place_coords[coord]
            count += 1
    return count
```

(`build_gazetteer` and `ambiguous_place_names` are unchanged — they return a coord-keyed dict, not the graph.)

- [ ] **Step 3: Migrate `plan.py` off `snap_place` and onto attribute-based resolve + `_name_for(graph)`**

In `pound/route/plan.py`:

1. Replace the imports:

```python
from pound.graph.gazetteer import build_gazetteer
from pound.graph.build import _node_key
```

Remove the `from pound.route.snap import snap_place` import entirely (the module is deleted in Step 5).

1. Replace the `start_node = snap_place(...)` / `end_node = snap_place(...)` lines with an inline attribute-based resolve:

```python
    graph, features = _graph, _features
    gaz = build_gazetteer(features)
    start_node = _resolve_place(constraints.start, gaz, graph)
    end_node = _resolve_place(constraints.end, gaz, graph)
```

and add the helper (private, designed for the hermetic test path; the production artifact-loading path still raises `RuntimeError` before reaching it):

```python
def _resolve_place(name: str, gaz: dict, graph: nx.Graph) -> int:
    """Resolve a place name to a graph node uid by rounded-coordinate match.

    Interim implementation: build_gazetteer returns name -> rounded coord (or a
    list of coords for ambiguous names). The graph is keyed by internal uids, so
    we match by reading each node's lat/lon attrs. Ambiguous names raise (PR2's
    OfflineResolver owns the real ambiguous-name handling); an unresolved name
    raises. O(|nodes|) per call — acceptable on the fixture-scale test path;
    the production path raises RuntimeError before reaching this.
    """
    if name not in gaz:
        raise ValueError(f"unknown place: {name!r}")
    coord = gaz[name]
    if isinstance(coord, list):
        raise ValueError(f"ambiguous place: {name!r} (PR2 resolve_place owns handling)")
    for uid, nd in graph.nodes(data=True):
        if _node_key(nd["lat"], nd["lon"]) == coord:
            return uid
    raise ValueError(f"place {name!r} snaps to a node not in the graph")
```

1. Rewrite `_name_for` to take the graph and read attrs (the call sites update from `_name_for(u, features, gaz)` to `_name_for(u, graph, gaz)`):

```python
def _name_for(node_uid, graph, gazetteer) -> str:
    """Reverse-lookup a node uid to a place name via its rounded coord;
    fall back to a coordinate string. The gazetteer is name -> coord (or list);
    ambiguous (list-valued) entries never match a coord string and fall through
    to the fallback (the documented interim regression; PR2 owns ambiguity)."""
    coord = _node_key(graph.nodes[node_uid]["lat"], graph.nodes[node_uid]["lon"])
    for name, key in gazetteer.items():
        if not isinstance(key, list) and key == coord:
            return name
    return f"{coord[0]},{coord[1]}"
```

1. Update the two `_name_for` call sites in the leg-assembly loop:

```python
            RouteLeg(
                from_place=_name_for(u, graph, gaz),
                to_place=_name_for(v, graph, gaz),
                ...
```

Remove the now-unused `from pound.ingest.ir import WaterwayFeatures` import only if it becomes unused — it is still used in the `plan_route` signature (`_features: WaterwayFeatures | None`), so keep it. `_node_key` is newly imported from `graph.build` (Step 3.1) — confirm it's used in `_resolve_place` and `_name_for` (it is).

- [ ] **Step 4: Update `tests/validate/test_connectivity.py::test_report_defaults_when_graph_has_no_bulk_attrs` for uid keys**

The `g.add_node((51.7, -1.2), lat=51.7, lon=-1.2)` line now needs the `lat`/`lon` attrs to be present (validate_graph reads `data["name"]` defensively, not `lat`/`lon`, so any key works — but under uids the key should be a plain int). Replace that line with:

```python
    g = nx.Graph()
    g.add_node(0, lat=51.7, lon=-1.2)
```

(`validate_graph` iterates `graph.nodes(data=True)` and only checks `"name" in data`, so the int key is fine; the `lat`/`lon` attrs are irrelevant to validate but kept for realism.)

- [ ] **Step 5: Migrate `tests/graph/test_gazetteer.py` coord-key node lookups to uid-based**

`test_gazetteer_unambiguous_name_maps_to_single_key` and `test_gazetteer_duplicate_name_maps_to_list_of_candidates` only assert on `build_gazetteer(feats)` and `ambiguous_place_names(gaz)` — both still return coord-keyed lists/tuples, unchanged. Leave them.

`test_attach_node_names_sets_name_on_coincident_graph_nodes` does a coord-key node lookup that no longer works. Replace its tail:

```python
def test_attach_node_names_sets_name_on_coincident_graph_nodes():
    feats = WaterwayFeatures(
        ways=[_way(1, [10, 11], [(51.75, -1.26), (51.76, -1.27)])],
        nodes=[_place(100, "Oxford", 51.75, -1.26)],  # coincides with way end
        source="geofabrik",
        fetched_at="t",
        bbox=None,
    )
    g = build_graph(feats)
    n = attach_node_names(g, feats)
    assert n == 1
    oxford_uid = next(
        uid for uid, nd in g.nodes(data=True)
        if _node_key(nd["lat"], nd["lon"]) == _node_key(51.75, -1.26)
    )
    assert g.nodes[oxford_uid].get("name") == "Oxford"
```

`test_attach_node_names_skips_non_coincident_place` only asserts `n == 0` (a place not on the way attaches no name) — leave it.

- [ ] **Step 6: Delete `route/snap.py` and `tests/route/test_snap.py`**

```bash
git rm pound/route/snap.py tests/route/test_snap.py
```

(`snap_place` does a coordinate-tuple graph-node lookup that violates criterion 4 and breaks under uids; its `build_gazetteer` was a stale non-list-aware duplicate of `graph/gazetteer.py`'s. PR2 builds `route/resolve.py` fresh; nothing imports `route/snap` after Step 3.)

- [ ] **Step 7: Run the full suite green**

Run: `pytest -q`

Expected: PASS. The `_name_for` ambiguous-name interim regression is asserted indirectly by `test_route_connects_oxford_to_hayfield` → `r.legs[i].to_place == r.legs[i+1].from_place` (Oxford/Hayfield/Marston are unambiguous on the fixture, so they resolve; the fallback never fires for them).

- [ ] **Step 8: Run ruff**

Run: `ruff check .`

Expected: clean. Fix any unused import (e.g. `WaterwayFeatures` if it were unused, or `_node_key` if imported twice).

- [ ] **Step 9: Commit**

```bash
git add pound/graph/build.py pound/graph/gazetteer.py pound/route/plan.py tests/validate/test_connectivity.py tests/graph/test_gazetteer.py
git commit -m "refactor(build): switch graph node keys to synthetic internal uids; migrate attach_node_names/plan/test consumers"
```

---

### Task 4: Bulk England verification (human-gated, acceptance crit 1)

**Files:** none modified — this is an end-to-end verification run against the real England PBF, not a CI test. Requires `pound/data/england.osm.pbf` (~1.5 GB, manual prerequisite) and `osmium-tool` + `pyosmium` (`uv sync --extra bulk`).

**Interfaces:**

- Consumes: the noded build from Tasks 1–3.
- Produces: a `/tmp/england.pkl` artifact and a printed validation report; no committed code.

- [ ] **Step 1: Build england and inspect the report**

Run:

```bash
time pound-ingest build england --out "$(mktemp -t england_XXXX.pkl)"
```

(The build prints the validation report JSON to stdout.) **Expected outcomes:**

- Exit code 0 (gate green): `derelict_edges == 0`, `self_loops == 0`.
- `total_edges` / `total_nodes` in the hundreds-of-thousands (noded graph, not the ~endpoint-only count).
- `component_count` ≤ ~1,669 ± noise (the reconstruction measurement; genuine geographic isolation for Devon/Cornwall, the Exe, Severn-tributary sub-networks).
- `largest_component_size` ≥ ~240,000 (the Midlands canal network joined up — reconstruction measured 240,902 nodes spanning N54.19°–S51.08°, W3.19°–E0.99°).
- Wall time ≤ ~2 min (perf preserved without the grid-bucket snap index).

If any of these fail wide, **stop and report** — do not tune knobs (there are no knobs now); a wrong component count vs the reconstruction means the noded emission misjoined something and is a build bug to debug with the systematic-debugging skill, not a tolerance dial.

- [ ] **Step 2 (only if the build fails): debug systematically**

If `self_loops > 0`: a way whose first/last OSM ids differ but whose first/last rounded coords are equal is being treated as a closed ring and skipped (good) — the remaining self-loops come from a len-2 way whose two ids resolve to the same uid (should be skipped by the `u == v` guard). Confirm the `u == v` guard fires on the segment loop, not just on whole-way endpoints.

If `component_count` is far above ~1,669: a shared-junction authority regressed. Re-check `_resolve_or_create` checks BOTH `osm_idx` and `coord_idx` and unions them when they disagree.

Record findings in `docs/testing/2026-07-03-pound-noded-build-verification.md` (or note them in STATUS.md) if anything is off; otherwise proceed to Task 4.

- [ ] **Step 3: Verify acceptance criteria 1 and 5 hold against the real graph**

Reload the artifact and assert the giant component and the internal-junction join:

```bash
python - <<'PY'
import pickle, networkx as nx
g, meta = pickle.load(open("<the /tmp/england_XXXX.pkl path>", "rb"))
v = meta["validation"]
assert v["derelict_edges"] == 0, v["derelict_edges"]
assert v["self_loops"] == 0, v["self_loops"]
print("components", v["component_count"], "largest", v["largest_component_size"])
# sanity: the largest component is the overwhelming majority of nodes
assert v["largest_component_size"] >= 240_000
assert v["component_count"] <= 2000
PY
```

Expected: components ≤ ~1669 ± noise, largest ≥ ~240k. (Crit 5 — internal junction — was proven at fixture scale in Task 2's `test_internal_junction_way_joins_main_chain_at_an_internal_node`; the bulk run is the real-data confirmation that the joined-up Midlands component exists.)

---

### Task 5: Final verification & acceptance sweep

**Files:** none modified — this is the acceptance gate confirming criteria 3 and 4 across the committed codebase.

- [ ] **Step 1: Full suite green**

Run: `pytest -q` (and, with the optional bulk extra installed, `pytest --run-bulk -q`).

Expected: all green. The count should be *≥ the pre-rewrite count, minus the deleted tolerance-snap/override/grid tests, plus the noded + alignment regression tests* added in Tasks 1–2.

- [ ] **Step 2: ruff clean**

Run: `ruff check .`

Expected: clean. (The `scripts/` B905 is gone from Task 2 Step 7; the deleted `snap.py`/`overrides.json`/`load_overrides`/`_contract` leave no unused-import residue after Tasks 2–3's import cleanups.)

- [ ] **Step 3: grep-verify no production coordinate-key graph consumers remain (crit 4)**

Run:

```bash
rg -n "graph\.nodes\[\(|g\.nodes\[\(|\.add_node\(\(|node in graph\.nodes|_node_key\(" pound/ | rg -v "build_gazetteer|ambiguous_place_names|place_coords\[|_node_key\(nd\[|_node_key\(n\.lat|_node_key\(graph\.nodes"
```

Expected: the only `_node_key(` hits in `pound/` are in `graph/gazetteer.py` (keying the *place dict*, not the graph: `_node_key(n.lat, n.lon)` and `_node_key(nd["lat"], nd["lon"])`) and in `graph/build.py` (`_node_key(lat, lon)` for the coord index, never as a graph node key). No `graph.nodes[(...)]`/`g.nodes[(...)]`/`add_node((...))`/`node in graph.nodes` patterns survive (they would be coordinate-key graph access). `route/snap.py` is gone. If any stray coordinate-key graph access remains, migrate it to `g.nodes[uid]["lat"]`-style attribute access.

- [ ] **Step 4: Confirm all seven acceptance criteria**

Tick each against the codebase:

1. `pound-ingest build england` exits 0, `derelict_edges==0`, `self_loops==0`, `component_count` ≤ ~1,669, largest ≥ ~240k, ≤ ~2 min — Task 4.
2. Oxford fixture builds under the noded model with re-derived (higher) edge counts; pendant joins 1003 without `overrides.json` — Task 2 Step 8 + the deleted `overrides.json`.
3. `pytest` green, `ruff check .` clean (scripts deleted) — Steps 1–2.
4. No production `(lat,lon)` graph-key consumers — Step 3.
5. Regression test asserts internal-junction join — `test_internal_junction_way_joins_main_chain_at_an_internal_node` (Task 2 Step 9).
6. Regression test asserts edge-collision merge (`kind==LOCK`, LOCK `osm_way_id` kept, `locks==1` at build + after `attach_locks`) — `test_coincident_lock_and_canal_ways_merge_to_one_lock_edge` (Task 2 Step 9).
7. Regression test asserts lock-node tie-break (LOCK segment gets `locks=1`, spur stays 0) — `test_lock_node_tie_goes_to_lock_edge_not_canal_spur` (Task 2 Step 9).

- [ ] **Step 5: Commit verification artifacts (optional)**

If you recorded any verification notes in `docs/testing/` or `STATUS.md` during Task 4, commit them:

```bash
git add docs/testing/2026-07-03-pound-noded-build-verification.md STATUS.md 2>/dev/null
git commit -m "docs: noded build verification report"
```

- [ ] **Step 6: Offer finishing-the-branch**

Use the superpowers:finishing-a-development-branch skill to present merge / PR / cleanup options to Kurt. The branch delivers a connectivity rewrite on `main` (the design spec supersedes the Scope D PR1 connectivity sections); merging is a notable change worth a PR + Kurt's eyeball on the bulk England report.

---

## Self-Review

**1. Spec coverage.**

- §3.1 node-key contract (internal uids) — Task 3.
- §3.2 alignment guard in `read_pbf` — Task 1 (and overpass.py noted unchanged).
- §3.2 dual-index `resolve_or_create`, segment edges, per-segment length, way-level attrs, dedupe consecutive dups, closed-ring skip — Task 2 Step 1.
- §3.3 edge-collision merge (kind specificity, dims union-tighten, name first non-None, tunnel/bridge OR, length keep, osm_way_id LOCK-keep, locks=max at merge) — Task 2 Step 1 `_merge_edge`; regression Test (crit 6) Step 9.
- §3.4 removals (Phase 1/3, tolerance-snap, grid, `load_overrides`, `overrides.json`, build kwargs, graph attrs, CLI flags, `route/snap.py` + test) — Task 2 (most) + Task 3 (snap).
- §3.5 `attach_node_names` body rewrite + `attach_locks` **flight-level chamber model (Model D, supersedes spec's literal "set on all")** + lock-node tie-break — Tasks 2 (locks + spec-doc §3.5 update) + 3 (gazetteer); `_node_key`/`_haversine_m` stay; staircase fixture augmented (4 gates → 3 chambers); optional `node_count_osm`/`edge_count_segments` graph attrs — noted optional in §3.5, **not implemented** (YAGNI; the build report already has `total_edges`/`total_nodes`).
- §3.6 hard-fail gate narrowed (derelict/self_loops only; component/missing-dims/ambiguous advisory) — Task 2 Step 4 (cli).
- §4 Oxford fixture migration — Task 2 Step 6.
- §5 migration table — Task 2 + Task 3 cover every row; `_long_plan` re-derivation — Task 2 Step 13.
- §6 acceptance crit 1–7 — Task 4 (1) + Task 5 (3,4) + Task 2 (2,5,6,7).
- §OQ-1 grid bucket removal — Task 2.
- §OQ-2/3 — no speculative multi-id edge field / id-less path kept as scaffolding — Tasks 2–3.
- §note on `scripts/` — Task 2 Step 7.

**Gap:** the optional `g.graph["node_count_osm"]`/`["edge_count_segments"]` attrs (§3.5, "optional, if useful") are not implemented — intentional YAGNI; the build report already carries `total_edges`/`total_nodes`.

**2. Placeholder scan.** No TBD/TODO/"fill in"/"similar to" — every code step shows the code; every count is spelled out (8 nodes, 6 edges, largest 6, missing_dims 5, `_long_plan` 4 edges / days=4).

**3. Type consistency.** `_resolve_or_create(osm_id, lat, lon)` → uid (Task 3) / coord key (Task 2) in both tasks; `build_graph(features)` (no kwargs) in Tasks 2–5; `attach_locks(graph, features)` signature unchanged (its body uses `gate_ids`, `lock_ways`, `flights`, `way_edges`, `_seg_idx`, `way_segments` as Model D locals); `_name_for(node_uid, graph, gaz)` Task 3 (Task 2 keeps `_name_for(node_key, features, gaz)` — the signature change Point is exactly the Task 3 Step 3 edit); `_resolve_place(name, gaz, graph)` Task 3 only; `_merge_edge(u, v, way, length_m, seg_geom)` Task 2; `_KIND_RANK` keys `WaterwayKind.LOCK/CANAL/RIVER/FAIRWAY` match `WaterwayKind` enum values. Counts internally consistent: Oxford 8 nodes / 6 edges / largest_component 6 / missing_dims 5 across `test_build.py` + `test_connectivity.py`; staircase 4 gates → 3 chambers (sum==3, len==3) across `test_locks.py` + the four Model D regression tests; `_long_plan` 4-edge path. The crit-6 collision test still asserts `locks==1` at build (collision-merge sets it) and after `attach_locks` (the single merged edge's flight has no gates → floor → 1 lock, idempotent); crit-7 tie-break test uses a gateless 2-node lock → floor → 1, spur stays 0.
