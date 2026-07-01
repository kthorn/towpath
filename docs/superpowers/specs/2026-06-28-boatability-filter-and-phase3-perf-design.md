# Boatability filter, infra-node pruning, and Phase 3 perf — design

**Date:** 2026-06-28
**Status:** draft (awaiting user review)
**Scope:** Scope D PR1 live-testing follow-on. Three changes to the bulk
ingest/build pipeline found during real-England-build testing of merged work
at `f8b3b36`.

## Background

Live testing of `pound-ingest build england` (`docs/testing/2026-06-26-scope-d-pr1-live-testing.md`) surfaced two gate failures and one perf wart:

1. `self_loops > 0` — 135 closed-ring ways (lock-chamber outlines, basins, wetlands, amusement rides). **Fixed separately** (skip closed rings at emission in `pound/graph/build.py`, 3 new tests, green). Not in this design.
2. `tolerance_snaps_unresolved=6 > --max-unresolved-snaps=0` — the curation queue. On inspection **5 of 6 snaps involve a `boat=no` way**: the filter never checks the `boat` access tag, so non-navigable drainage/isolated-tributary ways enter the routable graph. These 6 snaps are not curation items; they are symptoms of the missing boatability filter.
3. `build_graph` Phase 3 takes minutes per build on the England extract (O(tips × nodes)). The live-testing plan's curation loop (D.2/D.3) re-runs `build england` per round, so iteration is painful. Tracked in GitHub issue #2.

This design treats (2) as two filter changes (way filter + infra-node pruning) and (3) as a perf refactor. Together they let the England build regenerate with non-navigable water excluded and curation iteration practical.

## The `boat` tag on England (measured from the cached extract)

| `boat` value | ways | classified-routable | decision |
|---|---:|---:|---|
| `yes` | 7552 | yes | keep |
| `None` | 15519 | yes | keep (default) |
| `no` | 5343 | yes | **exclude** |
| `private` | 62 | yes | keep (navigable w/ permission) |
| `unknown` | 14 | yes | keep |
| `permissive` | 13 | yes | keep |
| `designated` | 8 | yes | keep |
| `discouraged` | 3 | yes | keep (passable, warned) |
| `unsuitable` | 1 | yes | **exclude** |
| `canoe` | 2 | yes | **exclude** (out of scope: canal-boat routing) |
| `permit` | 1 | yes | keep |
| `unkmown` (typo of `unknown`) | 1 | yes | keep (blacklist falls back to "keep") |

Exclusion set (Option B, agreed): **`{no, unsuitable, canoe}`** — blacklist style; bad data and unknowns (including typos like `unkmown` for `unknown`) fall back to "keep," not silent drop. The `no` value is 99.94% of the excluded mass (5343 of 5346). The single `unkmown` typo is kept deliberately; aliasing it to `unknown` would risk excluding a real `boat=yes` edge if a different typo were to collide with a blacklist entry, so the blacklist stays literal-string only.

## Non-navigable infra nodes (measured)

