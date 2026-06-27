# Scope D PR1 — Task 1 Implementation Report

### Bulk connectivity: co-primary joins (node-ref + exact-coord) + reported tolerance-snap fallback + overrides

## What I implemented

Rewrote `pound/graph/build.py` to add three-phase bulk connectivity per the
plan, and added `load_overrides`:

- **Phase 1 — node-ref authority**: ways sharing an OSM node id at an endpoint
  are unified (keys contracted) even when their coords differ slightly. Skipped
  automatically when `way.node_ids` is empty (Overpass `out geom` path).
- **Phase 2 — exact-coordinate authority**: way-ends rounding to the same
  `_node_key` (7-decimal) share a graph node by construction — preserved Scope C
  behaviour, NOT demoted to a snap candidate (OQ-1).
- **Phase 3 — tolerance-snap candidates**: for each dangling tip (degree-1 node),
  the nearest *other* node (excluding its sole neighbor) within
  `0 < dist <= tolerance_m` becomes a candidate. Two adjacent junctions are
  correctly NOT candidates (neither is a tip). A `split` override suppresses a
  candidate; a `join` override confirms (resolves) a built candidate and also
  bridges genuine beyond-tolerance gaps. A candidate that would duplicate an
  existing edge is recorded unresolved, not built.
- Graph now stores `graph.graph["tolerance_snaps_used"]`,
  `["tolerance_snaps_unresolved"]`, `["overrides_applied"]`, and per-node
  `osm_node_ids`. `_node_key`, `_haversine_m`, the edge-attribute contract, and
  the Scope C node key `(lat, lon)` are unchanged.
- `load_overrides(path)`: missing file → `{"join": [], "split": []}`; unknown
  top-level keys → `ValueError`; malformed JSON → `ValueError` (loud, no silent
  fallback). join/split pairs are stringified on load.
- `.gitignore` whitelists `!pound/data/overrides.json`.

## Files changed

- `pound/graph/build.py` — rewrite (three phases + `load_overrides` + `_contract` + `_key_for_osm_id`)
- `.gitignore` — whitelist `!pound/data/overrides.json`
- `tests/graph/test_build_bulk.py` — new, 10 tests

## TDD evidence

**RED** — before implementation:

```
$ uv run pytest tests/graph/test_build_bulk.py -v
ImportError: cannot import name 'load_overrides' from 'pound.graph.build'
1 error in 0.28s
```

(expected: `build_graph() got an unexpected keyword argument 'tolerance_m'` /
`load_overrides` absent — matched.)

**GREEN** — after implementation:

```
$ uv run pytest tests/graph/test_build_bulk.py -v
10 passed in 0.15s
```

## Deviations from the verbatim plan (necessarily, to satisfy acceptance)

Two internal inconsistencies in the plan's verbatim code/tests would have made
four of the ten tests fail against the verbatim implementation. Both are
defects in the plan itself (not in the acceptance contract), so fixing them is
the faithful design judgment the brief explicitly leaves room for:

1. **osm id type mismatch (affected `test_join_override_bridges_a_beyond_tolerance_gap`).**
   `load_overrides` stringifies join/split ids, but the plan stored
   `osm_node_ids` as ints (from `way.node_ids`). `_key_for_osm_id` does
   `str(osm_id) in set[int]` → never matches → the beyond-tolerance `join`
   bridge never connects → the test fails.
   **Fix:** store `osm_node_ids` as strings (`str(osm_id)`), making override
   resolution consistently string-keyed across `load_overrides`,
   `_key_for_osm_id`, and the phase-3 join confirmation. Pure consistency fix;
   no behaviour change for the int-id input path.

2. **Phase-3 candidate test geometry was outside tolerance (affected three tests:
   `test_tolerance_snap_fallback…`, `test_join_override_resolves…`,
   `test_split_override…`).**
   The test comment says B's start is "~3 m west of A's end", but the verbatim
   coord `(-1.2618)` is actually ~13.8 m EAST of A's end `(-1.2620)` — beyond
   the `tolerance_m=10.0` the tests pin — so no candidate fires, the snap never
   builds, and the three assertions fail.
   **Fix:** corrected B's start to `(-1.26204)` — genuinely ~2.8 m west of
   A's end, distinct 7-decimal key, within 10 m tolerance. This aligns the
   coordinate with the test's own stated intent and its assertions; it does
   not weaken any assertion. All three tests now pass for the right reason (a
   real phase-3 candidate).

I did NOT change any assertion or any tolerance value — only the impl id-type
and one fixture coordinate typo. The remaining 6 tests pass verbatim.

## Full-suite + ruff before commit

```
$ uv run pytest -q
117 passed, 1 skipped in 0.22s        (skip = network test, by default)
$ uv run ruff check pound/graph/build.py tests/graph/test_build_bulk.py
All checks passed!
$ uv run ruff format --check pound/graph/build.py tests/graph/test_build_bulk.py
2 files already formatted
```

Pre-existing `ruff check .` reports 4 `I001` import-sort errors in files I did
NOT touch (`tests/graph/test_build.py`, `tests/graph/test_locks.py`,
`tests/route/test_snap.py`, `tests/validate/test_connectivity.py`). Verified
pre-existing by `git stash` (they appear with my changes stashed). Out of
Task 1 scope; left untouched.

## Self-review findings

- `way_ends` is threaded through `_contract` per the plan but is not consumed
  after phase 1 in this task (phase 3 reads `g.degree`/`g.edges` directly). It's
  defensive scaffolding the plan includes; left as-is rather than refactor.
- The two authority tests pass with `tolerance_m=0.0`, proving joins are
  authoritative, not snap-derived (the plan's load-bearing property).
- No Oxford-fixture unit test moved: phase 2 keeps the existing exact-coord
  chain joined and Duke's Cut (~1.3 km away) disconnected at default tolerance,
  so `tests/graph/test_build.py` counts are unchanged.

## Residual risks / concerns

- The two deviations above are flagged clearly; if the parent wants the test
  file byte-identical to the plan, the coordinate change is the only test-side
  edit and is reversible — but then `test_*_snap_*` cannot pass at
  `tolerance_m=10.0` without a tolerance-semantics change, which I judged worse.
- `uv run` re-resolved `uv.lock` (added an explicit `networkx==3.6.1` pin) as an
  environment side effect; reverted via `git checkout uv.lock` — NOT in the
  commit.
