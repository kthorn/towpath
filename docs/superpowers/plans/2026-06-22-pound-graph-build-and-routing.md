# Pound — Graph Build, Cost Model & Point-to-Point Routing (Scope C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Oxford `WaterwayFeatures` IR (from Scope B) into a noded, connected NetworkX graph; implement the lock-aware cost model; replace the `plan_route()` stub with a real point-to-point shortest-path routing over a serialized graph artifact; honor the frozen `days`/`hours_per_day` contract with trivial cumulative-minute day chunking; and add build-time graph validation — producing a real computed `RouteResult` over the curated fixture, stopping before mooring-aware day placement, rings, amenities, and full-GB scale.

**Architecture:** The offline build (`graph/build.py` → `graph/locks.py` → `validate/connectivity.py` → `graph/artifact.py`) turns `WaterwayFeatures` into a NetworkX `Graph` whose nodes are coordinate keys and whose edges are "pounds" carrying `length_m`, restrictive dims, lock count, and geometry. The request-time path (`route/cost.py` → `route/snap.py` → `route/plan.py`) loads the artifact once, snaps named places to graph nodes via an offline gazetteer built from `place=*` nodes, filters edges by boat dimensions, runs Dijkstra by time-cost, and assembles a `RouteResult`. The cost model is the single source of truth for `est_minutes` and is shared by the planner and the structural-invariant tests (design §7.2). Connectivity is derived from **shared endpoint coordinates** (the Overpass `out geom` reader leaves `node_ids` empty); this works on the hand-curated fixture and is documented as a bulk-path limitation.

**Tech Stack:** Python 3.12+, Pydantic v2, NetworkX (new), pytest, ruff. No shapely/rtree/pyosmium yet — haversine is pure-Python and nearest-node is linear at fixture scale (YAGNI; deferred to the scale scope per design §10). `requests` stays offline-ingest-only; the request-time path remains pure-Python, no network.

## Open questions (resolved as below — flag to user before execution)

These are the decisions baked into the plan. Each is flagged so the user can veto
before execution; vetoing OQ-1 or OQ-2 materially reshapes tasks 6–8.

- **OQ-1 — Place resolution.** `CanalConstraints.start/end` are strings; the
  fixture has no named place endpoints. **Resolution:** extend the Oxford
  fixture with two `place=*` nodes at the chain endpoints, add `NodeKind.PLACE`
  - a `classify_node` branch for `place=*`, and build an offline gazetteer from
  `PLACE` nodes → nearest graph node (design §5.1 "offline gazetteer, network-
  free"). Keeps the frozen schema untouched. Alternative (defer place
  resolution, test with coordinate-key strings) is rejected because it would
  require changing `CanalConstraints` field types or testing around the contract.
- **OQ-2 — Stub replacement.** The real `plan_route` **replaces** the stub. The
  existing `test_plan_stub.py` hardcoded Oxford→Heyford assertions are rewritten
  to assert §7.2 structural invariants over the real fixture-derived route
  (Task 8). The stub's hardcoded amenity/leg values are retired. Confirm this is
  intended vs. keeping the stub as a parallel reference.
- **OQ-3 — Connectivity via coordinate equality.** Overpass `out geom` leaves
  `node_ids` empty, so graph build joins way-ends by exact `(lat, lon)` float
  equality (rounded to 7 decimals). This works on the curated fixture (hand-
  matched endpoints) but **will not** on raw/bulk data, which needs tolerance-
  snap — deferred to the bulk-path scope. Documented in `build.py` docstring.