Infra nodes sitting entirely on non-navigable ways (counted against the **full**, un-filtered feature set — see Section 1's ordering note for why this must be measured before the way filter runs):

| kind | total | would-drop |
|---|---:|---:|
| lock_gate | 3670 | 28 |
| lock | 39 | 5 |
| mooring | 17 | 0 |
| marina | 117 | 0 |
| movable_bridge | 0 | 0 |
| **total** | | **33** |

`place` nodes are **never dropped** (79173 total) — gazetteer anchors (towns, suburbs) are route-relevant irrespective of whether the nearest waterway is navigable; a non-navigable drainage ditch should not remove `Reading` from the gazetteer.

A node is dropped iff **all** its incident ways are non-navigable (a lock_gate at the junction of a navigable and non-navigable waterway gates traffic between them and stays).

---

## Section 1 — Way boatability filter

### New predicate

`pound/ingest/filters.py`:

```python
_NON_NAVIGABLE_BOAT = {"no", "unsuitable", "canoe"}

def is_navigable(tags: dict[str, str] | None) -> bool:
    """True unless the way is explicitly tagged non-navigable to canal boats.

    OSM `boat` access tag: `no`=prohibited/impassable, `unsuitable`=navigable-
    in-principle-but-not-really, `canoe`=canoe-only (out of scope for a canal-
    boat router). Everything else (`yes`, `private`, `permissive`, `permit`,
    `designated`, `discouraged`, `unknown`, missing) is kept — bad data and
    unknowns fall back to "keep," not silent drop. Dimensions (`maxwidth` etc.)
    are a *separate*, plan-time concern (route/cost.py:is_eligible) and stay
    untouched here.
    """
    if not tags:
        return True
    return tags.get("boat") not in _NON_NAVIGABLE_BOAT
```

### Why a separate predicate, not folded into `classify_way`

`classify_way` answers "what *kind* of waterway is this" (its docstring, its responsibility). Boatability is an *exclusion* concern, the same shape as `is_derelict` — and both readers already chain two such predicates (`is_derelict` then `classify_way`). Folding boatability into `classify_way` would overload one function with two responsibilities (classification + exclusion) and break the symmetry the readers rely on.

### Where the way filter runs — AFTER prune, not inside the readers

**The way filter does NOT live inside the readers' way loops.** It runs as a
post-processing step, *after* `prune_non_navigable_infra` (Section 2), on the
full `WaterwayFeatures`. This ordering is load-bearing:

- `prune_non_navigable_infra` joins each infra node to its incident ways and
  drops the node iff **all** incidents are non-navigable. It needs the
  non-navigable ways *present* in `features.ways` to make that decision.
- If the way filter stripped `boat=no` ways first (inside the readers), every
  infra node sitting solely on `boat=no` ways would have zero surviving
  incidents and fall into the prune's *keep* rule ("no incidents → kept").
  Verified against the England extract: all 33 candidate-drop nodes become
  "kept" under that ordering — prune would do nothing.

So the call-site shape is:

```python
# in overpass.py:fetch_oxford() and osm.py:read_england()
features = parse(...)              # / read_pbf(...) — full features, no boat filter
features = prune_non_navigable_infra(features)   # Section 2 — sees full ways
features = filter_navigable_ways(features)      # Section 1 — NOW drop boat=no ways
return features
```

`filter_navigable_ways(features) -> WaterwayFeatures` is a new pure function
co-located with `is_navigable` in `pound/ingest/filters.py` (it *is* the
batch form of the predicate; same module, same responsibility). It returns a
new `WaterwayFeatures` whose `ways` list omits any way for which
`is_navigable(tags) is False` (and likewise drops the `derelict` ways the
readers currently drop inline — the readers' inline `is_derelict` checks are
removed and folded into this one post-filter step, so both exclusion
predicates apply at the same place, after prune). `nodes` are untouched here
(prune already handled infra nodes; `place` and the no-incident cases are kept).

**Way-only.** `classify_node` is untouched — node navigability is determined
by `prune` (Section 2), not by the node's own tags (only 2 nodes carry
`boat=no` directly; the rest inherit from their carrier way, which prune
handles via the incident-way join).

### Scope-creep guard

`route/cost.py`, `WayDimensions`, and the dimension extraction in `filters.py` are **untouched**. Dimension enforcement is a plan-time, per-boat concern and is correct as designed.

### Tests

New in `tests/ingest/test_filters.py` (parametrized):

- `boat=no`/`unsuitable`/`canoe` → `is_navigable` returns `False`.
- `boat=yes`/`private`/`permissive`/`permit`/`designated`/`discouraged`/`unknown`/missing/`unkmown`(typo) → `True`.
- `filter_navigable_ways` drops a `boat=no` canal way, keeps a `boat=yes` and a `boat=None` way, and also drops a `disused:waterway` way (the folded `is_derelict` responsibility). Returns a new features object; input is not mutated.

