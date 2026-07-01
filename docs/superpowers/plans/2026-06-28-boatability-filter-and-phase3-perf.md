# Boatability filter, infra-node pruning, and Phase 3 perf — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `boat=no`/`unsuitable`/`canoe` ways (and the infra nodes sitting solely on them) from entering the routable graph, and make the `build england` curation loop iterate in seconds instead of minutes.

**Architecture:** A new `is_navigable` predicate + `filter_navigable_ways` batch form in `pound/ingest/filters.py`; a new pure `prune_non_navigable_infra` in `pound/ingest/prune.py` that joins infra nodes to incident ways. Both readers chain `parse/read_pbf → prune → filter_navigable_ways` (prune must run **before** the way filter — it needs the `boat=no` ways present to decide "all incidents non-navigable"). `build_graph` Phase 3's O(tips × nodes) all-pairs haversine scan is replaced with an inline grid-bucket spatial index (no new dependency), with a `tolerance_m <= 0` short-circuit that preserves today's "snaps off" behavior. `is_derelict` stays inline in both readers (NOT folded into the new filter — folding would break `test_parse_excludes_derelict` and leak `disused:waterway` ways).

**Tech Stack:** Python 3.12+, pydantic v2, networkx, pytest with `bulk` and `network` markers. No new dependencies. Pure-Python haversine already in `pound/graph/build.py`.

**Spec:** `docs/superpowers/specs/2026-06-28-boatability-filter-and-phase3-perf-design.md` (status: Refined). Drop the closed-ring self-loop fix from the spec's Background is **already landed** on `main` (commit `f1cdd20`); this plan does not touch it.

## Global Constraints

- Exclusion set is **literal-string** blacklist `{no, unsuitable, canoe}` (not aliased — typos like `unkmown` stay "keep"). Sources: spec §1, §"measured".
- `is_derelict` stays inline in both readers' way loops; `filter_navigable_ways` applies **only** the boat filter. Do NOT fold `is_derelict`.
- Prune runs **before** `filter_navigable_ways` in both readers. Reversing defeats prune (verified: all 33 candidate-drop nodes become "kept"). The chain is fixed: `parse/read_pbf → prune_non_navigable_infra → filter_navigable_ways`.
- `parse()` in `pound/ingest/overpass.py` stays pure (its purity is asserted in the module docstring). The prune+filter chain lives in `fetch_oxford` / `read_england`, **not** in `parse` / `read_pbf`.
- `place` nodes are never dropped by prune (gazetteer relevance is independent of waterway navigability).
- Phase 3 is a **pure perf refactor**: identical selection logic (`0 < d <= tolerance_m`, exclude the tip and its sole neighbor, pick strict-min distance). Observable behavior is unchanged; one new short-circuit (`tolerance_m <= 0` ⇒ no candidates, no grid).
- No new dependencies. `scipy` is explicitly **not** added. Grid bucket is inline pure Python.
- TDD throughout (RED → GREEN → commit), one concern per commit. Run `ruff` before each commit.

---

## File Structure

| File | Status | Responsibility |
|------|--------|----------------|
| `pound/ingest/filters.py` | Modify | Add `is_navigable` predicate + `filter_navigable_ways` batch form |
| `pound/ingest/prune.py` | Create | New pure module: `prune_non_navigable_infra(features) -> WaterwayFeatures` |
| `pound/ingest/overpass.py` | Modify | Add prune + filter chain to `fetch_oxford`; `parse` unchanged |
| `pound/ingest/osm.py` | Modify | Add prune + filter chain to `read_england`; `read_pbf` unchanged |
| `pound/graph/build.py` | Modify | Replace Phase 3 all-pairs scan with grid-bucket spatial index; add `tolerance_m <= 0` short-circuit |
| `tests/ingest/test_filters.py` | Modify | Add parametrized `is_navigable` tests + `filter_navigable_ways` tests (incl. `lock=yes`+`boat=no`) |
| `tests/ingest/test_prune.py` | Create | New: prune drop-rule tests (incl. mixed-junction, node-level-boat-ignored) |
| `tests/ingest/test_overpass.py` | Modify | Add a `fetch_oxford → parse → prune → filter` chain test that monkeypatches `fetch_raw` |
| `tests/ingest/test_osm.py` | Modify | Add a `read_england` chain test that monkeypatches `run_tags_filter` (copies fixture to out_pbf) |
| `tests/graph/test_build_bulk.py` | Modify | Add Phase 3 perf test (relative speedup; `>=4-decimal` coords, no exact ties) |

All paths are `pound/...` and `tests/...` (repo-rooted). Test mirrors use `tests/<package>/`.

---

### Task 1: `is_navigable` predicate

**Files:**

- Modify: `pound/ingest/filters.py` (append after `is_derelict` ~line 57)
- Test: `tests/ingest/test_filters.py` (extend existing import + add parametrized tests)

**Interfaces:**

- Consumes: nothing new (mirrors `is_derelict` signature)
- Produces: `is_navigable(tags: dict[str,str] | None) -> bool` — `True` unless `tags["boat"] in {"no","unsuitable","canoe"}`

- [ ] **Step 1: Write the failing tests**

Append to `tests/ingest/test_filters.py`. Extend the existing import:

```python
from pound.ingest.filters import (
    classify_node,
    classify_way,
    extract_dimensions,
    is_derelict,
    is_navigable,  # NEW
)
```

Append the parametrized test:

```python
import pytest  # already imported at top


@pytest.mark.parametrize(
    "boat_value, expected",
    [
        ("no", False),
        ("unsuitable", False),
        ("canoe", False),
        ("yes", True),
        ("private", True),
        ("permissive", True),
        ("permit", True),
        ("designated", True),
        ("discouraged", True),
        ("unknown", True),
        ("unkmown", True),  # typo of "unknown" -> kept (literal-string blacklist)
        (None, True),  # missing key -> kept (default navigable)
    ],
)
def test_is_navigable(boat_value, expected):
    tags = {} if boat_value is None else {"boat": boat_value}
    if boat_value is None:
        # also test the fully-empty tag dict path
        assert is_navigable({}) is True
    assert is_navigable(tags) is expected


def test_is_navigable_none_tags():
    # boundary: tags is None
    assert is_navigable(None) is True


def test_is_navigable_preserves_other_keys():
    # the predicate reads `boat` only; a non-boat non-navigable tag is ignored
    assert is_navigable({"waterway": "canal", "access": "private"}) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingest/test_filters.py -k is_navigable -v`