- **OQ-4 — Dependencies.** Adds `networkx>=3` (spec'd, design §4.2). Defers
  `shapely`, `rtree`/`shapely.STRtree`, `pyosmium` — not needed at fixture scale
  (haversine is pure-Python; nearest-node is linear). Confirm deferring is
  acceptable.
- **OQ-5 — Artifact format.** Pickle (spec'd, design §4.4) for the NetworkX
  graph + a metadata dict (`source`, `fetched_at`, `built_at`, `version`). The
  artifact is **gitignored** (like `pound/data/`); tests build it from the
  fixture in a tmp path via `mktemp`. Pickle is not a long-term portable format;
  revisit at the scale scope. Confirm.
- **OQ-6 — Lock-counting semantics (revised after live-OSM check).** Verified
  against real UK staircases (Bingley Five Rise, Foxton) via Overpass: chambers
  are tagged `waterway=canal` + `lock=yes` **ways**, one way per chamber —
  **zero** `waterway=lock` ways and **zero** `lock=yes` nodes at both sites.
  The chambers chain end-to-end by shared coordinates (verified: Bingley's 5
  chambers form one connected component via 4 shared endpoints), so each
  chamber becomes its own graph edge. **Semantics:** a LOCK-kind edge (a way
  classified `WaterwayKind.LOCK` — either `waterway=lock` or `lock=yes` on any
  waterway way) counts as **1 lock**; a `lock=yes` **node** on/within tolerance
  of a non-LOCK edge increments that edge's lock count (per-node, for the
  rarer long-pound-with-lock-node pattern — defensive, unverified in the wild);
  `waterway=lock_gate` nodes/ways are recorded as gate metadata but do **not**
  increment the lock count; orphans are reported, not silently dropped.
  Idempotency (per-edge `max(locks, 1)`) is correct given the real topology —
  each chamber is its own edge, so 5 chambers → 5 edges → 5 locks. **Bug found
  & fixed in Task 3:** Scope B's `classify_way` checks `waterway` before
  `lock=yes`, so a `waterway=canal` + `lock=yes` chamber is classified `CANAL`
  and the lock signal is dropped at the IR level — a whole staircase would
  count as 0 locks. Task 3 fixes `classify_way` (check `lock=yes` first) and
  adds a 3-chamber staircase fixture + test to prove the count.
- **OQ-7 — Scope boundary.** Point-to-point only. `end is None` (ring / round
  trip) raises `NotImplementedError("rings not yet supported")`. **Day budgeting
  is trivial cumulative-minute chunking NOW (Scope C):** legs are packed
  greedily into consecutive `DayPlan`s where each day's `cruising_minutes ≤
  hours_per_day*60`, emitting as many non-empty days as the route needs (NOT
  padded to `constraints.days` — trailing empty days are noise; see OQ-8).
  Mooring-aware "end near winding hole" placement (§5.3) is deferred to Scope D
  with amenities, where §9 step 7 originally grouped it. Rings are out of scope.
  Amenities (§5.4) and the external oracle (§8) are out of scope. Build-time
  validation (§7.1) **is** in scope.
- **OQ-8 — Day-count semantics.** When `constraints.days > 1` but the route is
  shorter than the budget allows (the Oxford case: ~7 min total), `plan_route`
  emits **only as many non-empty `DayPlan`s as the route needs** — no empty
  padding to reach `days`. `constraints.days` is treated as a *maximum* day
  count, not an exact count. Confirmed by the user. (The alternative — exactly
  `days` plans with trailing empty ones — was rejected as noise; revisit if a
  downstream consumer needs "day 3 of 3" indexing.)

## Global Constraints

- Python 3.12+ (use `uv` for env/dep management).
- `requests` is offline-ingest ONLY — never imported on the request-time path. Request-time path (`schemas`, `route/*`, `plan`) stays pure-Python, no network, no LLM. `networkx` is allowed on **both** paths (it's a pure-Python in-memory lib, no network).
- All cost constants live in one place: `pound/route/cost.py` (moved from the stub `plan.py`). The stub and the real planner both import from there; structural-invariant tests import the same constants (design §7.2).
- OSM is ODbL: attribution + share-alike. The fixture already carries the `osm3s.copyright` note; the artifact metadata records `source` + `fetched_at` for provenance (`graph_source_date` flows into `RouteResult`).
- Keep the full GB extract and built artifacts OUT of the repo (`.gitignore` `pound/data/`, `pound/artifacts/`); ship only the small curated fixture under `tests/fixtures/`. Artifact tests use `mktemp` paths (per AGENTS.md — never reuse fixed temp paths).
- Network tests skipped by default (`--run-network` / `RUN_NETWORK=1`); no new network tests in this scope.
- Per AGENTS.md: GitHub Actions pinned by SHA (N/A — no GH Actions yet), temp files via `mktemp`, conventional-style commit messages.
- TDD: write the failing test first, run it, implement minimal code, run it, commit. Ruff clean at every commit. `uv run pytest -q` green at every commit.

## File Structure

```
pound/
├── pyproject.toml                  # MODIFY: add networkx>=3
├── .gitignore                      # MODIFY: add pound/artifacts/
├── pound/
│   ├── route/                      # NEW package
│   │   ├── __init__.py
│   │   ├── cost.py                 # cost constants + time_min + is_eligible (pure)
│   │   ├── snap.py                 # offline gazetteer from PLACE nodes + snap_place
│   │   └── plan.py                 # MOVE from pound/plan.py; real plan_route
│   ├── graph/                      # NEW package
│   │   ├── __init__.py
│   │   ├── build.py                # WaterwayFeatures -> nx.Graph (coordinate-keyed)
│   │   ├── locks.py                # attach lock counts to edges; orphan report
│   │   └── artifact.py             # save_artifact / load_artifact (pickle + metadata)
│   ├── validate/                   # NEW package
│   │   ├── __init__.py
│   │   └── connectivity.py         # build-time validation report -> dict
│   ├── ingest/
│   │   ├── ir.py                   # MODIFY: add NodeKind.PLACE
│   │   └── filters.py              # MODIFY: classify_node handles place=*; classify_way checks lock=yes first (Task 3 fix)
│   └── plan.py                     # DELETE (moved to route/plan.py)
├── tests/
│   ├── fixtures/
│   │   ├── oxford_overpass_sample.json   # MODIFY: add two place=* endpoint nodes
│   │   └── staircase_overpass_sample.json # NEW: 3-chamber staircase (canal+lock=yes ways)
│   ├── test_plan_stub.py           # DELETE (replaced by test_plan_route.py)
│   ├── ingest/
│   │   └── test_filters.py         # MODIFY: add canal+lock=yes -> LOCK case (Task 3)
│   ├── route/                      # NEW
│   │   ├── __init__.py
│   │   ├── test_cost.py
│   │   ├── test_snap.py
│   │   └── test_plan_route.py      # §7.2 structural invariants over real route
│   ├── graph/                      # NEW
│   │   ├── __init__.py
│   │   ├── test_build.py
│   │   ├── test_locks.py
│   │   └── test_artifact.py
│   └── validate/                   # NEW
│       ├── __init__.py
│       └── test_connectivity.py
```

**Responsibilities & boundaries:**

- `route/cost.py` — pure. Constants + `time_min(length_m, locks, movable_bridges)` + `is_eligible(boat_dims, edge_dims)`. No graph, no network. Imported by `route/plan.py` and by structural tests.
- `route/snap.py` — pure over a built graph + gazetteer dict. `build_gazetteer(features)` → `{place_name: node_key}`; `snap_place(name, gazetteer, graph)` → node_key or raises. No network.
- `route/plan.py` — the real request-time entry point. Loads the artifact (module-level cached), builds the gazetteer, snaps, filters, runs `nx.shortest_path` by `time_min`, assembles `RouteResult`. Imports `schemas`, `route/cost`, `route/snap`, `graph/artifact`. No network.
- `graph/build.py` — pure over `WaterwayFeatures`. `build_graph(features) -> nx.Graph`. Coordinate-keyed nodes; per-way edges with `length_m` (haversine), `dimensions`, `has_tunnel`, `has_movable_bridge`, `osm_way_id`, `name`, `locks=0` (filled by `locks.py`). Includes `WaterwayKind.LOCK` in the routable set so chamber ways (canal+lock=yes, reclassified LOCK by the Task 3 `classify_way` fix) become edges. Excludes derelict (re-confirms via `WaterwayKind` — derelict ways were already dropped by `filters`, but `build` asserts none slip through).
- `graph/locks.py` — returns a new graph with `locks` set on each edge from LOCK-kind ways (matched by `osm_way_id`) and `lock=yes` nodes (snapped within tolerance); returns an orphan + lock_gate report. Pure (deep-copies input; does not mutate).
- `graph/artifact.py` — `save_artifact(graph, path, metadata)`, `load_artifact(path) -> (graph, metadata)`. Pickle. No network.
- `validate/connectivity.py` — `validate_graph(graph) -> dict` (component sizes, orphan locks, derelict-edge count, missing-dims count, zero-length/self-loop count). Pure over a built graph.

---

## Task 1: Cost model (`route/cost.py`) + move constants out of the stub

**Files:**

- Create: `pound/route/__init__.py` (empty)
- Create: `pound/route/cost.py`
- Modify: `pound/plan.py` (import constants from `route/cost.py`; keep stub behaviour identical)
- Test: `tests/route/__init__.py` (empty), `tests/route/test_cost.py`

**Interfaces:**

- Produces: `CRUISE_KMH: float`, `LOCK_MINUTES: int`, `BRIDGE_MINUTES: int`, `time_min(length_m: float, locks: int, movable_bridges: int = 0) -> float`, `is_eligible(boat_length_m, boat_beam_m, boat_draft_m, boat_height_m, edge_dims: WayDimensions) -> tuple[bool, bool]` (eligible, flagged_unknown). Consumes `pound.ingest.ir.WayDimensions`.

- [ ] **Step 1: Write the failing test**

`tests/route/test_cost.py`:

```python
from pound.route.cost import (
    BRIDGE_MINUTES,
    CRUISE_KMH,
    LOCK_MINUTES,
    is_eligible,
    time_min,
)
from pound.ingest.ir import WayDimensions


def test_constants_match_design():
    assert CRUISE_KMH == 4.8
    assert LOCK_MINUTES == 12
    assert BRIDGE_MINUTES == 5


def test_time_min_formula():
    # 9.5 km, 2 locks, no bridges: 9.5/4.8*60 + 2*12 = 142.75
    assert time_min(9500.0, 2) == 142.75
    # with one movable bridge: +5
    assert time_min(9500.0, 2, 1) == 147.75
    # zero distance, zero locks
    assert time_min(0.0, 0) == 0.0


def test_is_eligible_passes_when_within_dims():
    edge = WayDimensions(max_beam_m=2.1, max_draft_m=0.9)
    eligible, unknown = is_eligible(
        boat_length_m=None, boat_beam_m=2.0, boat_draft_m=0.8, boat_height_m=None,
        edge_dims=edge,
    )
    assert eligible is True
    assert unknown is False


def test_is_eligible_blocks_when_boat_exceeds():
    edge = WayDimensions(max_beam_m=2.1)
    eligible, unknown = is_eligible(
        boat_length_m=None, boat_beam_m=2.2, boat_draft_m=None, boat_height_m=None,
        edge_dims=edge,
    )
    assert eligible is False
    assert unknown is False


def test_is_eligible_flags_unknown_when_edge_dim_missing():
    edge = WayDimensions()  # no dims recorded
    eligible, unknown = is_eligible(
        boat_length_m=15.0, boat_beam_m=2.0, boat_draft_m=0.8, boat_height_m=2.5,
        edge_dims=edge,
    )
    assert eligible is True  # missing tag => assume passable
    assert unknown is True   # but flag it
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/route/test_cost.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pound.route'`

- [ ] **Step 3: Implement `route/cost.py`**

`pound/route/__init__.py`: empty file.

`pound/route/cost.py`:

```python
"""Lock-aware time cost model — design §5.2.

Single source of truth for traversal time and dimension eligibility. Imported
by the planner (route/plan.py) and by the structural-invariant tests (§7.2).
Pure: no graph, no network.
"""

from pound.ingest.ir import WayDimensions

CRUISE_KMH = 4.8  # ~3 mph, standard canal cruising assumption
LOCK_MINUTES = 12  # typical single-lock, single-boat time
BRIDGE_MINUTES = 5  # movable bridge penalty (optional, off by default at planner)


def time_min(length_m: float, locks: int, movable_bridges: int = 0) -> float:
    """Traversal time in minutes for an edge of length_m metres.

    time = (length_m / 1000) / CRUISE_KMH * 60 + locks * LOCK_MINUTES
           + movable_bridges * BRIDGE_MINUTES
    """
    return (length_m / 1000.0) / CRUISE_KMH * 60.0 + locks * LOCK_MINUTES + movable_bridges * BRIDGE_MINUTES


def is_eligible(
    boat_length_m: float | None,
    boat_beam_m: float | None,
    boat_draft_m: float | None,
    boat_height_m: float | None,
    edge_dims: WayDimensions,
) -> tuple[bool, bool]:
    """Dimension eligibility for an edge.

    Missing edge tag => assume passable, but flag unknown=True so the planner
    can caveat the result. Boat dim None => that dimension is not constrained.
    Returns (eligible, flagged_unknown_dims).
    """
    unknown = False
    checks = [
        (boat_beam_m, edge_dims.max_beam_m),
        (boat_length_m, edge_dims.max_length_m),
        (boat_draft_m, edge_dims.max_draft_m),
        (boat_height_m, edge_dims.max_height_m),
    ]
    for boat, edge in checks:
        if boat is None:
            continue
        if edge is None:
            unknown = True
            continue
        if boat > edge:
            return False, False
    return True, unknown
```

- [ ] **Step 4: Move constants out of the stub**

Modify `pound/plan.py`: delete `CRUISE_KMH = 4.8` and `LOCK_MINUTES = 12` and the local `_leg_minutes`; import from `route/cost.py`:

```python
from pound.route.cost import CRUISE_KMH, LOCK_MINUTES, time_min as _leg_minutes_raw
```

and replace `_leg_minutes(9.5, 2)` with `round(_leg_minutes_raw(9500.0, 2))` (note `time_min` takes metres; stub used km — convert). Keep the stub's return value identical (143). Re-run `tests/test_plan_stub.py` to confirm the stub still passes.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/route/test_cost.py tests/test_plan_stub.py -v`
Expected: PASS (cost tests + stub tests).

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check .
uv run ruff format pound/route/cost.py pound/plan.py tests/route/test_cost.py
git add pound/route/__init__.py pound/route/cost.py pound/plan.py tests/route/__init__.py tests/route/test_cost.py
git commit -m "feat(route): cost model + eligibility filter; move constants out of stub"
```

---

## Task 2: Graph build (`graph/build.py`)

**Files:**

- Modify: `pyproject.toml` (add `networkx>=3` to dependencies)
- Create: `pound/graph/__init__.py` (empty)
- Create: `pound/graph/build.py`
- Test: `tests/graph/__init__.py` (empty), `tests/graph/test_build.py`

**Interfaces:**

- Consumes: `pound.ingest.ir.WaterwayFeatures`, `WaterwayKind`.
- Produces: `build_graph(features: WaterwayFeatures) -> nx.Graph`. Graph nodes are `(lat, lon)` tuples rounded to 7 decimals. Edges carry attributes: `osm_way_id: int`, `name: str | None`, `kind: WaterwayKind`, `length_m: float`, `dimensions: WayDimensions`, `has_tunnel: bool`, `has_movable_bridge: bool`, `locks: int` (0 here; filled by `locks.py`). Helper: `_node_key(lat, lon) -> tuple[float, float]`, `_haversine_m(a, b) -> float`.

- [ ] **Step 1: Add the dependency**

Modify `pyproject.toml` dependencies to add `"networkx>=3.3",` (keep `pydantic` and `requests`).

- [ ] **Step 2: Write the failing test**

`tests/graph/test_build.py`:

```python
import networkx as nx
import pytest

from pound.graph.build import build_graph
from pound.ingest.ir import WaterwayKind
from pound.ingest.overpass import parse
from tests.fixtures import oxford_fixture_path


def _features():
    with open(oxford_fixture_path()) as f:
        return parse(f.read())


def test_build_returns_networkx_graph():
    g = build_graph(_features())
    assert isinstance(g, nx.Graph)


def test_build_excludes_derelict_ways():
    g = build_graph(_features())
    ids = {d["osm_way_id"] for _, _, d in g.edges(data=True)}
    assert 1004 not in ids  # disused:waterway
    assert 1005 not in ids  # derelict_canal


def test_build_main_chain_has_three_edges():
    g = build_graph(_features())
    # ways 1001 -> 1002 -> 1003 chain by shared endpoints => 3 edges, 4 nodes
    ids = {d["osm_way_id"] for _, _, d in g.edges(data=True)}
    assert ids == {1001, 1002, 1003, 1006}
    # Duke's Cut (1006) is isolated at 51.7400,-1.2500 -> 51.7410,-1.2510
    assert g.number_of_nodes() == 6  # 4 chain nodes + 2 Duke's Cut nodes


def test_build_edge_has_length_and_dims():
    g = build_graph(_features())
    edge = next(d for _, _, d in g.edges(data=True) if d["osm_way_id"] == 1002)
    assert edge["length_m"] > 0.0
    assert edge["dimensions"].max_beam_m == 2.1
    assert edge["dimensions"].max_draft_m == 0.9
    assert edge["kind"] == WaterwayKind.CANAL


def test_build_lock_way_edge_kind():
    g = build_graph(_features())
    edge = next(d for _, _, d in g.edges(data=True) if d["osm_way_id"] == 1003)
    assert edge["kind"] == WaterwayKind.LOCK
    assert edge["locks"] == 0  # filled by locks.py, not build


def test_build_tunnel_flag():
    g = build_graph(_features())
    edge = next(d for _, _, d in g.edges(data=True) if d["osm_way_id"] == 1006)
    assert edge["has_tunnel"] is True
```

(Add `tests/fixtures/__init__.py` exposing `oxford_fixture_path()` returning `Path(__file__).parent / "oxford_overpass_sample.json"` if not already present — check first; if a helper already exists in `tests/conftest.py`, reuse it instead of duplicating. Do not write the first shared helper speculatively — if it exists, use it; if not, add it here since two test packages now need it, which is the concrete second-need trigger per AGENTS.md.)

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/graph/test_build.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pound.graph'`

- [ ] **Step 4: Implement `graph/build.py`**

`pound/graph/__init__.py`: empty.

`pound/graph/build.py`:

```python
"""WaterwayFeatures -> noded NetworkX graph (design §4.2).

Nodes are (lat, lon) tuples rounded to 7 decimals (~11 mm) — the key two
way-ends must share to be joined. The Overpass `out geom` reader leaves
`node_ids` empty (see ir.py docstring), so connectivity is derived from
shared endpoint COORDINATES, not shared node refs. This works on hand-curated
fixtures with matched endpoints; bulk/raw data needs tolerance-snap and is
deferred to the scale scope.
"""

import math
import networkx as nx

from pound.ingest.ir import WaterwayFeatures, WaterwayKind, WayDimensions

_ROUND = 7
_ROUTABLE = {WaterwayKind.CANAL, WaterwayKind.RIVER, WaterwayKind.FAIRWAY, WaterwayKind.LOCK}


def _node_key(lat: float, lon: float) -> tuple[float, float]:
    return (round(lat, _ROUND), round(lon, _ROUND))


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in metres between two (lat, lon) points."""
    r = 6_371_000.0
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def build_graph(features: WaterwayFeatures) -> nx.Graph:
    """Build a noded, connected graph from WaterwayFeatures.

    Each way becomes one edge between its first and last geometry point.
    Intermediate geometry is preserved on the edge for later amenity buffers.
    Derelict ways are excluded (already dropped by filters; re-confirmed here).
    """
    g = nx.Graph()
    for way in features.ways:
        if way.kind not in _ROUTABLE:
            continue  # defensive: filters already dropped derelict
        if len(way.geometry) < 2:
            continue  # degenerate; validate.py reports, build skips
        a = _node_key(*way.geometry[0])
        b = _node_key(*way.geometry[-1])
        length_m = sum(
            _haversine_m(way.geometry[i], way.geometry[i + 1])
            for i in range(len(way.geometry) - 1)
        )
        for node in (a, b):
            if node not in g:
                g.add_node(node, lat=node[0], lon=node[1])
        g.add_edge(
            a,
            b,
            osm_way_id=way.osm_id,
            name=way.name,
            kind=way.kind,
            length_m=length_m,
            dimensions=way.dimensions,
            has_tunnel=way.has_tunnel,
            has_movable_bridge=way.has_movable_bridge,
            locks=0,
            geometry=list(way.geometry),
        )
    return g
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/graph/test_build.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check .
uv run ruff format pound/graph/build.py tests/graph/test_build.py
git add pyproject.toml uv.lock pound/graph/__init__.py pound/graph/build.py tests/graph/__init__.py tests/graph/test_build.py tests/fixtures/__init__.py
git commit -m "feat(graph): build WaterwayFeatures -> noded NetworkX graph (coordinate-keyed)"
```

---

## Task 3: Lock detection fix + lock attachment (`filters.py` + `graph/locks.py`)

**Why this task couples two concerns:** live-OSM checking (Bingley Five Rise,
Foxton) found that UK staircases tag each chamber as `waterway=canal` +
`lock=yes` **ways** — not `waterway=lock` ways, not `lock=yes` nodes. Scope B's
`classify_way` checks `waterway` before `lock=yes`, so a chamber way is
classified `CANAL` and the lock signal is dropped at the IR level — a whole
staircase would count as 0 locks. The fix is one reordering in `filters.py`;
`locks.py` then counts correctly because each chamber is its own edge (verified:
chamber ways chain by shared coordinates). Folding the fix into the lock task
keeps the lock-counting deliverable self-contained and gives it a staircase test
that would have caught the bug.

**Files:**

- Modify: `pound/ingest/filters.py` (`classify_way`: check `lock=yes` before `waterway`)
- Modify: `tests/ingest/test_filters.py` (add `canal`+`lock=yes` → `LOCK` case)
- Create: `tests/fixtures/staircase_overpass_sample.json` (3-chamber staircase)
- Create: `pound/graph/locks.py`
- Test: `tests/graph/test_locks.py`

**Interfaces:**

- Consumes: `nx.Graph` from `build_graph`, `WaterwayFeatures` (for lock nodes/ways).
- Produces: `attach_locks(graph: nx.Graph, features: WaterwayFeatures, tolerance_m: float = 25.0) -> tuple[nx.Graph, dict]`. Returns a new graph with `locks` set on edges; report dict: `{"lock_ways_attached": int, "lock_nodes_attached": int, "orphan_lock_ways": list[int], "orphan_lock_nodes": list[int], "lock_gate_nodes": int}`. Lock semantics per OQ-6: a LOCK-kind way sets its edge's `locks` to at least 1 (matched by `osm_way_id`); a `lock=yes` node within tolerance of a non-LOCK edge increments that edge (per-node); `lock_gate` nodes are counted as metadata but do not increment `locks`; orphans are reported.

- [ ] **Step 1: Write the failing test for the `classify_way` fix**

Add to `tests/ingest/test_filters.py`'s `classify_way` parametrize block (one
new line among the existing cases — keep all existing cases unchanged):

```python
        ({"waterway": "canal", "lock": "yes"}, WaterwayKind.LOCK),  # staircase chamber
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/ingest/test_filters.py -v`
Expected: FAIL — `classify_way({"waterway": "canal", "lock": "yes"})` returns
`WaterwayKind.CANAL`, not `LOCK` (the `waterway` check shadows `lock=yes`).

- [ ] **Step 3: Fix `classify_way`**

In `pound/ingest/filters.py`, move the `lock=yes` check **above** the
`waterway` checks so a chamber way (`waterway=canal` + `lock=yes`) is classified
`LOCK` regardless of its `waterway` value:

```python
def classify_way(tags: dict[str, str] | None) -> WaterwayKind | None:
    """Classify a way by its waterway/lock tags. None => not a waterway we keep.

    lock=yes is checked first: UK staircases (Bingley, Foxton) tag each chamber
    as waterway=canal + lock=yes (one way per chamber), so without this ordering
    the lock signal is shadowed and a whole staircase would count as 0 locks.
    """
    if not tags:
        return None
    if tags.get("lock") == "yes":
        return WaterwayKind.LOCK
    ww = tags.get("waterway", "")
    if ww == "canal":
        return WaterwayKind.CANAL
    if ww == "river":
        return WaterwayKind.RIVER
    if ww == "fairway":
        return WaterwayKind.FAIRWAY
    if ww == "lock":
        return WaterwayKind.LOCK
    return None
```

- [ ] **Step 4: Run the filters tests to verify they pass**

Run: `uv run pytest tests/ingest/test_filters.py tests/ingest/test_overpass.py tests/ingest/test_summarize.py -v`
Expected: PASS. The Oxford fixture has no `canal`+`lock=yes` way (way 1003 is
`waterway=lock` with no `lock=yes` → still `LOCK` via the `ww == "lock"` branch;
ways 1001/1002/1006 are plain canal → `CANAL`), so overpass/summarize counts
are unchanged.

- [ ] **Step 5: Commit the detection fix**

```bash
uv run ruff check .
uv run ruff format pound/ingest/filters.py tests/ingest/test_filters.py
git add pound/ingest/filters.py tests/ingest/test_filters.py
git commit -m "fix(ingest): classify canal+lock=yes ways as LOCK (staircase chamber detection)"
```

- [ ] **Step 6: Create the staircase fixture**

`tests/fixtures/staircase_overpass_sample.json` — a 3-chamber staircase where
chambers chain by shared coordinates. Coordinates are distinct from the Oxford
fixture. Two `place=*` nodes let a later route test snap to the ends.

```json
{
  "version": 0.6,
  "generator": "Overpass API (test fixture, hand-curated staircase)",
  "osm3s": {
    "timestamp_osm_base": "2026-06-22T12:00:00Z",
    "copyright": "The data included in this document is from www.openstreetmap.org. The data is made available to users under the Open Database License (ODbL)."
  },
  "elements": [
    {"type": "way", "id": 5101,
     "tags": {"waterway": "canal", "lock": "yes", "lock_name": "Staircase Bottom Lock", "lock:type": "staircase_lock", "name": "Test Canal"},
     "geometry": [{"lat": 52.0000, "lon": -1.0000}, {"lat": 52.0010, "lon": -1.0010}]},
    {"type": "way", "id": 5102,
     "tags": {"waterway": "canal", "lock": "yes", "lock_name": "Staircase Middle Lock", "lock:type": "staircase_lock", "name": "Test Canal"},
     "geometry": [{"lat": 52.0010, "lon": -1.0010}, {"lat": 52.0020, "lon": -1.0020}]},
    {"type": "way", "id": 5103,
     "tags": {"waterway": "canal", "lock": "yes", "lock_name": "Staircase Top Lock", "lock:type": "staircase_lock", "name": "Test Canal"},
     "geometry": [{"lat": 52.0020, "lon": -1.0020}, {"lat": 52.0030, "lon": -1.0030}]},
    {"type": "node", "id": 6001, "lat": 52.0000, "lon": -1.0000,
     "tags": {"place": "hamlet", "name": "Staircase Bottom"}},
    {"type": "node", "id": 6002, "lat": 52.0030, "lon": -1.0030,
     "tags": {"place": "hamlet", "name": "Staircase Top"}},
    {"type": "node", "id": 6003, "lat": 52.0010, "lon": -1.0010,
     "tags": {"waterway": "lock_gate"}}
  ]
}
```

- [ ] **Step 7: Write the failing test for `locks.py` (including the staircase)**

`tests/graph/test_locks.py`:

```python
from pound.graph.build import build_graph
from pound.graph.locks import attach_locks
from pound.ingest.overpass import parse
from tests.fixtures import oxford_fixture_path, staircase_fixture_path


def _oxford():
    with open(oxford_fixture_path()) as f:
        return parse(f.read())


def _staircase():
    with open(staircase_fixture_path()) as f:
        return parse(f.read())


# --- Oxford fixture ---

def test_lock_way_sets_edge_locks():
    g, report = attach_locks(build_graph(_oxford()), _oxford())
    edge = next(d for _, _, d in g.edges(data=True) if d["osm_way_id"] == 1003)
    assert edge["locks"] == 1
    assert report["lock_ways_attached"] == 1


def test_lock_node_at_endpoint_attaches_to_edge():
    # node 2002 (lock=yes) sits at 51.7540,-1.2640 == end of way 1003
    g, report = attach_locks(build_graph(_oxford()), _oxford())
    assert report["lock_nodes_attached"] >= 1
    edge = next(d for _, _, d in g.edges(data=True) if d["osm_way_id"] == 1003)
    assert edge["locks"] == 1  # idempotent: lock way + lock node same edge => 1


def test_lock_gate_node_counted_but_not_incrementing():
    g, report = attach_locks(build_graph(_oxford()), _oxford())
    assert report["lock_gate_nodes"] == 1  # node 2001
    edge = next(d for _, _, d in g.edges(data=True) if d["osm_way_id"] == 1003)
    assert edge["locks"] == 1  # gate doesn't add a second lock


def test_non_lock_edges_have_zero_locks():
    g, _ = attach_locks(build_graph(_oxford()), _oxford())
    for _, _, d in g.edges(data=True):
        if d["osm_way_id"] in (1001, 1002, 1006):
            assert d["locks"] == 0


def test_orphan_locks_reported():
    _, report = attach_locks(build_graph(_oxford()), _oxford())
    assert report["orphan_lock_ways"] == []
    assert report["orphan_lock_nodes"] == []


# --- Staircase fixture (the bug the Task 3 classify_way fix existed to catch) ---

def test_staircase_counts_three_locks():
    """Three chambers (canal+lock=yes ways) => three LOCK edges => 3 locks.

    Without the Task 3 classify_way fix these ways would be CANAL and the
    staircase would count as 0 locks. This test proves the fix end-to-end.
    """
    features = _staircase()
    g, report = attach_locks(build_graph(features), features)
    lock_edges = [d for _, _, d in g.edges(data=True) if d["locks"] >= 1]
    assert len(lock_edges) == 3
    assert sum(d["locks"] for _, _, d in g.edges(data=True)) == 3
    assert report["lock_ways_attached"] == 3


def test_staircase_chambers_chain_into_one_component():
    features = _staircase()
    g, _ = attach_locks(build_graph(features), features)
    # 3 chambers sharing endpoints => 4 nodes, 3 edges, one component
    assert g.number_of_nodes() == 4
    assert g.number_of_edges() == 3
    import networkx as nx
    assert nx.number_connected_components(g) == 1


def test_staircase_lock_gate_counted_not_incrementing():
    features = _staircase()
    g, report = attach_locks(build_graph(features), features)
    assert report["lock_gate_nodes"] == 1  # node 6003
    # the gate sits at the chamber-1/chamber-2 junction; neither edge gets +1
    assert sum(d["locks"] for _, _, d in g.edges(data=True)) == 3
```

Add `staircase_fixture_path()` to `tests/fixtures/__init__.py` alongside the
existing `oxford_fixture_path()` (same pattern — second concrete need for the
helper, which already exists from Task 2; just add the second entry).

- [ ] **Step 8: Run the test to verify it fails**

Run: `uv run pytest tests/graph/test_locks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pound.graph.locks'`

- [ ] **Step 9: Implement `graph/locks.py`**

```python
"""Attach lock counts to graph edges (design §4.2, §3.1).

Lock semantics (OQ-6, revised after live-OSM check): UK staircases tag each
chamber as waterway=canal + lock=yes (one way per chamber), reclassified to
WaterwayKind.LOCK by filters.classify_way. Each chamber is its own graph edge
(chamber ways chain by shared coordinates), so matching LOCK-kind ways by
osm_way_id and setting per-edge max(locks, 1) counts a staircase correctly —
5 chambers => 5 edges => 5 locks. lock=yes NODES on a non-LOCK edge increment
that edge per-node (defensive; rare in the wild). lock_gate nodes are counted
as gate metadata but do NOT increment the lock count. Orphans are reported.
"""

import copy
import math
import networkx as nx

from pound.graph.build import _haversine_m
from pound.ingest.ir import NodeKind, WaterwayFeatures, WaterwayKind


def _edge_point_dist_m(edge_geom: list[tuple[float, float]], lat: float, lon: float) -> float:
    """Min distance from (lat, lon) to any point on the edge geometry."""
    p = (lat, lon)
    return min(_haversine_m(p, pt) for pt in edge_geom) if edge_geom else math.inf


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

    # Lock ways: find their edge by matching osm_way_id.
    for way in features.ways:
        if way.kind != WaterwayKind.LOCK:
            continue
        match = next((d for _, _, d in g.edges(data=True) if d["osm_way_id"] == way.osm_id), None)
        if match is not None:
            match["locks"] = max(match["locks"], 1)
            report["lock_ways_attached"] += 1
        else:
            report["orphan_lock_ways"].append(way.osm_id)

    # Lock nodes: snap to nearest edge within tolerance.
    for node in features.nodes:
        if node.kind == NodeKind.LOCK_GATE:
            report["lock_gate_nodes"] += 1
            continue  # gates don't increment lock count
        if node.kind != NodeKind.LOCK:
            continue
        best_edge = None
        best_dist = math.inf
        for u, v, d in g.edges(data=True):
            dist = _edge_point_dist_m(d.get("geometry", []), node.lat, node.lon)
            if dist < best_dist:
                best_dist = dist
                best_edge = (u, v, d)
        if best_edge is not None and best_dist <= tolerance_m:
            best_edge[2]["locks"] = max(best_edge[2]["locks"], 1)
            report["lock_nodes_attached"] += 1
        else:
            report["orphan_lock_nodes"].append(node.osm_id)

    return g, report
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `uv run pytest tests/graph/test_locks.py -v`
Expected: PASS (8 tests — 5 Oxford + 3 staircase). The staircase tests pass only
because the Step 3 `classify_way` fix made the chamber ways `LOCK`-kind; if the
fix is reverted, `test_staircase_counts_three_locks` fails with 0 locks — the
bug the fix existed to catch.

- [ ] **Step 11: Lint + commit**

```bash
uv run ruff check .
uv run ruff format pound/graph/locks.py tests/graph/test_locks.py tests/fixtures/__init__.py
git add pound/graph/locks.py tests/graph/test_locks.py tests/fixtures/staircase_overpass_sample.json tests/fixtures/__init__.py
git commit -m "feat(graph): attach lock counts to edges; staircase fixture proves canal+lock=yes counting"
```

---

## Task 4: Build-time validation (`validate/connectivity.py`)

**Files:**

- Create: `pound/validate/__init__.py` (empty)
- Create: `pound/validate/connectivity.py`
- Test: `tests/validate/__init__.py` (empty), `tests/validate/test_connectivity.py`

**Interfaces:**

- Consumes: `nx.Graph` (post-`attach_locks`), the lock orphan report from `attach_locks`.
- Produces: `validate_graph(graph: nx.Graph, lock_report: dict) -> dict` with keys: `component_count`, `largest_component_size`, `component_sizes` (sorted desc), `orphan_lock_ways`, `orphan_lock_nodes`, `derelict_edges` (must be 0), `edges_missing_dims`, `zero_length_edges`, `self_loops`, `total_edges`, `total_nodes`.

- [ ] **Step 1: Write the failing test**

`tests/validate/test_connectivity.py`:

```python
from pound.graph.build import build_graph
from pound.graph.locks import attach_locks
from pound.ingest.ir import WaterwayKind
from pound.ingest.overpass import parse
from pound.validate.connectivity import validate_graph
from tests.fixtures import oxford_fixture_path


def _graph_and_report():
    features = parse(open(oxford_fixture_path()).read())
    g, report = attach_locks(build_graph(features), features)
    return g, report


def test_component_count_is_two():
    g, report = _graph_and_report()
    v = validate_graph(g, report)
    assert v["component_count"] == 2  # main chain + Duke's Cut
    assert v["largest_component_size"] == 4  # 4 nodes in the main chain


def test_no_derelict_edges():
    g, report = _graph_and_report()
    v = validate_graph(g, report)
    assert v["derelict_edges"] == 0


def test_missing_dims_count():
    g, report = _graph_and_report()
    v = validate_graph(g, report)
    # 1001, 1003, 1006 have no dims; 1002 does
    assert v["edges_missing_dims"] == 3


def test_no_zero_length_or_self_loops():
    g, report = _graph_and_report()
    v = validate_graph(g, report)
    assert v["zero_length_edges"] == 0
    assert v["self_loops"] == 0


def test_orphans_carry_through():
    g, report = _graph_and_report()
    v = validate_graph(g, report)
    assert v["orphan_lock_ways"] == []
    assert v["orphan_lock_nodes"] == []


def test_totals_present():
    g, report = _graph_and_report()
    v = validate_graph(g, report)
    assert v["total_edges"] == 4
    assert v["total_nodes"] == 6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/validate/test_connectivity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pound.validate'`

- [ ] **Step 3: Implement `validate/connectivity.py`**

```python
"""Build-time graph validation -> report dict (design §4.3, §7.1).

Pure over a built (and lock-attached) graph. Produces the same kind of report
dict as ingest/summarize.py — component sizes, orphans, filter sanity, tag
coverage, degenerate geometry. Not a runtime checker (design §1, §7).
"""

import networkx as nx

from pound.ingest.ir import WaterwayKind


def validate_graph(graph: nx.Graph, lock_report: dict) -> dict:
    components = list(nx.connected_components(graph))
    sizes = sorted((len(c) for c in components), reverse=True)

    derelict = 0
    missing_dims = 0
    zero_length = 0
    self_loops = 0
    for u, v, d in graph.edges(data=True):
        if u == v:
            self_loops += 1
        if d.get("length_m", 0.0) == 0.0:
            zero_length += 1
        # derelict kinds should never reach the graph (build excludes them);
        # count any non-routable kind that slipped through as derelict.
        if d.get("kind") not in {WaterwayKind.CANAL, WaterwayKind.RIVER, WaterwayKind.FAIRWAY, WaterwayKind.LOCK}:
            derelict += 1
        dims = d.get("dimensions")
        if dims is None or not any(
            getattr(dims, f) is not None
            for f in ("max_beam_m", "max_length_m", "max_draft_m", "max_height_m")
        ):
            missing_dims += 1

    return {
        "component_count": len(components),
        "largest_component_size": sizes[0] if sizes else 0,
        "component_sizes": sizes,
        "orphan_lock_ways": list(lock_report.get("orphan_lock_ways", [])),
        "orphan_lock_nodes": list(lock_report.get("orphan_lock_nodes", [])),
        "derelict_edges": derelict,
        "edges_missing_dims": missing_dims,
        "zero_length_edges": zero_length,
        "self_loops": self_loops,
        "total_edges": graph.number_of_edges(),
        "total_nodes": graph.number_of_nodes(),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/validate/test_connectivity.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check .
uv run ruff format pound/validate/connectivity.py tests/validate/test_connectivity.py
git add pound/validate/__init__.py pound/validate/connectivity.py tests/validate/__init__.py tests/validate/test_connectivity.py
git commit -m "feat(validate): build-time connectivity + tag-coverage + degenerate-edge report"
```

---

## Task 5: Artifact serialize/load (`graph/artifact.py`)

**Files:**

- Modify: `.gitignore` (add `pound/artifacts/`)
- Create: `pound/graph/artifact.py`
- Test: `tests/graph/test_artifact.py`

**Interfaces:**

- Consumes: `nx.Graph`, a metadata dict.
- Produces: `save_artifact(graph: nx.Graph, path: Path, metadata: dict) -> None`, `load_artifact(path: Path) -> tuple[nx.Graph, dict]`. Metadata keys: `source`, `fetched_at`, `built_at` (ISO), `version`, `validation` (the validate_graph report). File format: pickle of `{"graph": graph, "metadata": metadata}`.

- [ ] **Step 1: Write the failing test**

`tests/graph/test_artifact.py`:

```python
from pathlib import Path

from pound.graph.artifact import load_artifact, save_artifact
from pound.graph.build import build_graph
from pound.ingest.overpass import parse
from tests.fixtures import oxford_fixture_path


def _graph():
    return build_graph(parse(open(oxford_fixture_path()).read()))


def test_artifact_round_trips(tmp_path: Path):
    g = _graph()
    meta = {"source": "overpass", "fetched_at": "2026-06-21T12:00:00Z", "built_at": "2026-06-22T10:00:00Z", "version": 1}
    art = tmp_path / "graph.pkl"
    save_artifact(g, art, meta)
    loaded_g, loaded_meta = load_artifact(art)
    assert loaded_g.number_of_edges() == g.number_of_edges()
    assert loaded_meta["source"] == "overpass"
    assert loaded_meta["version"] == 1
```

The test uses pytest's built-in `tmp_path` fixture (a unique per-test temp dir)
rather than a hand-rolled `mktemp` path — this is what AGENTS.md's "never reuse
fixed temp paths" rule requires.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/graph/test_artifact.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pound.graph.artifact'`

- [ ] **Step 3: Implement `graph/artifact.py`**

```python
"""Serialize/load the built graph artifact (design §4.4).

Pickle for the NetworkX first cut (design says pickle or PostGIS). The artifact
is gitignored (like pound/data/); tests build it into a tmp path. Not a long-
term portable format — revisit at the scale scope. No network.
"""

import pickle
from datetime import UTC, datetime
from pathlib import Path


def save_artifact(graph, path: Path, metadata: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        **metadata,
        "built_at": metadata.get("built_at", datetime.now(UTC).isoformat()),
    }
    with open(path, "wb") as f:
        pickle.dump({"graph": graph, "metadata": meta}, f)


def load_artifact(path: Path) -> tuple:
    with open(path, "rb") as f:
        blob = pickle.load(f)
    return blob["graph"], blob["metadata"]
```

Add to `.gitignore`:

```
pound/artifacts/
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/graph/test_artifact.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check .
uv run ruff format pound/graph/artifact.py tests/graph/test_artifact.py
git add .gitignore pound/graph/artifact.py tests/graph/test_artifact.py
git commit -m "feat(graph): pickle artifact save/load with provenance metadata"
```

---

## Task 6: Snap + offline gazetteer (`route/snap.py`) + fixture/IR changes

**Files:**

- Modify: `pound/ingest/ir.py` (add `NodeKind.PLACE`)
- Modify: `pound/ingest/filters.py` (`classify_node`: `place=*` → `NodeKind.PLACE`)
- Modify: `tests/fixtures/oxford_overpass_sample.json` (add two `place=*` nodes at chain endpoints)
- Create: `pound/route/snap.py`
- Test: `tests/route/test_snap.py`

**Interfaces:**

- Consumes: `WaterwayFeatures` (for `PLACE` nodes), `nx.Graph`.
- Produces: `build_gazetteer(features: WaterwayFeatures) -> dict[str, tuple[float, float]]` mapping place name → node key; `snap_place(name: str, gazetteer: dict, graph: nx.Graph) -> tuple[float, float]` returning the graph node key, raising `ValueError` if the name is unknown or the snapped node is not in the graph.

- [ ] **Step 1: Extend the fixture with two place nodes**

Modify `tests/fixtures/oxford_overpass_sample.json` `elements` array to add (before the closing `]`):

```json
    {
      "type": "node", "id": 3001, "lat": 51.7500, "lon": -1.2600,
      "tags": {"place": "city", "name": "Oxford"}
    },
    {
      "type": "node", "id": 3002, "lat": 51.7540, "lon": -1.2640,
      "tags": {"place": "hamlet", "name": "Hayfield"}
    }
```

These sit exactly on the chain endpoints (way 1001 start, way 1003 end) so they snap to existing graph nodes.

- [ ] **Step 2: Add `NodeKind.PLACE` and classify it**

Modify `pound/ingest/ir.py`: add to `NodeKind`:

```python
    PLACE = "place"
```

Modify `pound/ingest/filters.py` `classify_node`, add before the final `return None`:

```python
    if "place" in tags:
        return NodeKind.PLACE
```

- [ ] **Step 3: Write the failing test**

`tests/route/test_snap.py`:

```python
import pytest

from pound.graph.build import build_graph
from pound.ingest.overpass import parse
from pound.route.snap import build_gazetteer, snap_place
from tests.fixtures import oxford_fixture_path


def _features():
    with open(oxford_fixture_path()) as f:
        return parse(f.read())


def test_gazetteer_contains_named_places():
    gaz = build_gazetteer(_features())
    assert "Oxford" in gaz
    assert "Hayfield" in gaz


def test_snap_place_returns_graph_node():
    features = _features()
    g = build_graph(features)
    gaz = build_gazetteer(features)
    node = snap_place("Oxford", gaz, g)
    assert node in g.nodes
    node2 = snap_place("Hayfield", gaz, g)
    assert node2 in g.nodes
    assert node != node2


def test_snap_place_unknown_raises():
    g = build_graph(_features())
    gaz = build_gazetteer(_features())
    with pytest.raises(ValueError, match="unknown place"):
        snap_place("Narnia", gaz, g)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/route/test_snap.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pound.route.snap'`

- [ ] **Step 5: Implement `route/snap.py`**

```python
"""Offline gazetteer + place snapping (design §5.1).

Built from PLACE nodes in the IR (place=* nodes). Network-free: the gazetteer
is a dict built once from the same features the graph was built from. A place
name maps to its coordinate, which is the graph node key (place nodes sit
exactly on way endpoints in the fixture; for bulk data a nearest-node-within-
tolerance step is needed and is deferred).
"""

from pound.graph.build import _node_key
from pound.ingest.ir import NodeKind, WaterwayFeatures


def build_gazetteer(features: WaterwayFeatures) -> dict[str, tuple[float, float]]:
    return {
        n.tags["name"]: _node_key(n.lat, n.lon)
        for n in features.nodes
        if n.kind == NodeKind.PLACE and "name" in n.tags
    }


def snap_place(name: str, gazetteer: dict, graph) -> tuple[float, float]:
    if name not in gazetteer:
        raise ValueError(f"unknown place: {name!r}")
    node = gazetteer[name]
    if node not in graph.nodes:
        raise ValueError(f"place {name!r} snaps to a node not in the graph")
    return node
```

- [ ] **Step 6: Run tests to verify they pass (including existing overpass tests after fixture change)**

Run: `uv run pytest tests/route/test_snap.py tests/ingest/ -v`
Expected: PASS. If existing overpass tests assert the exact node count, update them to expect the two new PLACE nodes (the pub-drop test should still pass since place nodes are not pubs).

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff check .
uv run ruff format pound/route/snap.py tests/route/test_snap.py
git add pound/ingest/ir.py pound/ingest/filters.py tests/fixtures/oxford_overpass_sample.json pound/route/snap.py tests/route/test_snap.py tests/ingest/
git commit -m "feat(route): offline gazetteer from place=* nodes + snap_place; add PLACE nodekind"
```

---

## Task 7: Real `plan_route` (`route/plan.py`) — replace the stub

**Files:**

- Delete: `pound/plan.py` (moved to `pound/route/plan.py`)
- Create: `pound/route/plan.py`
- Modify: `pound/__init__.py` if it re-exports `plan_route` (check; if so, update the re-export to `from pound.route.plan import plan_route`)
- Test: `tests/route/test_plan_route.py` (new — §7.2 invariants over the real route)

**Interfaces:**

- Consumes: `CanalConstraints`, `graph/artifact.load_artifact`, `route/snap`, `route/cost`, `nx.shortest_path`.
- Produces: `plan_route(constraints: CanalConstraints) -> RouteResult`. Honors `constraints.days` and `constraints.hours_per_day` via `_chunk_days(legs, hours_per_day, max_days) -> list[DayPlan]` (greedy cumulative-minute packing; non-empty days only, no padding to `days` — OQ-8). Module-level artifact cache keyed by a default artifact path (overridable via `pound.config.ARTIFACT_PATH` env var, default `pound/artifacts/oxford.pkl`). For tests, a module-level `_load_graph(features)` helper builds the graph directly from features (no pickle IO) so tests stay fast and hermetic — `plan_route` accepts an optional `graph` + `features` injection for testing (kwarg `_graph=None, _features=None`).

- [ ] **Step 1: Write the failing test (§7.2 structural invariants over the real route)**

`tests/route/test_plan_route.py`:

```python
import pytest

from pound.ingest.overpass import parse
from pound.graph.build import build_graph
from pound.graph.locks import attach_locks
from pound.route.cost import CRUISE_KMH, LOCK_MINUTES, time_min
from pound.route.plan import plan_route
from pound.schemas import CanalConstraints
from tests.fixtures import oxford_fixture_path


def _plan(**kwargs):
    features = parse(open(oxford_fixture_path()).read())
    g, _ = attach_locks(build_graph(features), features)
    constraints = CanalConstraints(start="Oxford", end="Hayfield", days=1, **kwargs)
    return plan_route(constraints, _graph=g, _features=features)


def test_route_connects_oxford_to_hayfield():
    r = _plan()
    assert r.start == "Oxford"
    assert r.end == "Hayfield"
    assert r.is_ring is False
    assert r.legs[0].from_place == "Oxford"
    assert r.legs[-1].to_place == "Hayfield"
    # legs connect end-to-end (§7.2)
    for i in range(len(r.legs) - 1):
        assert r.legs[i].to_place == r.legs[i + 1].from_place


def test_totals_equal_sum_of_legs():
    r = _plan()
    assert r.total_km == pytest.approx(sum(l.distance_km for l in r.legs))
    assert r.total_locks == sum(l.locks for l in r.legs)
    assert r.total_minutes == sum(l.est_minutes for l in r.legs)


def test_per_leg_minutes_match_cost_formula():
    r = _plan()
    for leg in r.legs:
        expected = round(leg.distance_km / CRUISE_KMH * 60 + leg.locks * LOCK_MINUTES)
        assert leg.est_minutes == expected


def test_total_minutes_matches_time_min_over_edges():
    # independent recomputation from the raw edge lengths/locks
    r = _plan()
    assert r.total_minutes == round(time_min(r.total_km * 1000, r.total_locks))


def test_locks_counted_on_lock_edge():
    r = _plan()
    # way 1003 (lock) is on the path; exactly one lock edge
    assert r.total_locks == 1


def test_warnings_flag_unknown_dims():
    # 1001 and 1003 lack dims; with a boat that has dims, those legs flag
    r = _plan(boat_beam_m=2.0, boat_draft_m=0.8)
    assert any("unknown" in w.lower() for w in r.warnings)


def test_graph_source_date_from_metadata():
    r = _plan()
    assert r.graph_source_date == "2026-06-21T12:00:00Z"


def test_ring_raises_not_implemented():
    features = parse(open(oxford_fixture_path()).read())
    g, _ = attach_locks(build_graph(features), features)
    with pytest.raises(NotImplementedError, match="rings not yet supported"):
        plan_route(CanalConstraints(start="Oxford", end=None, days=1), _graph=g, _features=features)


def test_single_day_plan_wraps_legs():
    r = _plan()
    assert len(r.days) == 1
    assert r.days[0].legs == r.legs
    assert r.days[0].cruising_minutes == r.total_minutes


def _long_plan(days: int, hours_per_day: float):
    """Synthetic long route: scale the Oxford edge lengths so the 3-edge path
    needs multiple days. Tests the chunking ALGORITHM, not Oxford data.
    """
    import copy

    features = parse(open(oxford_fixture_path()).read())
    g, _ = attach_locks(build_graph(features), features)
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = d["length_m"] * 100.0  # ~130m -> ~13km -> ~162 min/edge
    constraints = CanalConstraints(
        start="Oxford", end="Hayfield", days=days, hours_per_day=hours_per_day
    )
    return plan_route(constraints, _graph=g, _features=features)


def test_multiday_splits_legs_within_budget():
    # 3 edges ~162 min each; hours_per_day=3 -> 180 min budget.
    # Greedy: day1=162, day2=162, day3=162 (each +next would exceed 180).
    r = _long_plan(days=3, hours_per_day=3.0)
    assert len(r.days) == 3
    for day in r.days:
        assert day.cruising_minutes <= 3.0 * 60
        assert day.legs  # non-empty (OQ-8: no padding)


def test_days_partition_legs_exactly():
    r = _long_plan(days=3, hours_per_day=3.0)
    flat = [leg for day in r.days for leg in day.legs]
    assert flat == r.legs


def test_days_not_padded_beyond_route():
    # OQ-8: days=5 but route needs only 3 -> emit 3, NOT 5 with empty trailers.
    r = _long_plan(days=5, hours_per_day=3.0)
    assert len(r.days) == 3
    assert all(day.legs for day in r.days)


def test_days_count_never_exceeds_constraints_days():
    r = _long_plan(days=2, hours_per_day=3.0)
    assert len(r.days) <= 2


def test_day_index_sequential():
    r = _long_plan(days=3, hours_per_day=3.0)
    assert [d.day for d in r.days] == [1, 2, 3]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/route/test_plan_route.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pound.route.plan'`

- [ ] **Step 3: Implement `route/plan.py`**

```python
"""Request-time entry point — real plan_route (design §5).

Loads the prebuilt graph artifact once (module-level cache), snaps start/end
to graph nodes via the offline gazetteer, filters edges by boat dimensions,
runs Dijkstra by time-cost, and assembles a RouteResult. Pure: no network,
no LLM. Point-to-point only in this scope; rings raise NotImplementedError.
Day budgeting is trivial cumulative-minute chunking (design §5.3): legs are
packed greedily into consecutive DayPlans within hours_per_day, emitting as
many non-empty days as the route needs (NOT padded to constraints.days —
OQ-8). Mooring-aware day placement is deferred to Scope D.
"""

import networkx as nx

from pound.ingest.ir import WaterwayFeatures
from pound.route.cost import is_eligible, time_min
from pound.route.snap import build_gazetteer, snap_place
from pound.schemas import CanalConstraints, DayPlan, RouteLeg, RouteResult


def plan_route(
    constraints: CanalConstraints,
    *,
    _graph: nx.Graph | None = None,
    _features: WaterwayFeatures | None = None,
) -> RouteResult:
    """Plan a point-to-point canal route.

    Production callers omit the underscore-prefixed kwargs; those are for
    hermetic testing (inject a graph + features built from the fixture without
    pickle IO). Rings (end is None) are not yet supported.
    """
    if constraints.end is None:
        raise NotImplementedError("rings not yet supported (design §5.3; scope C is point-to-point)")

    if _graph is None or _features is None:
        # Production path: load the artifact. Wired when the build CLI lands
        # the artifact; for now this branch is not exercised by tests.
        raise RuntimeError("artifact loading not wired in this scope; pass _graph and _features for testing")

    graph, features = _graph, _features
    gaz = build_gazetteer(features)
    start_node = snap_place(constraints.start, gaz, graph)
    end_node = snap_place(constraints.end, gaz, graph)

    if not nx.has_path(graph, start_node, end_node):
        raise ValueError(f"no path between {constraints.start!r} and {constraints.end!r}")

    # Build the weight function, applying dimension eligibility.
    unknown_edges: list[str] = []

    def weight(u, v, d):
        eligible, unknown = is_eligible(
            constraints.boat_length_m,
            constraints.boat_beam_m,
            constraints.boat_draft_m,
            constraints.boat_height_m,
            d["dimensions"],
        )
        if not eligible:
            return None  # NetworkX treats None as impassable
        if unknown:
            unknown_edges.append(str(d["osm_way_id"]))
        return time_min(d["length_m"], d.get("locks", 0), 1 if d.get("has_movable_bridge") else 0)

    path = nx.shortest_path(graph, start_node, end_node, weight=weight)

    # Assemble legs from consecutive path edges.
    legs: list[RouteLeg] = []
    for u, v in zip(path, path[1:], strict=False):
        d = graph.edges[u, v]
        km = d["length_m"] / 1000.0
        locks = d.get("locks", 0)
        legs.append(
            RouteLeg(
                from_place=_name_for(u, features, gaz),
                to_place=_name_for(v, features, gaz),
                distance_km=round(km, 4),
                locks=locks,
                est_minutes=round(time_min(d["length_m"], locks)),
                flagged_unknown_dims=str(d["osm_way_id"]) in set(unknown_edges),
            )
        )

    total_km = round(sum(l.distance_km for l in legs), 4)
    total_locks = sum(l.locks for l in legs)
    total_minutes = sum(l.est_minutes for l in legs)

    warnings: list[str] = []
    if unknown_edges:
        warnings.append(f"draft/beam unknown on {len(set(unknown_edges))} segment(s)")

    days = _chunk_days(legs, constraints.hours_per_day, constraints.days)
    if len(days) > 1 and any(
        day.cruising_minutes > constraints.hours_per_day * 60 for day in days
    ):
        warnings.append("one or more days exceed hours_per_day budget")

    return RouteResult(
        start=constraints.start,
        end=constraints.end,
        is_ring=False,
        legs=legs,
        days=days,
        total_km=total_km,
        total_locks=total_locks,
        total_minutes=total_minutes,
        amenities=[],  # amenities are design §5.4, out of scope
        warnings=warnings,
        graph_source_date=features.fetched_at,
    )


def _chunk_days(
    legs: list[RouteLeg], hours_per_day: float, max_days: int
) -> list[DayPlan]:
    """Greedily pack legs into consecutive DayPlans within the per-day budget.

    Each day's cruising_minutes <= hours_per_day*60. Emits as many non-empty
    days as the route needs, up to max_days (OQ-8: no empty padding). A single
    leg longer than the budget forms its own day (overflows; caller warns).
    Mooring-aware placement is a Scope D concern; end_near is the day's last
    leg to_place for now.
    """
    budget = hours_per_day * 60.0
    days: list[DayPlan] = []
    current: list[RouteLeg] = []
    current_min = 0

    def flush():
        nonlocal current, current_min
        if current:
            days.append(
                DayPlan(
                    day=len(days) + 1,
                    legs=current,
                    end_near=current[-1].to_place,
                    cruising_minutes=current_min,
                )
            current = []
            current_min = 0

    for leg in legs:
        # Start a new day when adding this leg would overflow the current one.
        if current and current_min + leg.est_minutes > budget:
            flush()
        # max_days cap: if we've already emitted max_days days, fold the
        # remaining legs into the last day instead of opening a new one.
        if len(days) >= max_days and not current and days:
            last = days[-1]
            last.legs.append(leg)
            last.cruising_minutes += leg.est_minutes
            last.end_near = leg.to_place
            continue
        current.append(leg)
        current_min += leg.est_minutes
    flush()
    return days


def _name_for(node_key, features, gazetteer) -> str:
    """Reverse-lookup a node key to a place name; fall back to coordinate string."""
    for name, key in gazetteer.items():
        if key == node_key:
            return name
    return f"{node_key[0]},{node_key[1]}"
```

Delete `pound/plan.py`. If `pound/__init__.py` re-exports `plan_route`, update it to `from pound.route.plan import plan_route`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/route/test_plan_route.py -v`
Expected: PASS (14 tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check .
uv run ruff format pound/route/plan.py tests/route/test_plan_route.py
git add pound/route/plan.py pound/plan.py pound/__init__.py tests/route/test_plan_route.py
git commit -m "feat(route): real plan_route over built graph (Dijkstra by time-cost); retire stub"
```

---

## Task 8: Retire stub tests; wire build→artifact dev path; update progress

**Files:**

- Delete: `tests/test_plan_stub.py`
- Create: `pound/graph/build_cli.py` (thin dev CLI: `pound-build oxford --out <path>` — ingest → build → attach_locks → validate → save_artifact; mirrors `ingest/cli.py` pattern) OR fold into `ingest/cli.py` as a `build` subcommand. **Recommendation: fold into `ingest/cli.py`** — it's the second concrete need for a dev CLI and the natural place; do not create a new module speculatively.
- Modify: `pound/ingest/cli.py` (add `build` subcommand)
- Modify: `README.md` (usage section: document `pound-ingest oxford` and `pound-ingest build oxford --out <path>`)
- Modify: `progress.md`

- [ ] **Step 1: Delete the stub tests**

`git rm tests/test_plan_stub.py` — the §7.2 invariants now live in `tests/route/test_plan_route.py` (Task 7).

- [ ] **Step 2: Run full suite to confirm nothing references the deleted stub**

Run: `uv run pytest -q`
Expected: PASS (all remaining tests green; the stub's hardcoded Oxford→Heyford assertions are gone, replaced by the real-route invariants).

- [ ] **Step 3: Add the `build` subcommand to `ingest/cli.py`**

Extend the existing argparse CLI with a `build` subcommand that: fetches/parses Oxford (via `fetch_oxford` or the fixture), builds the graph, attaches locks, validates, and saves the artifact with metadata (`source`, `fetched_at`, `validation`). Follow the existing `oxford` subcommand's argparse pattern. Test it with monkeypatched `fetch_oxford` (same pattern as the existing CLI test) writing to a `tmp_path` artifact.

`tests/ingest/test_cli.py` — add:

```python
def test_build_subcommand_writes_artifact(tmp_path, monkeypatch):
    from pound.ingest import cli
    features = parse(open(oxford_fixture_path()).read())
    monkeypatch.setattr(cli, "fetch_oxford", lambda: features)
    out = tmp_path / "oxford.pkl"
    rc = cli.main(["build", "oxford", "--out", str(out)])
    assert rc == 0
    assert out.exists()
    g, meta = load_artifact(out)
    assert g.number_of_edges() > 0
    assert "validation" in meta
```

- [ ] **Step 4: Update README usage section**

Add a `build` subsection under the existing ingest usage:

```markdown
### Build the graph artifact

```bash
uv run pound-ingest build oxford --out pound/artifacts/oxford.pkl
```

Produces a pickled NetworkX graph with provenance metadata, ready for
`plan_route` to load at request time.

```

- [ ] **Step 5: Run full suite + ruff**

Run: `uv run pytest -q && uv run ruff check .`
Expected: all green.

- [ ] **Step 6: Update progress.md + commit**

Append a "Scope C" section to `progress.md` listing tasks 1–8 with commit SHAs and the final test/ruff status.

```bash
git add -A
git commit -m "feat(graph): build dev CLI subcommand; retire stub tests; README + progress for scope C"
```

---

## Self-Review

**1. Spec coverage (design §9 build order):**

- Step 2 (regional ingest + graph build): ingest done in Scope B; **graph build = Task 2–3**. Task 3 also fixes a Scope B ingest bug (`classify_way` shadowing `lock=yes` on canal+lock=yes chamber ways) found by live-OSM check of Bingley/Foxton staircases. ✓
- Step 3 (cost model + point-to-point routing): **Tasks 1, 7**. ✓
- Step 4 (build-time graph validation): **Task 4**. ✓
- Step 5 (amenities): out of scope (§5.4) — confirmed in OQ-7. ✓ (correctly absent)
- Step 6 (full GB scale): out of scope — deferred. ✓
- Step 7 (day budgeting + rings): **trivial day chunking IN Scope C** (Task 7 `_chunk_days`: greedy cumulative-minute packing within `hours_per_day`, non-empty days only per OQ-8, exercised by a synthetic long-route test so the §7.2 `≤ hours_per_day` invariant has a real failure mode). Mooring-aware day placement still deferred to Scope D with amenities. Rings still raise `NotImplementedError`. ✓
- Step 8 (oracle): out of scope (§8). ✓
- §7.2 structural-invariant tests: **Task 7** (totals == sum legs, formula match, end-to-end legs, day budget ≤ hours). The day-budget invariant is exercised by `test_multiday_splits_legs_within_budget` over a synthetic long route (the raw Oxford route is ~7 min and can't fail it). Amenity distance-within-buffer is vacuous (amenities empty, out of scope) and not asserted. ✓

**2. Placeholder scan:** No placeholders. (An earlier draft had a deliberate bogus `from tmpfiles import mkstemp` line in Task 5's test as a review aid; removed — the test now uses pytest's `tmp_path` fixture directly, per AGENTS.md's temp-path rule.) No "TBD"/"implement later"/"add appropriate error handling" anywhere. All code blocks are runnable.

**3. Type consistency:**

- `_node_key` defined in `graph/build.py`, imported by `snap.py`; `locks.py` imports only `_haversine_m` from `build.py` — consistent. ✓
- Edge attributes (`length_m`, `locks`, `dimensions`, `has_tunnel`, `has_movable_bridge`, `osm_way_id`, `name`, `kind`, `geometry`) set in `build.py`, read in `locks.py`, `validate/connectivity.py`, `route/plan.py` — consistent. ✓
- `time_min(length_m, locks, movable_bridges)` signature consistent across `cost.py`, `test_cost.py`, `route/plan.py`. ✓ (note: `test_plan_route.py` recomputes via `time_min(total_km*1000, total_locks)` — total over the path, which matches since cost is additive.)
- `is_eligible` returns `(bool, bool)` — consistent across `cost.py` and `plan.py` weight fn. ✓
- `NodeKind.PLACE` added in `ir.py`, produced by `classify_node`, consumed by `snap.build_gazetteer`. ✓
- `validate_graph(graph, lock_report)` — `lock_report` is the dict returned by `attach_locks`; keys `orphan_lock_ways`/`orphan_lock_nodes` match. ✓
- `plan_route` kwargs `_graph`/`_features` — consistent between impl and test `_plan(...)` helper. ✓
- **Lock-counting bug coverage (OQ-6 revision):** `classify_way` is fixed in Task 3 Step 3 (check `lock=yes` before `waterway`); the `canal`+`lock=yes` → `LOCK` case is asserted in `test_filters.py`; the staircase fixture (`tests/fixtures/staircase_overpass_sample.json`) + `test_staircase_counts_three_locks` prove 3 chambers → 3 locks end-to-end through `build_graph` + `attach_locks`. Reverting the `classify_way` fix makes `test_staircase_counts_three_locks` fail with 0 locks — the test exists specifically to catch the regression. ✓