Reader integration (Overpass path, in `tests/ingest/test_overpass.py`): the
full Overpass chain (`fetch_oxford` → `parse` → `prune_non_navigable_infra` →
`filter_navigable_ways`) drops a `boat=no` canal way from the final features,
keeps a `boat=yes` way, and keeps a `boat=None` way. (Bulk path covered by
Section 2's prune tests + the existing bulk reader test if it asserts counts.)

---

## Section 2 — Infra-node post-filter

### New module and function

`pound/ingest/prune.py` (new file):

```python
def prune_non_navigable_infra(features: WaterwayFeatures) -> WaterwayFeatures:
    """Return a new WaterwayFeatures with infra nodes sitting entirely on
    non-navigable ways removed. `place` nodes are never removed (gazetteer
    relevance is independent of waterway navigability).

    Pure: returns a new features object; does not mutate the input. Bulk-path
    only: requires `WaterwayWay.node_ids` (filled by the pyosmium reader). On
    the Overpass `out geom` path `node_ids` is empty, so no node is incident to
    any way and this is a no-op (documented; not a silent drop).
    """
```

- **Pure:** returns a new `WaterwayFeatures`, does not mutate input.
- **Kinds affected:** `LOCK_GATE`, `LOCK`, `MOORING`, `MOVABLE_BRIDGE`, `MARINA` — every kind `classify_node` actually returns, which is everything in `NodeKind` *except* `PLACE` (always kept). `NodeKind.OTHER` is a forward-compat enum value that `classify_node` never produces (verified at `pound/ingest/filters.py:83-96`), so it is not a case the prune even encounters — not "excluded by construction," just never emitted.
- **Drop rule:** a non-place classified node is dropped iff it is incident to at least one way AND all its incident ways are non-navigable (`is_navigable(tags) is False`). A node with **no** incident ways (no `node_ids` populated — the Overpass path) is **kept**: the post-filter cannot determine navigability by join, and dropping it would be unsupportable guesswork; documented no-op.
- **Where called:** the bulk reader (`osm.py:read_england`, after `read_pbf`) calls it on the **full, unfiltered** features. The Overpass reader `overpass.py:fetch_oxford` (the network wrapper around `parse()`) also calls it, wrapping `parse()`'s return. **`parse()` itself is NOT modified** — it stays pure (its purity is asserted in its docstring, `overpass.py:8`); the prune call lives in `fetch_oxford` so it sits outside the pure-data path. Both Overpass CLI entrypoints (`_cmd_oxford` at `cli.py:31`, `_cmd_build ... oxford` at `cli.py:87-89`) call `fetch_oxford`, so every Overpass route inherits the prune. On the Overpass path `node_ids` is empty (real `out geom` returns none), so the join yields no incidents and prune is a no-op there (documented; not a silent drop).
- **Must run before `filter_navigable_ways`** (Section 1): prune needs the non-navigable ways present to decide "all incidents non-navigable." See Section 1's ordering note. Final chain in both readers: `parse/read_pbf → prune_non_navigable_infra → filter_navigable_ways`.

### Why a new module, not appended to `filters.py`

`filters.py`'s job is tag-local drop decisions (`classify_way`, `is_derelict`, `is_navigable`, `extract_dimensions`, `classify_node` — all pure functions of one tag dict). The post-filter is a tag + **join** decision (a node's navigability is a function of its incident ways' tags). Co-locating it would overload `filters.py` with a different responsibility shape. A new module keeps the boundary clean and the unit easy to reason about. (`AGENTS.md`: one call site — write it inline; but this is a *function* with its own tests and imports, so a small module is the inline equivalent. Not pre-generalizing — there is exactly one caller.)

### Bulk-only caveat

The post-filter is effective only when `WaterwayWay.node_ids` is populated (the bulk pyosmium reader). The Overpass `out geom` reader leaves `node_ids` empty, so the join yields no incidents and the post-filter is a no-op. This is **documented, not a silent drop**: the Overpass path is dev scaffolding, and the small Oxford fixture's infra nodes survive (its 5 ways are all navigable anyway, so the no-op is correct there too). Building a coordinate-proximity fallback for the Overpass path is out of scope.

### Tests

New file `tests/ingest/test_prune.py`:

- A `lock_gate` node whose single incident way is `boat=no` → dropped.
- A `lock_gate` node at the junction of one `boat=no` and one `boat=yes` way → kept (gates traffic between them).
- A `lock_gate` node at the junction of **two** `boat=no` ways and **one** `boat=yes` way → kept (still gates traffic; mixed junction).
- A `place` node whose all incident ways are `boat=no` → kept (gazetteer anchor).
- A node with no incident ways (empty `node_ids` path) → kept (the Overpass no-op case).
- A way with no `boat` tag (missing key) incident to an infra node counts as navigable (does not alone trigger a drop).
- Purity: the input `WaterwayFeatures` is not mutated.

Bulk integration: the existing `tests/ingest/test_osm.py::test_read_pbf_*` tests assert shape; the post-filter is applied by `read_england`, not by `read_pbf`, so those tests are unaffected. A new bulk test (or an assertion in the existing round-trip test) confirms England-shape post-filter counts if cheap.

---

## Section 3 — Phase 3 perf (grid-bucket spatial index)

### Problem

`pound/graph/build.py` Phase 3 finds each dangling tip's nearest other graph node within `tolerance_m` by scanning every other node:

```python
for tip in tips:
    nbr = next(iter(g[tip]))
    best, best_d, best_w = None, math.inf, -1
    for other in g.nodes():           # <-- O(n) per tip
        ...
        d = _haversine_m(tip, other)  # <-- all-pairs haversine
```

On England (~32k nodes, thousands of tips) this is minutes per build, biting every curation re-run (issue #2).

### Fix

Inline grid-bucket spatial index — **pure perf refactor, observable behaviour identical**.

- **Cell size:** `cell_deg = tolerance_m / 111_320` (1° lat ≈ 111.32 km). Bucket key `(int((lat+90)/cell_deg), int((lon+180)/cell_deg))`. The cell size is derived from the already-present `tolerance_m` build parameter, so no tuning.
- **Per-tip query:** look up the tip's cell and its 8 Moore neighbours, collect candidate nodes, apply the exact haversine `0 < d <= tolerance_m` filter, pick the nearest (excluding the tip and its sole neighbour). Identical selection logic to today; only the candidate set is bounded (O(1) amortised per tip).
- **Tie-break:** the current code picks the strict-min distance, first-seen-wins on exact ties (`d >= best_d`), iterating `g.nodes()` in NetworkX insertion order. The grid implementation iterates candidates in a deterministic order (sorted by cell key, then node key) — which is **deterministic but not insertion-order**, so on synthetic fixtures with *exact* sub-metre ties the chosen nearest neighbour may differ. No existing test exercises an exact tie (fixture coords use ≥4 decimal places, so distances are distinct), so the existing Phase 3 tests pass unchanged in practice; the spec no longer claims "matches exactly," only "deterministic and no existing test depends on the difference." A new tie-presence test is not required (the existing tests are the regression surface), but the implementer must keep the sort stable.
- **`tolerance_m <= 0` short-circuit:** several existing tests pass `tolerance_m=0.0` to disable snaps (`test_build_bulk.py` lines ~59, 76, 105). The grid formula `cell_deg = tolerance_m / 111_320` would `ZeroDivisionError` on that input. The refactor **must** short-circuit Phase 3 when `tolerance_m <= 0` (no candidates, no grid built — matching today's behaviour where `d > tolerance_m` rejects everything). This is a behavioural-preservation requirement, not a new feature.
- **Longitude oversizing:** using a single (lat-derived) cell size slightly oversizes lon cells at high latitude. This is **safe** — it only adds cheap haversine re-checks, never drops a candidate. England max latitude ~55°, so lon cells are at most ~1.7× oversize — negligible.

### Why not scipy KD-tree / LSH

- **scipy `cKDTree`** (O(log n), exact): would work, but `scipy` is not a dependency (`pyproject.toml` has only `networkx`) and adding it for one call site is heavy. Grid is O(1) amortised and dependency-free.
- **Locality-sensitive hashing** (probabilistic near-neighbour): wrong fit. (1) It exists for the **curse of dimensionality**; we're in 2D, where exact trees/buckets are already optimal. (2) It is **approximate** — returns near-neighbours with a probability guarantee, misses some; we'd still need the exact haversine re-check the grid gives for free. (3) LSH is built for "all points within variable r"; our r (`tolerance_m`) is fixed, small, and known at build time — exactly the grid-bucket use case.

Grid bucket is the simplest exact method for this fixed-small-radius 2D problem.

### Tests

- New perf test (synthetic graph with many tips/nodes) asserting sub-second completion and correct snap results identical to the current implementation.
- All existing Phase 3 tests (snap joins a tip to a junction; `split` override suppresses; beyond-tolerance not a candidate; the Oxford pendant case; the duplicate-edge-as-unresolved case) pass **unchanged** — pure perf refactor, no behaviour change.

---

## Architecture summary

```
overpass.py parse()     /  osm.py read_pbf()    → full WaterwayFeatures
                                                 │
         prune_non_navigable_infra (NEW, ingest/prune.py)   ← sees FULL ways
                                                 │   (drops infra nodes whose
                                                 │    ALL incident ways are
                                                 │    non-navigable)
                                                 ▼
         filter_navigable_ways (NEW, filters.py)  → drops boat=no/unsuitable/canoe
                                                 │   ways AND the derelict ways
                                                 │   (folds the readers' inline
                                                 │   is_derelict checks)
                                                 ▼
         build_graph (pound/graph/build.py)
           Phase 1+2 unchanged
           Phase 3 grid-bucket perf (NEW, same behaviour + tolerance_m<=0 short-circuit)
                                                 ▼
         validate_graph / save_artifact (unchanged)
```

**Ordering is load-bearing**: prune runs on full features (needs boat=no ways
present to decide "all incidents non-navigable"); the way filter runs after
prune. Reversing the order defeats prune entirely (verified: all 33 candidate
drops become "kept" if ways are stripped first).

Untouched: `route/cost.py`, `WayDimensions`, dimension extraction, gazetteer,
locks, artifact serialization, the CLI, `classify_node`, `classify_way`. The
Oxford integration tests and the hermetic suite remain green by construction
(Oxford fixture ways carry no `boat` tags; the post-filter is a no-op on its
empty `node_ids`; Phase 3 behaviour is preserved).

## Out of scope

- Dimension access refinement (`private`/`permissive`/`permit` permission gating at plan-time): 79 ways; a later flag, not a PR1 build-exclusion.
- Coordinate-proximity join for the Overpass path (so the post-filter is effective there too): the Overpass path is dev scaffolding; out of scope.
- The 6 unresolved snaps: with the boatability filter, snaps 1/2/3/5/6 dissolve or change character (their `boat=no` ways drop). Re-evaluate the residual queue on the rebuilt graph; snap 4 (both ways `boat=None`) is the one genuine curation item. Curation is a follow-on, not part of this design.
- Phase 3 algorithm (nearest-tip snap, override confirmation, duplicate-edge-as-unresolved): unchanged. Only the inner nearest-neighbour search is reimplemented.

## Done-when

- `is_navigable` predicate lands in `filters.py`, gated in both readers; parametrized + integration tests green.
- `prune_non_navigable_infra` lands in `ingest/prune.py`, called by both readers; tests green; Oxford fixture unaffected.
- Phase 3 grid-bucket refactor lands in `build.py`; existing Phase 3 tests unchanged; new perf test green; England build previously-minutes becomes O(seconds) for Phase 3.
- Rebuilt `england.pkl` has `derelict_edges == 0`, `self_loops == 0`, and a `tolerance_snaps_unresolved` queue reflecting only genuine curation items (the `boat=no` noise is gone).
- Hermetic suite (`uv run pytest -q`) still green at the current baseline (`138 collected`, ~133 passed / 5 skipped after the `--overwrite` argv-test fix landed in commit `9adcf7b`) or better, with the new tests added by this spec.