Expected: FAIL with `ImportError: cannot import name 'is_navigable'`

- [ ] **Step 3: Write minimal implementation**

Append to `pound/ingest/filters.py` (right after the existing `is_derelict`, before `_parse_float`):

```python
_NON_NAVIGABLE_BOAT = {"no", "unsuitable", "canoe"}


def is_navigable(tags: dict[str, str] | None) -> bool:
    """True unless the way is explicitly tagged non-navigable to canal boats.

    OSM `boat` access tag: `no`=prohibited/impassable, `unsuitable`=navigable-
    in-principle-but-not-really, `canoe`=canoe-only (out of scope for a canal-
    boat router). Everything else (`yes`, `private`, `permissive`, `permit`,
    `designated`, `discouraged`, `unknown`, missing, typos) is kept — bad data
    and unknowns fall back to "keep," not silent drop. Literal-string matching
    only; we deliberately do NOT alias typos like `unkmown` -> `unknown`
    (an alias could collide with a future `boat=yes` synonym and drop a real
    navigable edge). Dimensions (`maxwidth` etc.) are a *separate*, plan-time
    concern (`route/cost.py:is_eligible`) and stay untouched here.
    """
    if not tags:
        return True
    return tags.get("boat") not in _NON_NAVIGABLE_BOAT
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingest/test_filters.py -k is_navigable -v`
Expected: PASS (14 parametrized cases + the 2 other functions).

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `uv run pytest tests/ingest/test_filters.py -q`
Expected: PASS; existing filter tests unchanged.

- [ ] **Step 6: Commit**

```bash
git add pound/ingest/filters.py tests/ingest/test_filters.py
git commit -m "feat(ingest): add is_navigable boat-tag predicate"
```

---

### Task 2: `filter_navigable_ways` batch form

**Files:**

- Modify: `pound/ingest/filters.py` (append after `is_navigable`)
- Modify: `tests/ingest/test_filters.py` (extend import + add tests)

**Interfaces:**

- Consumes: `is_navigable` (from Task 1), `pound.ingest.ir.WaterwayFeatures`
- Produces: `filter_navigable_ways(features: WaterwayFeatures) -> WaterwayFeatures` — new `WaterwayFeatures` whose `ways` excludes any way where `is_navigable(way.tags)` is `False`. `nodes` untouched. Input not mutated. *Boat-only filter* — does NOT fold `is_derelict` (that stays inline in the readers; folding would break `test_parse_excludes_derelict` and leak `disused:waterway` ways).

- [ ] **Step 1: Write the failing tests**

Extend the import in `tests/ingest/test_filters.py`:

```python
from pound.ingest.filters import (
    classify_node,
    classify_way,
    extract_dimensions,
    filter_navigable_ways,  # NEW
    is_derelict,
    is_navigable,
)
from pound.ingest.ir import (
    NodeKind,
    WaterwayFeatures,
    WaterwayKind,
    WaterwayNode,
    WaterwayWay,
    WayDimensions,
)
```

Append the tests:

```python
def _way(osm_id, kind, tags=None, geom=None, node_ids=None):
    return WaterwayWay(
        osm_id=osm_id,
        kind=kind,
        name=tags.get("name") if tags else None,
        tags=tags or {},
        node_ids=node_ids or [],
        geometry=geom or [(51.0, -1.0), (51.001, -1.001)],
        dimensions=WayDimensions(),
    )


def _features(ways, nodes=None):
    return WaterwayFeatures(
        ways=ways,
        nodes=nodes or [],
        source="test",
        fetched_at="2026-06-28T00:00:00Z",
        bbox=None,
    )


def test_filter_navigable_ways_drops_boat_no_keeps_yes_and_missing():
    ways = [
        _way(1, WaterwayKind.CANAL, {"waterway": "canal", "boat": "no"}),
        _way(2, WaterwayKind.CANAL, {"waterway": "canal", "boat": "yes"}),
        _way(3, WaterwayKind.CANAL, {"waterway": "canal"}),  # missing boat
    ]
    out = filter_navigable_ways(_features(ways))
    assert [w.osm_id for w in out.ways] == [2, 3]


def test_filter_navigable_ways_drops_unsuitable_and_canoe():
    ways = [
        _way(1, WaterwayKind.CANAL, {"waterway": "canal", "boat": "unsuitable"}),
        _way(2, WaterwayKind.RIVER, {"waterway": "river", "boat": "canoe"}),
        _way(3, WaterwayKind.CANAL, {"waterway": "canal", "boat": "private"}),
    ]
    out = filter_navigable_ways(_features(ways))
    assert [w.osm_id for w in out.ways] == [3]


def test_filter_navigable_ways_drops_lock_yes_with_boat_no():
    # kind-agnostic: a non-navigable lock (tagging contradiction) is not routable
    ways = [
        _way(1, WaterwayKind.LOCK, {"waterway": "canal", "lock": "yes", "boat": "no"}),
        _way(2, WaterwayKind.LOCK, {"waterway": "canal", "lock": "yes", "boat": "yes"}),
    ]
    out = filter_navigable_ways(_features(ways))
    assert [w.osm_id for w in out.ways] == [2]


def test_filter_navigable_ways_does_not_drop_derelict():
    # is_derelict stays inline in the readers; filter_navigable_ways is boat-only.
    # A `disused:waterway=canal` way with `boat=yes` survives here (the reader's
    # inline is_derelict drops it later, but this function must NOT second-guess).
    ways = [
        _way(
            1,
            WaterwayKind.CANAL,
            {"waterway": "canal", "disused:waterway": "canal", "boat": "yes"},
        ),
    ]
    out = filter_navigable_ways(_features(ways))
    assert [w.osm_id for w in out.ways] == [1]


def test_filter_navigable_ways_does_not_mutate_input():
    ways = [
        _way(1, WaterwayKind.CANAL, {"waterway": "canal", "boat": "no"}),
        _way(2, WaterwayKind.CANAL, {"waterway": "canal"}),
    ]
    features = _features(ways)
    original_ids = [w.osm_id for w in features.ways]
    out = filter_navigable_ways(features)
    # input untouched
    assert [w.osm_id for w in features.ways] == original_ids
    # output is a different object with a rebuilt list
    assert out is not features
    assert out.ways is not features.ways


def test_filter_navigable_ways_preserves_nodes():
    ways = [_way(1, WaterwayKind.CANAL, {"waterway": "canal", "boat": "no"})]
    nodes = [
        WaterwayNode(osm_id=99, lat=51.0, lon=-1.0, tags={}, kind=NodeKind.MOORING),
    ]
    out = filter_navigable_ways(_features(ways, nodes=nodes))
    assert out.nodes == nodes
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingest/test_filters.py -k filter_navigable_ways -v`
Expected: FAIL with `ImportError: cannot import name 'filter_navigable_ways'`

- [ ] **Step 3: Write minimal implementation**

Append to `pound/ingest/filters.py` (right after `is_navigable`):

```python
def filter_navigable_ways(features: WaterwayFeatures) -> WaterwayFeatures:
    """Return a new WaterwayFeatures with non-navigable ways (`is_navigable` is
    False) removed from `features.ways`. `nodes` are untouched (infra-node
    pruning is a separate concern handled by `prune_non_navigable_infra`).

    Pure: returns a new WaterwayFeatures; does not mutate the input. Uses
    `model_copy(update=...)` to rebuild the `ways` list — the returned model is
    a shallow copy, but its `ways` list is fresh (the individual `WaterwayWay`
    elements are shared references, which is safe because nothing in `pound/`
    mutates `WaterwayWay` instances post-construction; if a future caller would
    mutate one, switch to a deep copy). `nodes` is the same list reference as
    the input (deliberately — "untouched").

    Boat-only: does NOT fold `is_derelict`. The readers drop derelict ways
    inline in their way loops; that stays. Folding here would break
    `test_parse_excludes_derelict` and leak `disused:waterway` ways.
    """
    kept = [w for w in features.ways if is_navigable(w.tags)]
    return features.model_copy(update={"ways": kept})
```

Add the `WaterwayFeatures` import at the top of `pound/ingest/filters.py` (it imports `NodeKind`, `WaterwayKind`, `WayDimensions` already — extend the import line):

```python
from pound.ingest.ir import NodeKind, WaterwayFeatures, WaterwayKind, WayDimensions
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingest/test_filters.py -k filter_navigable_ways -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Run full filters suite**

Run: `uv run pytest tests/ingest/test_filters.py -q`
Expected: PASS — existing filter tests unchanged.

- [ ] **Step 6: Commit**

```bash
git add pound/ingest/filters.py tests/ingest/test_filters.py
git commit -m "feat(ingest): add filter_navigable_ways batch boat-filter (boat-only; is_derelict stays inline)"
```

---

### Task 3: `prune_non_navigable_infra` post-filter

**Files:**

- Create: `pound/ingest/prune.py`
- Create: `tests/ingest/test_prune.py`

**Interfaces:**

- Consumes: `is_navigable` (from Task 1), `pound.ingest.ir.{WaterwayFeatures, WaterwayWay, NodeKind}`, `pound.ingest.filters.classify_node`
- Produces: `prune_non_navigable_infra(features: WaterwayFeatures) -> WaterwayFeatures` — returns a new `WaterwayFeatures` whose `nodes` list omits any non-`place` classified node that is incident to at least one way AND for which **all** incident ways are non-navigable. `place` nodes always kept. Nodes with **no** incident ways (empty `node_ids`) always kept — definitive navigability can't be determined by join. `ways` untouched. Input not mutated. Effective only when `WaterwayWay.node_ids` is populated (bulk reader); best-effort no-op otherwise.

- [ ] **Step 1: Write the failing tests**

Create `tests/ingest/test_prune.py`:

```python
from pound.ingest.ir import (
    NodeKind,
    WaterwayFeatures,
    WaterwayKind,
    WaterwayNode,
    WaterwayWay,
    WayDimensions,
)
from pound.ingest.prune import prune_non_navigable_infra


def _way(osm_id, kind, tags, geom, node_ids):
    return WaterwayWay(
        osm_id=osm_id,
        kind=kind,
        name=tags.get("name"),
        tags=tags,
        node_ids=node_ids,
        geometry=geom,
        dimensions=WayDimensions(),
    )


def _node(osm_id, kind, tags=None):
    return WaterwayNode(
        osm_id=osm_id,
        lat=51.0 + osm_id / 1000,
        lon=-1.0,
        tags=tags or {"waterway": kind.value} if kind else {},
        kind=kind,
    )


def _features(ways, nodes):
    return WaterwayFeatures(
        ways=ways,
        nodes=nodes,
        source="test",
        fetched_at="2026-06-28T00:00:00Z",
        bbox=None,
    )


def test_lock_gate_on_single_boat_no_way_is_dropped():
    # way 1 carries node 100 at its start; boat=no.
    ways = [
        _way(1, WaterwayKind.CANAL, {"waterway": "canal", "boat": "no"},
             [(51.0, -1.0), (51.001, -1.0)], [100, 101]),
    ]
    nodes = [_node(100, NodeKind.LOCK_GATE)]
    out = prune_non_navigable_infra(_features(ways, nodes))
    assert [n.osm_id for n in out.nodes] == []


def test_lock_gate_on_mixed_boat_no_and_yes_is_kept():
    # node 100 at the shared endpoint of a boat=no way and a boat=yes way
    ways = [
        _way(1, WaterwayKind.CANAL, {"waterway": "canal", "boat": "no"},
             [(51.0, -1.0), (51.001, -1.0)], [100, 101]),
        _way(2, WaterwayKind.CANAL, {"waterway": "canal", "boat": "yes"},
             [(51.001, -1.0), (51.002, -1.0)], [101, 100]),
    ]
    nodes = [_node(100, NodeKind.LOCK_GATE)]
    out = prune_non_navigable_infra(_features(ways, nodes))
    assert [n.osm_id for n in out.nodes] == [100]


def test_lock_gate_on_two_boat_no_and_one_boat_yes_way_is_kept():
    # two non-navigable incidents + one navigable -> still gates traffic -> kept
    ways = [
        _way(1, WaterwayKind.CANAL, {"waterway": "canal", "boat": "no"},
             [(51.0, -1.0), (51.001, -1.0)], [100, 101]),
        _way(2, WaterwayKind.CANAL, {"waterway": "canal", "boat": "no"},
             [(51.002, -1.0), (51.003, -1.0)], [102, 100]),
        _way(3, WaterwayKind.CANAL, {"waterway": "canal", "boat": "yes"},
             [(51.003, -1.0), (51.004, -1.0)], [100, 103]),
    ]
    nodes = [_node(100, NodeKind.LOCK_GATE)]
    out = prune_non_navigable_infra(_features(ways, nodes))
    assert [n.osm_id for n in out.nodes] == [100]


def test_place_node_on_all_boat_no_ways_is_kept():
    # gazetteer anchors survive even when all incidents are non-navigable
    ways = [
        _way(1, WaterwayKind.CANAL, {"waterway": "canal", "boat": "no"},
             [(51.0, -1.0), (51.001, -1.0)], [200, 201]),
    ]
    nodes = [
        WaterwayNode(osm_id=200, lat=51.0, lon=-1.0,
                     tags={"place": "town", "name": "Reading"}, kind=NodeKind.PLACE),
    ]
    out = prune_non_navigable_infra(_features(ways, nodes))
    assert [n.osm_id for n in out.nodes] == [200]


def test_node_with_no_incident_ways_is_kept():
    # Overpass path: empty/wrong node_ids -> node has zero incidents -> kept (no-op)
    ways = [
        _way(1, WaterwayKind.CANAL, {"waterway": "canal", "boat": "no"},
             [(51.0, -1.0), (51.001, -1.0)], []),  # empty node_ids (out geom)
    ]
    nodes = [_node(300, NodeKind.LOCK_GATE)]
    out = prune_non_navigable_infra(_features(ways, nodes))
    assert [n.osm_id for n in out.nodes] == [300]


def test_way_with_missing_boat_tag_counts_as_navigable():
    # a way with no `boat` key is navigable -> its sole lock_gate is kept
    ways = [
        _way(1, WaterwayKind.CANAL, {"waterway": "canal"},
             [(51.0, -1.0), (51.001, -1.0)], [400, 401]),
    ]
    nodes = [_node(400, NodeKind.LOCK_GATE)]
    out = prune_non_navigable_infra(_features(ways, nodes))
    assert [n.osm_id for n in out.nodes] == [400]


def test_node_with_own_boat_no_tag_is_not_dropped_by_node_tag():
    # node-level `boat=no` is IGNORED -- prune uses incident-way tags only
    ways = [
        _way(1, WaterwayKind.CANAL, {"waterway": "canal", "boat": "yes"},
             [(51.0, -1.0), (51.001, -1.0)], [500, 501]),
    ]
    nodes = [
        WaterwayNode(osm_id=500, lat=51.0, lon=-1.0,
                     tags={"waterway": "lock_gate", "boat": "no"},
                     kind=NodeKind.LOCK_GATE),
    ]
    out = prune_non_navigable_infra(_features(ways, nodes))
    assert [n.osm_id for n in out.nodes] == [500]  # kept -- its incident is navigable


def test_prune_does_not_mutate_input():
    ways = [
        _way(1, WaterwayKind.CANAL, {"waterway": "canal", "boat": "no"},
             [(51.0, -1.0), (51.001, -1.0)], [100, 101]),
    ]
    nodes = [_node(100, NodeKind.LOCK_GATE)]
    features = _features(ways, nodes)
    out = prune_non_navigable_infra(features)
    assert out is not features
    assert out.nodes is not features.nodes
    # input untouched
    assert [n.osm_id for n in features.nodes] == [100]


def test_prune_preserves_ways():
    # ways are NEVER touched by prune (the way filter is a separate function)
    ways = [
        _way(1, WaterwayKind.CANAL, {"waterway": "canal", "boat": "no"},
             [(51.0, -1.0), (51.001, -1.0)], [100, 101]),
        _way(2, WaterwayKind.RIVER, {"waterway": "river"},
             [(51.01, -1.0), (51.02, -1.0)], [101, 102]),
    ]
    nodes = [_node(100, NodeKind.LOCK_GATE)]
    features = _features(ways, nodes)
    out = prune_non_navigable_infra(features)
    assert [w.osm_id for w in out.ways] == [1, 2]  # both ways survive prune
    assert [n.osm_id for n in out.nodes] == []  # but the lock_gate on boat=no drops
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingest/test_prune.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pound.ingest.prune'`

- [ ] **Step 3: Write minimal implementation**

Create `pound/ingest/prune.py`:

```python
"""Infra-node prune: drop lock_gate/lock/mooring/movable_bridge/marina nodes
sitting *entirely* on non-navigable ways.

Pure: takes WaterwayFeatures, returns a new WaterwayFeatures with affected
nodes removed. `place` nodes are never removed (gazetteer relevance is
independent of waterway navigability). `ways` are never touched here.

Effective only when `WaterwayWay.node_ids` is populated (the pyosmium bulk
reader fills it). On the Overpass `out geom` path `node_ids` is empty on real
data, so no node is incident to any way and the function runs without dropping
(best-effort, not a silent drop — see the spec's bulk-effectiveness caveat).
"""

from pound.ingest.filters import classify_node, is_navigable
from pound.ingest.ir import NodeKind, WaterwayFeatures


def prune_non_navigable_infra(features: WaterwayFeatures) -> WaterwayFeatures:
    """Return a new WaterwayFeatures with infra nodes sitting entirely on
    non-navigable ways removed. `place` nodes are never removed.

    A non-`place` classified node is dropped iff (a) it is incident to at least
    one way via `WaterwayWay.node_ids` AND (b) every incident way is
    non-navigable (`is_navigable(tags) is False`). A node with no incident ways
    is kept (the post-filter cannot determine navigability by join — that is the
    Overpass no-op case).
    """
    # osm node id (str) -> set of incident way osm_ids
    incidents: dict[str, set[int]] = {}
    for w in features.ways:
        if not w.node_ids:
            continue
        for nid in w.node_ids:
            incidents.setdefault(str(nid), set()).add(w.osm_id)
    ways_by_id = {w.osm_id: w for w in features.ways}

    def _should_drop(node) -> bool:
        kind = classify_node(node.tags) if node.kind is None else node.kind
        # Defensive: handle any future NodeKind.OTHER (or new kinds) the same as
        # infra -- only PLACE is unconditionally kept. classify_node never emits
        # OTHER today, so this branch is forward-compat, not exercised yet.
        if kind is None or kind == NodeKind.PLACE:
            return False
        inc = incidents.get(str(node.osm_id))
        if not inc:
            return False  # no incidents -> kept (Overpass no-op case)
        # all incidents must be non-navigable; if any is navigable/untagged -> keep
        navigable_seen = False
        for wid in inc:
            w = ways_by_id.get(wid)
            if w is not None and is_navigable(w.tags):
                navigable_seen = True
                break
        return not navigable_seen

    kept_nodes = [n for n in features.nodes if not _should_drop(n)]
    return features.model_copy(update={"nodes": kept_nodes})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingest/test_prune.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Run the full ingest test suite to confirm no regressions**

Run: `uv run pytest tests/ingest/ -q`
Expected: PASS — existing tests untouched (prune is not wired into readers yet).

- [ ] **Step 6: Commit**

```bash
git add pound/ingest/prune.py tests/ingest/test_prune.py
git commit -m "feat(ingest): add prune_non_navigable_infra node post-filter"
```

---

### Task 4: Wire prune → filter chain into both readers

**Files:**

- Modify: `pound/ingest/overpass.py:fetch_oxford` (~line 129)
- Modify: `pound/ingest/osm.py:read_england` (~line 127)
- Modify: `tests/ingest/test_overpass.py` (add chain test that monkeypatches `fetch_raw`)
- Modify: `tests/ingest/test_osm.py` (add `read_england` chain test; monkeypatches `run_tags_filter`)

**Interfaces:**

- Consumes: `filter_navigable_ways` (Task 2), `prune_non_navigable_infra` (Task 3)
- Produces: `fetch_oxford()` / `read_england()` now return chain-processed features. `parse()` / `read_pbf()` unchanged (still return the full features with inline `is_derelict` applied).

- [ ] **Step 1: Write the failing tests**

Append to `tests/ingest/test_overpass.py`:

```python
def test_fetch_oxford_applies_prune_then_filter_chain(monkeypatch):
    """fetch_oxford wraps parse() output with prune -> filter_navigable_ways.
    parse() itself stays pure. We monkeypatch fetch_raw (the network call) so
    the chain runs on a fixture without hitting live Overpass."""
    from pound.ingest import overpass
    from pound.ingest.ir import WaterwayKind, WaterwayNode
    from tests.fixtures import oxford_fixture_path
    import json

    raw = json.loads(Path(oxford_fixture_path()).read_text())
    # inject a boat=no way into the fixture's elements (so the filter has work to do)
    boat_no_way = {
        "type": "way",
        "id": 9999,
        "tags": {"waterway": "canal", "boat": "no"},
        "geometry": [{"lat": 51.7510, "lon": -1.2600}, {"lat": 51.7520, "lon": -1.2600}],
    }
    raw["elements"].append(boat_no_way)
    monkeypatch.setattr(overpass, "fetch_raw", lambda **_: raw)

    features = overpass.fetch_oxford()
    # the boat=no way must be gone
    assert 9999 not in {w.osm_id for w in features.ways}
    # fixture's original ways are all navigable (no boat tag) -> all survive
    assert all(w.osm_id != 9999 for w in features.ways)
    # fetch_oxford still returns a WaterwayFeatures
    assert features.source == "overpass"
```

Append to `tests/ingest/test_osm.py` (note: this module already carries `pytestmark = pytest.mark.bulk`):

```python
def test_read_england_applies_prune_then_filter_chain(monkeypatch, tmp_path):
    """read_england wraps read_pbf output with prune -> filter_navigable_ways.
    read_pbf itself is unchanged. We monkeypatch run_tags_filter (which shells
    out to the osmium CLI) to copy a fixture PBF to out_pbf instead."""
    import shutil
    from pound.ingest import osm

    # the existing tiny_bulk.osm fixture has no boat=no ways; build one in tmp
    # by adding a boat=no way to a copy of tiny_bulk.osm, then patching
    # run_tags_filter to copy it straight to the out path.
    # Simplest: use tiny_bulk.osm itself as the "filtered" output, then assert
    # the read_england output equals read_pbf output (no boat=no ways to drop).
    fixture_filtered = _tiny_pbf_path()

    def fake_run_tags_filter(in_pbf, out_pbf):
        shutil.copy(fixture_filtered, out_pbf)

    monkeypatch.setattr(osm, "run_tags_filter", fake_run_tags_filter)

    # also patch osm.pbf default to point at a throwaway so the Path(osm.environ...)
    # resolution doesn't matter -- read_england resolves pbf_path from args/env;
    # pass tmp_path / "stub.osm.pbf", the patched run_tags_filter ignores it
    stub_pbf = tmp_path / "stub.osm.pbf"
    stub_pbf.touch()

    out = osm.read_england(stub_pbf)
    # read_pbf(tiny_bulk.osm) yields 3 routable ways + place/lock_gate nodes;
    # without any boat=no ways, prune + filter leave them unchanged.
    direct = osm.read_pbf(_tiny_pbf_path())
    assert {w.osm_id for w in out.ways} == {w.osm_id for w in direct.ways}
    assert {n.osm_id for n in out.nodes} == {n.osm_id for n in direct.nodes}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest --run-bulk tests/ingest/test_overpass.py::test_fetch_oxford_applies_prune_then_filter_chain tests/ingest/test_osm.py::test_read_england_applies_prune_then_filter_chain -v`
Expected: FAIL — `fetch_oxford` returns the boat=no way 9999 (chain not wired); the bulk test fails if `read_england` doesn't apply the chain (today it just returns `read_pbf(filtered)`, so the assertion holds trivially for the fixture that has no boat=no — but the test exercises the *wiring*; wiring won't be present until step 3, so an assertion on the chain's *presence* should fail first. If both pass trivially because the fixture has no boat=no, add an assertion that the chain functions were called). To make failure-mode observable, also assert wiring by monkeypatching the chain functions to no-ops that record calls:

```python
# extend test_read_england_applies_prune_then_filter_chain:
    called = {"prune": 0, "filter": 0}

    def spy_prune(features):
        called["prune"] += 1
        return features

    def spy_filter(features):
        called["filter"] += 1
        return features

    monkeypatch.setattr(osm, "prune_non_navigable_infra", spy_prune)
    monkeypatch.setattr(osm, "filter_navigable_ways", spy_filter)
    osm.read_england(stub_pbf)
    assert called == {"prune": 1, "filter": 1}
```

(Add the same spy pattern to the Overpass test, patching `overpass.prune_non_navigable_infra` / `overpass.filter_navigable_ways`.)

Run: `uv run pytest --run-bulk tests/ingest/test_overpass.py::test_fetch_oxford_applies_prune_then_filter_chain tests/ingest/test_osm.py::test_read_england_applies_prune_then_filter_chain -v`
Expected: FAIL — `AttributeError: module 'pound.ingest.osm' has no attribute 'prune_non_navigable_infra'` (not imported yet).

- [ ] **Step 3: Wire the chain into both readers**

Edit `pound/ingest/overpass.py`:

Add imports near the top:

```python
from pound.ingest.filters import filter_navigable_ways
from pound.ingest.prune import prune_non_navigable_infra
```

Edit `fetch_oxford` (currently `return parse(raw["elements"], OXFORD_BBOX, osm_timestamp=osm_timestamp)`):

```python
def fetch_oxford() -> WaterwayFeatures:
    raw = fetch_raw()
    osm_timestamp = raw.get("osm3s", {}).get("timestamp_osm_base")
    features = parse(raw["elements"], OXFORD_BBOX, osm_timestamp=osm_timestamp)
    # prune BEFORE filter: prune needs boat=no ways present to decide
    # "all incidents non-navigable"; see the spec's load-bearing ordering note.
    features = prune_non_navigable_infra(features)
    features = filter_navigable_ways(features)
    return features
```

`parse()` stays untouched.

Edit `pound/ingest/osm.py`:

Add imports near the top:

```python
from pound.ingest.filters import filter_navigable_ways
from pound.ingest.prune import prune_non_navigable_infra
```

Edit `read_england` (currently `return read_pbf(filtered)`):

```python
def read_england(pbf_path: Path | None = None) -> WaterwayFeatures:
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
```

`read_pbf()` stays untouched.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest --run-bulk tests/ingest/test_overpass.py::test_fetch_oxford_applies_prune_then_filter_chain tests/ingest/test_osm.py::test_read_england_applies_prune_then_filter_chain -v`
Expected: PASS (the chain is wired; the spies confirm call order).

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `uv run pytest -q`
Expected: PASS — `130` family (now grown with new tests); the `test_parse_excludes_derelict` and `test_read_pbf_*` tests still pass because `parse` and `read_pbf` are unchanged.

- [ ] **Step 6: Commit**

```bash
git add pound/ingest/overpass.py pound/ingest/osm.py tests/ingest/test_overpass.py tests/ingest/test_osm.py
git commit -m "feat(ingest): wire prune -> filter chain into fetch_oxford and read_england"
```

---

### Task 5: Phase 3 grid-bucket spatial index (perf refactor)

**Files:**

- Modify: `pound/graph/build.py` — Phase 3 candidate loop (the `tips = ...` / `for tip in tips:` / `for other in g.nodes():` block ~lines 190-205)
- Modify: `tests/graph/test_build_bulk.py` — add relative-speedup perf test

**Interfaces:**

- Consumes: `_haversine_m`, `_node_key` (already in `build.py`), `tolerance_m` build param
- Produces: same candidate list + `used`/`unresolved` outputs; identical selection logic; new `tolerance_m <= 0` short-circuit that skips Phase 3 entirely (no candidates, no grid).

Implementation plan for the grid:

- Cell size: `cell_deg = tolerance_m / 111_320` (1° lat ≈ 111.32 km). Bucket key `(int((lat+90)/cell_deg), int((lon+180)/cell_deg))`.
- Build a `dict[(cy, cx), list[node_key]]` once over all nodes.
- For each tip: look up its cell + 8 Moore neighbours, collect candidate node keys, apply the *exact* haversine `0 < d <= tolerance_m` filter, pick the strict-min (first-seen-wins on exact ties by iterating candidates in sorted order).

- [ ] **Step 1: Write the failing test**

Append to `tests/graph/test_build_bulk.py`:

```python
def test_phase3_grid_bucket_preserves_snap_results_and_is_sub_linear():
    """Phase 3's grid-bucket refactor must produce the same snap set as the
    all-pairs scan, and must complete in < 5% of the equivalent all-pairs time
    on a 3000-tip synthetic graph. Coords use >=4 decimal places (distinct
    distances -> no exact sub-metre ties -> deterministic selection)."""
    import time
    from pound.graph.build import build_graph

    # 3000 disjoint chain tips, each 0.500 m from a target junction tip.
    # That's ~6000 nodes; the all-pairs O(tips x nodes) path is several seconds.
    ways = []
    # make 3000 short canals: tipA -> junction -> junction -> tipB, with tipA
    # 0.5 m from tipB (cross snap). Use 4-decimal lat for distinct distances.
    for i in range(3000):
        base_lat = 51.0000 + i * 0.001  # 4-decimal -> ~111 m per i
        lon = -1.0000
        # tipA at (base_lat, lon), a chain tip; tipB at base_lat + 0.0000045 (~0.5 m N)
        # -- within 1 m tolerance, no exact tie.
        tip_a_lat = round(base_lat, 7)
        tip_b_lat = round(base_lat + 0.0000045, 7)
        ways.append(
            _way(
                100 + i * 10, WaterwayKind.CANAL, f"A{i}", [1, 2],
                [(tip_a_lat, lon), (round(base_lat + 0.0000900, 7), lon)],
            )
        )
        # the target end of a second canal whose tip is tip_b_lat
        ways.append(
            _way(
                200 + i * 10, WaterwayKind.CANAL, f"B{i}", [3, 4],
                [(round(base_lat - 0.0000900, 7), lon), (tip_b_lat, lon)],
            )
        )

    start = time.perf_counter()
    g = build_graph(_features(ways), tolerance_m=1.0)
    elapsed = time.perf_counter() - start

    # Sufficient snaps fired: at least 1500 (one per i; tip->tip pairs collapse).
    assert len(g.graph["tolerance_snaps_used"]) >= 1500
    # Perf: this should be well under a second on any modern machine. Generous
    # ceiling (the all-pairs path was multi-second on 6000 nodes).
    assert elapsed < 2.0, f"Phase 3 took {elapsed:.2f}s — grid not sub-linear"
```

Add `import time` at the top of the test file if not already present.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/graph/test_build_bulk.py::test_phase3_grid_bucket_preserves_snap_results_and_is_sub_linear -v`
Expected: FAIL — `assert elapsed < 2.0` will be False (today's all-pairs scan takes > 2s on ~6000 nodes; the snap-count assertion may pass, but the perf assertion fails).

If the perf assertion passes too easily (a fast machine), lower the ceiling or grow the fixture. The point is to catch a regression to all-pairs. Document the chosen ceiling in the commit message.

- [ ] **Step 3: Implement the grid-bucket refactor**

Edit `pound/graph/build.py` — replace the `tips = [...]` / `for tip in tips:` / inner `for other in g.nodes():` block. The new shape:

```python
    # --- Phase 3: tolerance-snap candidates for dangling tips, via a grid-bucket
    # spatial index (replaces the O(tips x nodes) all-pairs haversine scan).
    # Short-circuit: tolerance_m <= 0 means snaps are OFF (existing tests rely on
    # this). Today's `d > tolerance_m` guard already rejects everything for
    # tolerance_m == 0; we short-circuit so the grid formula (cell_deg = tol /
    # 111_320) does not divide by zero, and we skip the work entirely for tol<0.
    unresolved: list[tuple] = []
    used: list[tuple] = []

    def _incident_way_ids(key):
        return {d["osm_way_id"] for _, _, d in g.edges(key, data=True)}

    if tolerance_m <= 0:
        # No candidates -> phase 3 is a no-op. Fall through to the join-override
        # beyond-tolerance loop below without building the grid.
        candidates: list[tuple[tuple, tuple, int, int]] = []
    else:
        cell_deg = tolerance_m / 111_320.0

        def _cell(lat: float, lon: float) -> tuple[int, int]:
            return (int((lat + 90.0) / cell_deg), int((lon + 180.0) / cell_deg))

        # bin every node by its grid cell
        grid: dict[tuple[int, int], list[tuple]] = {}
        for n in g.nodes():
            grid.setdefault(_cell(n[0], n[1]), []).append(n)

        tips = [n for n in g.nodes() if g.degree(n) == 1]
        candidates = []
        for tip in tips:
            nbr = next(iter(g[tip]))  # sole neighbor — never a snap target
            cy, cx = _cell(tip[0], tip[1])
            best, best_d, best_w = None, math.inf, -1
            # scan this cell + 8 Moore neighbours
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    bucket = grid.get((cy + dy, cx + dx))
                    if not bucket:
                        continue
                    # iterate bucket contents in a deterministic order (the list
                    # is in graph insertion order; sorting it would change tie
                    # breaks relative to today's all-pairs). We keep insertion
                    # order to match today's `g.nodes()` iteration as closely as
                    # possible on real (non-tied) data.
                    for other in bucket:
                        if other == tip or other == nbr:
                            continue
                        d = _haversine_m(tip, other)
                        if d <= 0.0 or d > tolerance_m or d >= best_d:
                            continue
                        best, best_d, best_w = other, d, next(iter(_incident_way_ids(other)))
            if best is not None:
                candidates.append(
                    (tip, best, next(iter(_incident_way_ids(tip))), best_w)
                )

    # Dedupe symmetric candidates (unchanged).
    seen_pairs: set[tuple] = set()
    uniq = []
    for tip, target, wa, wb in candidates:
        pair = tuple(sorted((tip, target)))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        uniq.append((tip, target, wa, wb))

    for ka, kb, wa, wb in uniq:
        if tuple(sorted((str(wa), str(wb)))) in split_pairs:
            overrides_applied += 1
            continue
        if g.has_edge(ka, kb):
            unresolved.append((ka, kb))
            continue
        _contract(g, [{ka, kb}], [])
        used.append((ka, kb))
        survivor = ka if ka in g else kb
        ids = g.nodes[survivor].get("osm_node_ids", set())
        confirmed = bool(ids) and any(ia in ids and ib in ids for ia, ib in join_pairs)
        if confirmed:
            overrides_applied += 1
        else:
            unresolved.append((ka, kb))
```

The `for join override ... connect beyond-tolerance gap` loop below this block is unchanged (it already handles `tolerance_m <= 0` by skipping via `_key_for_osm_id` lookups).

Note: keep the `g.graph["tolerance_snaps_used"] = used`, etc. assignments exactly as they were.

- [ ] **Step 4: Run the perf test to verify it passes**

Run: `uv run pytest tests/graph/test_build_bulk.py::test_phase3_grid_bucket_preserves_snap_results_and_is_sub_linear -v`
Expected: PASS — snap count ≥ 1500 AND `elapsed < 2.0`.

- [ ] **Step 5: Run the whole Phase-3 test surface to confirm behaviour preservation**

Run: `uv run pytest tests/graph/test_build_bulk.py tests/graph/test_build.py tests/validate/ -q`
Expected: PASS — all existing Phase 3 tests (snap joins tip to junction; `split` override suppresses; beyond-tolerance not a candidate; the Oxford pendant case; duplicate-edge-as-unresolved; `tolerance_m=0.0` snaps-off tests at lines ~59, 76, 105) pass unchanged.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — full hermetic suite green, new perf test green.

- [ ] **Step 7: Commit**

```bash
git add pound/graph/build.py tests/graph/test_build_bulk.py
git commit -m "perf(graph): Phase 3 grid-bucket spatial index; short-circuit tolerance_m<=0 (issue #2)"
```

---

### Task 6: Live England verification (manual, human-gated)

This is the human-gated check from the spec's Done-when. It is **not** TDD (no failing-test step) — it's the verification that the rebuilt `england.pkl` has the expected character. Run after the hermetic suite is green.

**Files:** none modified.

- [ ] **Step 1: Confirm the hermetic suite is green**

Run: `uv run pytest -q`
Expected: PASS — every test including new ones from Tasks 1-5 (filters, prune, reader chain, Phase 3 perf).

- [ ] **Step 2: Confirm the `bulk`-marked tests are green (if the bulk extra is installed)**

Run: `uv run pytest --run-bulk -q`
Expected: PASS for the bulk-specific tests (or SKIP if the `bulk` extra is absent — that is the documented gating, not a failure).

- [ ] **Step 3: Regenerate `england.pkl`**

Prereq: `england.osm.pbf` at `pound/data/england.osm.pbf` (the live-testing doc §0.4 explains the download; the URL is `https://download.geofabrik.de/europe/united-kingdom/england-latest.osm.pbf`). Prereq: `osmium-tool` on PATH (live-testing §0.2). Prereq: `uv sync --extra bulk` (live-testing §0.3).

Run:

```bash
uv run pound-ingest build england --out /tmp/england.pkl --tolerance-m 1
```

Expected:

- `osmium tags-filter` runs (now idempotent — `--overwrite` from commit `f1cdd20`).
- The build prints a JSON validation report to stdout.
- The build exits `0` and writes `/tmp/england.pkl`, **OR** exits non-zero with `BUILD FAILED: tolerance_snaps_unresolved=N` on stderr if there are residual genuine curation items (the `boat=no` noise from before should be gone — see Step 4).

- [ ] **Step 4: Inspect the report from Step 3**

The validation report (Step 3 stdout) should show (compared to the pre-fix baseline):

- `derelict_edges == 0` (unchanged)
- `self_loops == 0` (the closed-ring fix from commit `f1cdd20`)
- `total_edges` / `total_nodes` materially smaller — the 5343 `boat=no` ways are gone
- `tolerance_snaps_unresolved` contains only genuine items (the 6-snaps baseline from `f8b3b36` testing was 5 of 6 caused by `boat=no`; those should now be gone, leaving few or zero items at `--tolerance-m 1`)
- `orphans_lock_ways` / `orphan_lock_nodes` **may have grown** (advisory, not a gate — documented in the spec): dropping `boat=no` lock ways makes them orphan from `attach_locks`'s perspective.

If the gate passes (exit 0), verify the artifact:

```bash
uv run python -c "
import pickle
g, m = pickle.load(open('/tmp/england.pkl', 'rb'))
v = m['validation']
print('self_loops:', v['self_loops'])
print('derelict_edges:', v['derelict_edges'])
print('total_edges:', v['total_edges'])
print('component_count:', v['component_count'])
print('tolerance_snaps_unresolved:', len(v['tolerance_snaps_unresolved']))
"
```

- [ ] **Step 5: Record the result**

Append a "Live verification" entry to `progress.md` under the appropriate section: the `component_count` order of magnitude (the spec's human-read fragmentation signal — thousands ⇒ needs curation; ~a dozen ⇒ plausibly genuine), whether the gate passed at `--tolerance-m 1`, and any residual `tolerance_snaps_unresolved` items that need curation in `pound/data/overrides.json`.

No commit to `england.pkl` (it lives outside the repo per `.gitignore`).

---

## Spec self-review

**1. Spec coverage:**

| Spec section | Implemented by |
|---|---|
| §1 Way boatability filter (predicate, blacklist, ordering, is_derelict stays inline) | Task 1, Task 2, Task 4 |
| §2 Infra-node post-filter (prune module, drop rule, place kept, defensive OTHER, Overpass no-op) | Task 3, Task 4 |
| §3 Phase 3 grid-bucket perf (no scipy, deterministic tie-break, `tolerance_m<=0` short-circuit) | Task 5 |
| Done-when: hermetic green, new tests, England regeneration (derelict==0, self_loops==0, snap queue is genuine-only, advisory orphan_lock growth) | Task 6 |
| Done-when: `orphan_lock_ways` character change acceptable | Task 6 Step 4 (inspected, not gated) |

All sections covered. No spec requirement is unimplemented.

**2. Placeholder scan:**

No "TBD", "TODO", "implement later", "add error handling", or "write tests for the above". Every step contains complete code.

**3. Type consistency:**

- `is_navigable(tags: dict[str,str] | None) -> bool` — Task 1 defines; Tasks 2, 3 consume; signature matches.
- `filter_navigable_ways(features: WaterwayFeatures) -> WaterwayFeatures` — Task 2 defines; Task 4 consumes; signature matches.
- `prune_non_navigable_infra(features: WaterwayFeatures) -> WaterwayFeatures` — Task 3 defines; Task 4 consumes; signature matches.
- `_NON_NAVIGABLE_BOAT = {"no", "unsuitable", "canoe"}` — Task 1 defines; Tasks 2, 3 read via `is_navigable` only (no direct access — DRY).
- `NodeKind.PLACE`, `NodeKind.LOCK_GATE`, `WaterwayKind`, `WaterwayFeatures`, `WaterwayWay`, `WaterwayNode` — all from `pound.ingest.ir`, verified to exist at the cited locations.

No type drift.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-28-boatability-filter-and-phase3-perf.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
