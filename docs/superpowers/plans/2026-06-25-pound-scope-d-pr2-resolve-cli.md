# Pound — Scope D PR2: Resolve, Production Loading & Minimal `pound-plan` CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Status — reconciled with repo state 2026-07-06

PR1 (the noded graph build + comprehensive `place=*` gazetteer + `name` node-attribute attachment + embedded `graph.graph["gazetteer"]` wired through `pound-ingest build`) **has landed** (commits `3b6c7e0` → `2fac18d`, merged as PR #4). This plan now executes against that landed tree. The following corrections relative to the original 2026-06-25 draft reflect the post-PR1 repo reality:

- **Graph node keys are synthetic internal uids (ints), not coordinate tuples.** Scope C's interim coord-keyed graph was rewritten by `3b6c7e0` then switched to internal uids by `2fac18d`. OQ-2 is reopened and **flipped to uids** below: `ResolvedConstraints` carries `start_uid`/`end_uid: int` (the graph's own node handles); `resolve_place(name, graph) -> int` returns a uid; `plan_route` consumes uids directly — no `coord_to_uid` index, no indirection. The geography-first case (a future map-click UI posting raw lat/lon) is handled by a **separate** `resolve_coord(lat, lon, graph) -> int` helper that snaps a coordinate to the nearest uid — the geography seam stays open *at the resolver layer*, not leaked into `ResolvedConstraints`. `resolve_coord` is a documented `# future` seam in `resolve.py`, deferred to the scope that builds the map-click UI (it is mechanically the nearest-node loop `resolve_place` already performs, minus the gazetteer lookup).
- **`pound/route/snap.py` and `tests/route/test_snap.py` are already gone** (dropped by the noded-build refactor). OQ-4's “DELETE” step is therefore a no-op; Task 2 just adds `resolve.py`.
- **`pound-ingest build` already embeds `graph.graph["gazetteer"]`** and writes `fetched_at` into the artifact *metadata* (not `graph.graph`); the `pound-plan` CLI sets `graph.graph["fetched_at"]` from that metadata after `load_artifact`, and the Task 3 test helper sets it directly on the in-memory graph.
- **The README “Bulk ingest” section is now stale** (it still documents `--tolerance-m` / `--max-unresolved-snaps` / `pound/data/overrides.json`, which the noded-build refactor dropped). Refreshing it is out of PR2's scope; Task 4 only appends the `pound-plan` section.
- **Task 3 multi-day tests restored to `days=4`** (the 4-edge Oxford→Hayfield path needs 4 days at the 13 km/edge scale used by the existing passing tests); the draft's `days=3`-with-in-budget assertions were self-contradictory under the max-days cap, and its `test_days_not_padded_beyond_route` asserting `3` (with `days=5`) should have been `4`.

Everything below is the corrected plan.

**Goal:** Evolve the Scope A frozen contract deliberately — make `plan_route` pure-by-construction over *resolved* graph nodes via a new `ResolvedConstraints` and a new `route/resolve.py` `resolve_place` function (offline gazetteer only; no resolver class — see OQ-3), wire production artifact loading into a **minimal** `pound-plan` CLI, and retire Scope C's `_graph`/`_features` test kwargs. Exit: `pound-plan Oxford Banbury --days 3` prints a real human-readable `RouteResult` over the England artifact end-to-end, no Python, no network, no LLM. Four error-behavior correctness gaps the production CLI surfaces on real data are fixed in this plan (clear `ValueError` instead of an uncaught `NetworkXNoPath` under dimension filtering; over-budget day warning for single-day routes; schema `Field(gt=0)` on `days`/`hours_per_day`).

**Architecture:** The contract splits into three types: `CanalConstraints` (CLI/UI convenience, names strings) → `route/resolve.py` `resolve_place(name, graph) -> int` (dict-lookup of the embedded `graph.graph["gazetteer"]`, then nearest-graph-node-within-tolerance, returning the matched node's **uid**; a `# future: GeocodeResolver (network)` seam and a `# future: resolve_coord (lat/lon → uid)` seam for map-click input are left in the docstring) → `ResolvedConstraints` (`start_uid`/`end_uid: int` — the graph's own node handles, the pure-routing input) → pure `plan_route(resolved, *, graph) -> RouteResult` (Dijkstra over the loaded graph; leg names from the `name` node attribute PR1 attached; zero network, zero LLM, hermetic by construction). A `plan_route_from_constraints(c, *, graph, snap_tolerance_m=...)` convenience sits beside pure `plan_route` as the `CanalConstraints → resolve → plan_route` bridge the CLI and Agent Core use — additive, not breaking, at the convenience layer; the old Scope C `plan_route(CanalConstraints, _graph=…, _features=…)` entry point is **removed entirely**. Production artifact loading is the CLI's job: `pound-plan` calls `load_artifact(path)` once and threads the loaded graph through `resolve_place` then `plan_route`.

**Tech Stack:** Python 3.12+, Pydantic v2, NetworkX — all already present. **No new dependencies.** Geocoder, `rtree`/`shapely`, rings, amenities all deferred.

## Open questions (resolved as below — flag to user before execution)

- **OQ-1 — `ResolvedConstraints` location** → `pound/schemas.py` (the contract home). Confirmed by the refined design (§4 Resolved micro-questions #1).
- **OQ-2 — Node-key shape** → `ResolvedConstraints` carries **`start_uid` / `end_uid: int`** — the graph's own internal node handles. `resolve_place` returns a uid. `plan_route` consumes uids directly: `start, end = constraints.start_uid, constraints.end_uid` (no `coord_to_uid` index, no coord-to-uid mapping step — `plan_route` is purest-possible, operating on the handles the graph already understands). The geography-first case (a future map-click UI posting raw lat/lon, with no resolver round-trip) is served by a **separate** `resolve_coord(lat, lon, graph, *, snap_tolerance_m=...) -> int` helper that snaps a coordinate to the nearest uid — keeping the geography seam open *at the resolver layer* rather than leaking it into `ResolvedConstraints`. (`ResolvedConstraints` is request-scoped — built by `plan_route_from_constraints` / a future `resolve_coord`, consumed immediately, never persisted across differently-built artifacts — so uid instability is unexercised.) No new `NodeKey` type, no coordinate type in the constraint — YAGNI. *(Supersedes the spec's §4 Resolved micro-question #2, which kept `tuple[float,float]` — that decision pre-dated PR #4's switch to uid-keyed graph nodes; the spec has not been re-edited.)*
- **OQ-3 — Geocoder** → **deferred**. Only the offline resolver ships. "OfflineResolver" is the conceptual name for the offline resolution *layer*; the shipped surface is the **`resolve_place` function** (no `OfflineResolver` class/protocol — YAGNI; the spec's §4 `resolve_place(name, graph) -> node_key` wording is the same function). An explicit `# future: GeocodeResolver (network)` docstring seam is left in `route/resolve.py` so the deferred network geocoder has a clear landing spot, alongside the `# future: resolve_coord` geography seam (OQ-2).
- **OQ-4 — `route/snap.py` fate** → **already removed** by the noded-build refactor (PR #4); no `git rm` is needed. `build_gazetteer`/`snap_place` (old `route/snap.py`) are superseded by PR1's build-time `pound/graph/gazetteer.py` and the new `route/resolve.py`. `tests/route/test_snap.py` is likewise already gone; Task 2 only adds `tests/route/test_resolve.py`.
- **OQ-5 — The Scope C `_graph`/`_features` test kwargs** → retired in **the same commit** as the `plan_route` signature change (Task 3). All ~15 existing test call sites migrate in that commit so CI never goes red on a half-migrated tree. Tests inject an in-memory graph (built from the Oxford fixture) directly as the `graph=` kwarg — honest, no pickle-IO pretence.
- **OQ-6 — Unknown-name error message** → succinct and user-actionable: `"'X' not found in gazetteer; this build covers N places; try a different name or wait for geocoding support"`. `N` comes from `len(graph.graph["gazetteer"])`. This is the contract migration's user-facing error.
- **OQ-7 — Ambiguous-name behavior** → `resolve_place` raises `ValueError("'Newton' matches N places; specify a nearby town or a more specific name")` for any name whose gazetteer entry is a list (PR1's `ambiguous_place_names` source). Unambiguous common town names — the normal `pound-plan` input — resolve exactly.

## Global Constraints

- Python 3.12+; `uv` for env/dep management. No new dependencies in this plan.
- The request-time path stays pure-Python, no network, no LLM — this plan *strengthens* that property (hermetic-by-construction) rather than relaxing it. `route/resolve.py` is offline-only in this scope.
- OSM data is ODbL: PR2 does not change attribution; the artifact's provenance (`metadata["source"]`, `fetched_at`) flows into `RouteResult.graph_source_date` as before.
- Per AGENTS.md: GitHub Actions pinned by SHA (N/A — no GH Actions in this repo yet), temp files via `mktemp` (N/A here), commit messages conventional-style, frequent small commits.
- The CLI is a **test harness, not a product surface** (design §6): plain human-readable stdout, no `--json`, no fancy formatting, no map, no interactive picker, no amenity display. A future REST API supersedes it; the CLI does not prefigure it.
- Default artifact path: `pound/artifacts/england.pkl`. The CLI must work with the Oxford artifact built by PR1's integration gate for its tests (build the artifact into `tmp_path` in tests).
- All PR1 outputs (embedded `graph.graph["gazetteer"]`, node `name` attributes, augmented validation report) **are landed** (PR #4). If the real England report surprises (e.g. gazetteer size, place-node coincidence with waterway nodes), revise `resolve_place`'s nearest-node tolerance default here before pinning.

## File Structure

```
pound/
├── pyproject.toml                      # MODIFY: add `[project.scripts] pound-plan = "pound.route.cli:main"`
├── README.md                           # MODIFY: document `pound-plan` usage
├── pound/
│   ├── schemas.py                      # MODIFY: add ResolvedConstraints (resolved node uids); Field(gt=0) on days/hours_per_day in both CanalConstraints and ResolvedConstraints
│   ├── route/
│   │   ├── resolve.py                  # NEW: resolve_place (offline resolver — gazetteer + nearest-within-tolerance)
│   │   ├── plan.py                     # MODIFY: pure plan_route(ResolvedConstraints, *, graph) + plan_route_from_constraints convenience; retire _graph/_features; fix NetworkXNoPath + single-day over-budget warning
│   │   ├── cli.py                      # NEW: minimal pound-plan CLI shell
│   │   ├── cost.py                     # NO CHANGE
│   │   └── (snap.py already removed by the PR #4 noded-build refactor)
│   └── (everything else)               # NO CHANGE
└── tests/
    ├── route/
    │   ├── test_resolve.py            # NEW (replaces test_snap.py)
    │   ├── test_plan_route.py        # MODIFY: migrate ~15 call sites to plan_route(Resolved, *, graph=…); add no-path-under-dims + single-day-over-budget + schema tests
    │   ├── test_cli.py                 # NEW: pound-plan over a test-built artifact
    │   └── (test_snap.py already removed by the PR #4 refactor)
    └── (ingest/graph/validate tests)   # NO CHANGE in this plan
```

---

### Task 1: `ResolvedConstraints` + schema `Field(gt=0)` validators

**Files:**

- Modify: `pound/schemas.py`
- Modify: `tests/test_schemas.py`

**Interfaces:**

- Consumes: nothing new.
- Produces:
  - `ResolvedConstraints(BaseModel)` — `start_uid: int`, `end_uid: int`, `days: int`, `hours_per_day: float = 6.0`, `boat_length_m: float | None = None`, `boat_beam_m: float | None = None`, `boat_draft_m: float | None = None`, `boat_height_m: float | None = None`, `allow_derelict: bool = False`. **No `start: str`. No `amenity_prefs`** (amenities deferred; they live only on `CanalConstraints` as a UI hint). `*_uid` are the graph's own node handles (OQ-2), not coordinates.
  - `CanalConstraints` keeps its existing fields; `days` gains `Field(gt=0)`, `hours_per_day` gains `Field(gt=0)`. `ResolvedConstraints.days`/`hours_per_day` gain the same.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_schemas.py`:

```python
import pytest
from pydantic import ValidationError

from pound.schemas import CanalConstraints, ResolvedConstraints


def test_resolved_constraints_has_uids_not_strings():
    rc = ResolvedConstraints(
        start_uid=42, end_uid=43, days=3,
    )
    assert rc.start_uid == 42
    assert rc.end_uid == 43
    assert rc.hours_per_day == 6.0
    assert not hasattr(rc, "start")  # no string start field
    assert not hasattr(rc, "start_node")  # not coordinate-tuple-typed


def test_resolved_constraints_rejects_days_zero():
    with pytest.raises(ValidationError):
        ResolvedConstraints(start_uid=0, end_uid=1, days=0)


def test_resolved_constraints_rejects_hours_per_day_zero():
    with pytest.raises(ValidationError):
        ResolvedConstraints(start_uid=0, end_uid=1, days=1, hours_per_day=0)


def test_canal_constraints_rejects_days_zero():
    with pytest.raises(ValidationError):
        CanalConstraints(start="Oxford", end="Banbury", days=0)


def test_canal_constraints_rejects_hours_per_day_zero():
    with pytest.raises(ValidationError):
        CanalConstraints(start="Oxford", end="Banbury", days=1, hours_per_day=0)


def test_canal_constraints_accepts_positive_days():
    c = CanalConstraints(start="Oxford", end="Banbury", days=1, hours_per_day=6.0)
    assert c.days == 1
    assert c.hours_per_day == 6.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_schemas.py -v`
Expected: FAIL — `ResolvedConstraints` does not exist; `days=0`/`hours_per_day=0` currently accepted.

- [ ] **Step 3: Implement `ResolvedConstraints` and the validators**

Edit `pound/schemas.py`. Replace the `CanalConstraints` class and add `ResolvedConstraints`:

```python
from pydantic import BaseModel, Field


class CanalConstraints(BaseModel):
    start: str
    end: str | None = None  # None => ring / round trip
    days: int = Field(gt=0)
    hours_per_day: float = Field(gt=0, default=6.0)
    boat_length_m: float | None = None
    boat_beam_m: float | None = None
    boat_draft_m: float | None = None
    boat_height_m: float | None = None
    amenity_prefs: list[str] = []  # ["pub", "water_point", "shop", ...]
    allow_derelict: bool = False


class ResolvedConstraints(BaseModel):
    """The pure-routing input: resolved graph node uids, not place names.

    `start_uid`/`end_uid` are the graph's own synthetic internal node handles
    (what `nx.shortest_path` consumes) — not coordinates, not place names.
    Carrying uids means plan_route literally cannot need a name lookup or a
    coord→uid mapping step: it operates on the handles the graph already
    understands. The CLI / Agent Core obtain a ResolvedConstraints from a
    CanalConstraints via route.resolve.resolve_place; a future map-click UI
    obtains one via route.resolve.resolve_coord(lat, lon, graph). Request-scoped
    — built by a resolver with graph access, consumed immediately, never
    persisted across differently-built artifacts. (design §4 contract evolution.)
    """

    start_uid: int
    end_uid: int
    days: int = Field(gt=0)
    hours_per_day: float = Field(gt=0, default=6.0)
    boat_length_m: float | None = None
    boat_beam_m: float | None = None
    boat_draft_m: float | None = None
    boat_height_m: float | None = None
    allow_derelict: bool = False
```

Leave the `Amenity`, `RouteLeg`, `DayPlan`, `RouteResult` classes unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_schemas.py -v`
Expected: PASS — all six new tests pass; existing schema tests (if any) still pass.

*(Note: if any existing Scope C test elsewhere built `CanalConstraints(days=0)` or `hours_per_day=0` expecting success, it now raises; fix it in Task 3's migration commit. The `_long_plan` helper in `test_plan_route.py` uses `days=3`/`days=5`/`days=2`/`hours_per_day=3.0`, all positive — unaffected.)*

- [ ] **Step 5: Run the full hermetic suite to surface any `days=0` callers**

Run: `uv run pytest -q`
Expected: Some tests in `tests/route/test_plan_route.py` may now fail because they call `plan_route` with `_graph`/`_features` and Task 3 hasn't migrated them yet — **that is expected** and is fixed in Task 3 in the *same* commit as the signature change. Do not patch them here. Schema-only tests pass.

- [ ] **Step 6: Commit**

```bash
git add pound/schemas.py tests/test_schemas.py
git commit -m "feat(schemas): ResolvedConstraints + Field(gt=0) on days/hours_per_day"
```

---

### Task 2: `route/resolve.py` `resolve_place` (the offline resolver)

**Files:**

- Create: `pound/route/resolve.py`
- Test: `tests/route/test_resolve.py`
- (`pound/route/snap.py` and `tests/route/test_snap.py` were already removed by the PR #4 noded-build refactor.)

**Interfaces:**

- Consumes: the embedded `graph.graph["gazetteer"]` placed at build time by PR1's `pound/graph/gazetteer.py`, and the graph itself. The gazetteer maps `name -> tuple[float,float] | list[tuple[float,float]]` (PR1's duplicate-name handling).
- Produces:
  - `resolve_place(name: str, graph: nx.Graph, *, snap_tolerance_m: float = 50.0) -> int` — returns the **uid** of the graph node a place name resolves to. Resolution order:
    1. If `name` is in the gazetteer and its value is a single tuple → find the graph node whose `_node_key(nd["lat"], nd["lon"])` equals that tuple; if found, return its **uid**. Otherwise snap to the nearest graph node (haversine over node lat/lon attrs) within `snap_tolerance_m` and return *that node's* **uid**.
    2. If the value is a list (ambiguous) → raise `ValueError("'{name}' matches {N} places; specify a nearby town or a more specific name")`.
    3. If `name` is not in the gazetteer → raise `ValueError("'{name}' not found in gazetteer; this build covers {N} places; try a different name or wait for geocoding support")` where `N = len(graph.graph["gazetteer"])`.
    - `resolve_coord(lat: float, lon: float, graph: nx.Graph, *, snap_tolerance_m: float = 50.0) -> int` — **not implemented this scope**. A `# future: resolve_coord (lat/lon → uid)` seam is left in the module docstring so the deferred map-click-UI path has a clear landing spot; it is mechanically the nearest-node loop `resolve_place` performs, minus the gazetteer lookup. (Do not pre-build it; trigger is a real geography-first caller, not PR2.)
  - `OnlineResolver` — **not implemented**. A `# future: GeocodeResolver (network)` seam is left in the module docstring. (No `Geocoder` protocol ships in this scope.)
  - Linear nearest-node within tolerance (haversine over node lat/lon attrs, since the graph is uid-keyed) — R6: ms at England scale; YAGNI for `rtree`/`shapely` spatial indexing.
- Consumes `pound.graph.build._node_key` (the 7-decimal rounding helper) to match gazetteer tuples against node attrs.

- [ ] **Step 1: Write failing tests**

Create `tests/route/test_resolve.py`:

```python
import networkx as nx
import pytest

from pound.route.resolve import resolve_place


def _graph_with_gazetteer(gaz, nodes):
    """nodes: list of (uid, lat, lon). Mirror build_graph's uid-keyed graph."""
    g = nx.Graph()
    for uid, lat, lon in nodes:
        g.add_node(uid, lat=lat, lon=lon)
    g.graph["gazetteer"] = gaz
    return g


def test_resolve_place_returns_exact_node_when_in_gazetteer():
    g = _graph_with_gazetteer(
        {"Oxford": (51.75, -1.26), "Banbury": (52.06, -1.34)},
        [(0, 51.75, -1.26), (1, 52.06, -1.34)],
    )
    assert resolve_place("Oxford", g) == 0
    assert resolve_place("Banbury", g) == 1


def test_resolve_place_snaps_to_nearest_graph_node_within_tolerance():
    # Place coordinate ~140 m from the nearest graph node; 50 m tolerance fails,
    # 200 m tolerance succeeds and returns the matched node's uid (the nearest uid).
    g = _graph_with_gazetteer(
        {"Pub": (51.7509, -1.2609)},
        [(0, 51.75, -1.26), (1, 51.80, -1.30)],
    )
    with pytest.raises(ValueError, match="not within"):
        resolve_place("Pub", g, snap_tolerance_m=50.0)
    assert resolve_place("Pub", g, snap_tolerance_m=200.0) == 0  # nearest uid


def test_resolve_place_unknown_name_raises_with_count():
    g = _graph_with_gazetteer(
        {"Oxford": (51.75, -1.26)}, [(0, 51.75, -1.26)],
    )
    with pytest.raises(ValueError, match="not found in gazetteer.*covers 1 places"):
        resolve_place("Narnia", g)


def test_resolve_place_ambiguous_name_raises():
    g = _graph_with_gazetteer(
        {"Newton": [(52.0, -1.0), (53.0, -2.0)]},
        [(0, 52.0, -1.0), (1, 53.0, -2.0)],
    )
    with pytest.raises(ValueError, match="matches 2 places"):
        resolve_place("Newton", g)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/route/test_resolve.py -v`
Expected: FAIL — module `pound.route.resolve` does not exist.

- [ ] **Step 3: Implement the resolver**

Create `pound/route/resolve.py`:

```python
"""Place -> graph node resolution (design §4 contract evolution, §6 CLI).

Ships the offline resolver only (a function, not a class — see OQ-3): dict-lookup
of the embedded `graph.graph["gazetteer"]` (built at build time by
pound.graph.gazetteer), then nearest-graph-node-within-tolerance if the place
coordinate isn't already a node. No network, no LLM, hermetic in this scope.

# future: GeocodeResolver (network) — a deferred scope will add a network
# geocoder behind the same resolve_place surface; do not pre-build a protocol
# here. The seam is this docstring + the resolve_place function.
# future: resolve_coord(lat, lon, graph) -> uid — geography-first entry for a
# map-click UI (snap a raw coordinate to the nearest node uid). Mechanically the
# nearest-node loop resolve_place already performs, minus the gazetteer lookup.
# Do not pre-build it; trigger is a real geography-first caller, not PR2.
"""

import math

import networkx as nx

from pound.graph.build import _node_key

_DEFAULT_SNAP_TOLERANCE_M = 50.0


def _haversine_m(a, b) -> float:
    r = 6_371_000.0
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def resolve_place(
    name: str,
    graph: nx.Graph,
    *,
    snap_tolerance_m: float = _DEFAULT_SNAP_TOLERANCE_M,
) -> int:
    """Resolve a place name to the uid of a graph node (offline only).

    Returns the graph's internal node handle (an int) so `plan_route` can consume
    it directly with no coord→uid mapping step. A future geography-first caller
    (map-click UI posting raw lat/lon) uses the deferred resolve_coord helper
    instead — both produce uids, keeping ResolvedConstraints uid-typed. Order:
      1. exact gazetteer hit (single tuple) -> the graph node whose
         `_node_key(nd["lat"], nd["lon"])` equals that tuple, if any; else the
         nearest node within snap_tolerance_m (haversine over node lat/lon attrs).
         Returns the matched node's uid.
      2. ambiguous (gazetteer entry is a list) -> raise ValueError.
      3. name absent -> raise ValueError citing N = len(gazetteer).

    Raises ValueError for unknown / ambiguous names (never KeyError).
    """
    gaz = graph.graph.get("gazetteer", {})
    if name not in gaz:
        raise ValueError(
            f"{name!r} not found in gazetteer; this build covers {len(gaz)} places; "
            f"try a different name or wait for geocoding support"
        )
    entry = gaz[name]
    if isinstance(entry, list):
        raise ValueError(
            f"{name!r} matches {len(entry)} places; "
            f"specify a nearby town or a more specific name"
        )
    target = entry
    # Exact match: a graph node whose rounded _node_key equals the gazetteer coord.
    for uid, nd in graph.nodes(data=True):
        if _node_key(nd["lat"], nd["lon"]) == target:
            return uid
    # Nearest graph node within tolerance (linear; R6: ms at England scale).
    best, best_d = None, math.inf
    for uid, nd in graph.nodes(data=True):
        node_coord = (nd["lat"], nd["lon"])
        d = _haversine_m(target, node_coord)
        if d < best_d:
            best, best_d = uid, d
    if best is None or best_d > snap_tolerance_m:
        raise ValueError(
            f"{name!r} at {target} is not within {snap_tolerance_m} m "
            f"of any graph node (nearest {best_d:.1f} m)"
        )
    return best
```

- [ ] **Step 4: (no-op) `snap.py` and its test are already gone**

The PR #4 noded-build refactor already removed `pound/route/snap.py` and `tests/route/test_snap.py`. Nothing to `git rm`; skip to Step 5.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/route/test_resolve.py -v`
Expected: PASS (4 tests). (No `test_snap.py` remains to collect.)

- [ ] **Step 6: Commit**

```bash
git add pound/route/resolve.py tests/route/test_resolve.py
git commit -m "feat(route): resolve_place (offline gazetteer + nearest-node); snap.py already retired in PR #4"
```

---

### Task 3: Pure `plan_route(ResolvedConstraints, *, graph)` + `plan_route_from_constraints`; retire `_graph`/`_features`; fix error behavior

**Files:**

- Modify: `pound/route/plan.py`
- Modify: `tests/route/test_plan_route.py` (migrate all call sites + add error-behavior + schema tests)

**Interfaces:**

- Consumes: `ResolvedConstraints` (Task 1), `resolve_place` (Task 2's offline resolver), the loaded graph with embedded `gazetteer` and node `name` attributes (PR1).
- Produces:
  - `plan_route(constraints: ResolvedConstraints, *, graph: nx.Graph) -> RouteResult` — pure. Dijkstra by time-cost (Scope C's `weight` via `cost.is_eligible`/`time_min`); leg names from `graph.nodes[key].get("name")` falling back to a coordinate string when a node is unnamed.
  - `plan_route_from_constraints(c: CanalConstraints, *, graph: nx.Graph, snap_tolerance_m: float = 50.0) -> RouteResult` — the convenience bridge: resolves `c.start`/`c.end` via `resolve_place`, builds a `ResolvedConstraints`, calls `plan_route`. This is the path the CLI and Agent Core use.
  - Error-behavior fixes:
    1. **Remove the unweighted `nx.has_path` pre-check.** Catch `NetworkXNoPath` from the weighted `nx.shortest_path` and convert to `ValueError("no path between '{start}' and '{end}' meets the boat's dimensions")`. Plain-unconnected graphs raise the same `ValueError` with an unweighted-message variant (caught from `NetworkXNoPath` raised before any weight function is consulted — detect by trying `nx.has_path` *only inside the `except`* to disambiguate).
    2. **Over-budget day warning is no longer gated on `len(days) > 1`.** Any day whose `cruising_minutes > hours_per_day*60` adds the warning, single- or multi-day.
  - The old `plan_route(CanalConstraints, _graph=…, _features=…)` signature and its `_graph`/`_features` kwargs and the `RuntimeError("artifact loading not wired in this scope")` are **removed entirely**.

- [ ] **Step 1: Rewrite `test_plan_route.py` to the new contract**

Replace `tests/route/test_plan_route.py` contents (the ~15 existing tests migrate to the new seam). Tests now build an in-memory graph from the Oxford fixture (via PR1's `build_graph`, which carries node-ref joins and the embedded-name-free path) and call either pure `plan_route` or `plan_route_from_constraints`:

```python
import copy
import json

import networkx as nx
import pytest

from pound.graph.build import build_graph
from pound.graph.gazetteer import attach_node_names, build_gazetteer
from pound.graph.locks import attach_locks
from pound.ingest.overpass import parse
from pound.route.cost import CRUISE_KMH, LOCK_MINUTES, time_min
from pound.route.plan import plan_route, plan_route_from_constraints
from pound.schemas import CanalConstraints, ResolvedConstraints
from tests.fixtures import oxford_fixture_path


def _graph_and_gaz():
    with open(oxford_fixture_path()) as f:
        raw = json.load(f)
    feats = parse(raw["elements"], None,
                  osm_timestamp=raw["osm3s"]["timestamp_osm_base"])
    g, _ = attach_locks(build_graph(feats), feats)
    attach_node_names(g, feats)
    g.graph["gazetteer"] = build_gazetteer(feats)
    g.graph["fetched_at"] = feats.fetched_at  # plan_route reads graph_source_date here
    return g, feats


def _resolved(start="Oxford", end="Hayfield", **kwargs):
    g, _ = _graph_and_gaz()
    from pound.route.resolve import resolve_place
    return ResolvedConstraints(
        start_uid=resolve_place(start, g),
        end_uid=resolve_place(end, g),
        **kwargs,
    ), g


def test_route_connects_oxford_to_hayfield():
    (rc, g) = _resolved(days=1)
    r = plan_route(rc, graph=g)
    assert r.start == "Oxford"
    assert r.end == "Hayfield"
    assert r.legs[0].from_place == "Oxford"
    assert r.legs[-1].to_place == "Hayfield"
    for i in range(len(r.legs) - 1):
        assert r.legs[i].to_place == r.legs[i + 1].from_place


def test_totals_equal_sum_of_legs():
    (rc, g) = _resolved(days=1)
    r = plan_route(rc, graph=g)
    assert r.total_km == pytest.approx(sum(l.distance_km for l in r.legs))
    assert r.total_locks == sum(l.locks for l in r.legs)
    assert r.total_minutes == sum(l.est_minutes for l in r.legs)


def test_per_leg_minutes_match_cost_formula():
    (rc, g) = _resolved(days=1)
    r = plan_route(rc, graph=g)
    for leg in r.legs:
        expected = round(leg.distance_km / CRUISE_KMH * 60 + leg.locks * LOCK_MINUTES)
        assert leg.est_minutes == expected


def test_total_minutes_matches_time_min_over_edges():
    (rc, g) = _resolved(days=1)
    r = plan_route(rc, graph=g)
    # rounding accumulates across the 4 legs; the existing Scope C test uses abs=1
    assert r.total_minutes == pytest.approx(
        round(time_min(r.total_km * 1000, r.total_locks)), abs=1
    )


def test_locks_counted_on_lock_edge():
    (rc, g) = _resolved(days=1)
    r = plan_route(rc, graph=g)
    assert r.total_locks == 1


def test_warnings_flag_unknown_dims():
    (rc, g) = _resolved(days=1, boat_beam_m=2.0, boat_draft_m=0.8)
    r = plan_route(rc, graph=g)
    assert any("unknown" in w.lower() for w in r.warnings)


def test_graph_source_date_from_metadata():
    (rc, g) = _resolved(days=1)
    r = plan_route(rc, graph=g)
    assert r.graph_source_date == "2026-06-21T12:00:00Z"


def test_ring_raises_not_implemented():
    # Rings are not modelled in ResolvedConstraints (end_uid is required);
    # CanalConstraints(end=None) -> plan_route_from_constraints raises.
    g, _ = _graph_and_gaz()
    with pytest.raises(NotImplementedError, match="rings not yet supported"):
        plan_route_from_constraints(
            CanalConstraints(start="Oxford", end=None, days=1), graph=g
        )


def test_single_day_plan_wraps_legs():
    (rc, g) = _resolved(days=1)
    r = plan_route(rc, graph=g)
    assert len(r.days) == 1
    assert r.days[0].legs == r.legs
    assert r.days[0].cruising_minutes == r.total_minutes


def test_no_path_under_dimensions_raises_valueerror_not_traceback():
    g, _ = _graph_and_gaz()
    rc = ResolvedConstraints(
        start_uid=resolve_first("Oxford", g), end_uid=resolve_first("Hayfield", g),
        days=1, boat_beam_m=99.0, boat_draft_m=99.0,  # bigger than any edge
    )
    with pytest.raises(ValueError, match="no path between"):
        plan_route(rc, graph=g)


def test_single_day_over_budget_warns():
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0  # ~162 min leg, ~3 h budget at 1 h/day
    rc = ResolvedConstraints(
        start_uid=resolve_first("Oxford", g), end_uid=resolve_first("Hayfield", g),
        days=1, hours_per_day=1.0,
    )
    r = plan_route(rc, graph=g)
    assert len(r.days) == 1  # forced single day via max_days cap
    assert r.days[0].cruising_minutes > 1.0 * 60
    assert any("exceed hours_per_day" in w for w in r.warnings)


def _long_resolved(days, hours_per_day, g):
    return ResolvedConstraints(
        start_uid=resolve_first("Oxford", g),
        end_uid=resolve_first("Hayfield", g),
        days=days, hours_per_day=hours_per_day,
    )


def test_multiday_splits_legs_within_budget():
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0
    # 4 edges ~162 min each; hours_per_day=3 -> 180 min budget. Greedy emits
    # one edge per day (each +next would exceed 180) -> 4 days, each in budget.
    rc = _long_resolved(days=4, hours_per_day=3.0, g=g)
    r = plan_route(rc, graph=g)
    assert len(r.days) == 4
    for day in r.days:
        assert day.cruising_minutes <= 3.0 * 60
        assert day.legs


def test_days_partition_legs_exactly():
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0
    rc = _long_resolved(days=4, hours_per_day=3.0, g=g)
    r = plan_route(rc, graph=g)
    flat = [leg for day in r.days for leg in day.legs]
    assert flat == r.legs


def test_days_not_padded_beyond_route():
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0
    rc = _long_resolved(days=5, hours_per_day=3.0, g=g)
    r = plan_route(rc, graph=g)
    assert len(r.days) == 4  # 4 edges need 4 days; days=5 does not pad with empties
    assert all(day.legs for day in r.days)


def test_days_count_never_exceeds_constraints_days():
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0
    rc = _long_resolved(days=2, hours_per_day=3.0, g=g)
    r = plan_route(rc, graph=g)
    assert len(r.days) <= 2


def test_day_index_sequential():
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0
    rc = _long_resolved(days=4, hours_per_day=3.0, g=g)
    r = plan_route(rc, graph=g)
    assert [d.day for d in r.days] == [1, 2, 3, 4]


def test_plan_route_from_constraints_bridge():
    g, _ = _graph_and_gaz()
    r = plan_route_from_constraints(
        CanalConstraints(start="Oxford", end="Hayfield", days=1), graph=g
    )
    assert r.start == "Oxford"
    assert r.end == "Hayfield"
    assert r.legs  # non-empty
```

Add the small `_graph_and_gaz`-based helper at the top (after imports):

```python
def resolve_first(name, g):
    from pound.route.resolve import resolve_place
    return resolve_place(name, g)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/route/test_plan_route.py -v`
Expected: FAIL — `plan_route` still takes `CanalConstraints` + `_graph`/`_features`; `ResolvedConstraints` import path mismatches; new error-behavior tests fail.

- [ ] **Step 3: Implement the pure plan_route + bridge + error fixes**

Rewrite `pound/route/plan.py`:

```python
"""Request-time entry point — pure plan_route over ResolvedConstraints (design §5, Scope D).

Routing runs Dijkstra by time-cost over the loaded graph (passed explicitly);
leg names come from the `name` node attribute PR1 attached (falling back to a
coordinate string). Zero network, zero LLM, hermetic by construction. Rings
(end_uid not applicable / CanalConstraints.end is None) raise
NotImplementedError. The Scope C `_graph`/`_features` test kwargs are retired;
tests inject an in-memory graph directly.

`plan_route_from_constraints` is the CanalConstraints -> resolve -> plan_route
bridge the CLI and Agent Core use.
"""

import networkx as nx

from pound.route.cost import is_eligible, time_min
from pound.route.resolve import resolve_place
from pound.schemas import (
    CanalConstraints, DayPlan, ResolvedConstraints, RouteLeg, RouteResult,
)


def plan_route(constraints: ResolvedConstraints, *, graph: nx.Graph) -> RouteResult:
    """Plan a point-to-point canal route over `graph`. Pure."""
    # ResolvedConstraints carries the graph's own node handles — no coord→uid
    # mapping, no name lookup, no graph mutation. Pure on the resolved uids.
    start, end = constraints.start_uid, constraints.end_uid
    name_attr = lambda uid: graph.nodes[uid].get("name") or f"{graph.nodes[uid]['lat']},{graph.nodes[uid]['lon']}"
    start_name = name_attr(start)

    unknown_edges: list[str] = []

    def weight(u, v, d):
        eligible, unknown = is_eligible(
            constraints.boat_length_m, constraints.boat_beam_m,
            constraints.boat_draft_m, constraints.boat_height_m,
            d["dimensions"],
        )
        if not eligible:
            return None
        if unknown:
            unknown_edges.append(str(d["osm_way_id"]))
        return time_min(d["length_m"], d.get("locks", 0))

    try:
        path = nx.shortest_path(graph, start, end, weight=weight)
    except nx.NetworkXNoPath:
        if nx.has_path(graph, start, end):
            raise ValueError(
                f"no path between '{start_name}' and "
                f"'{name_attr(end)}' meets the boat's dimensions"
            ) from None
        raise ValueError(
            f"no path between '{start_name}' and '{name_attr(end)}' "
            f"(graph is not connected between these nodes)"
        ) from None

    legs: list[RouteLeg] = []
    for u, v in zip(path, path[1:], strict=False):
        d = graph.edges[u, v]
        km = d["length_m"] / 1000.0
        locks = d.get("locks", 0)
        legs.append(RouteLeg(
            from_place=name_attr(u), to_place=name_attr(v),
            distance_km=round(km, 4), locks=locks,
            est_minutes=round(time_min(d["length_m"], locks)),
            flagged_unknown_dims=str(d["osm_way_id"]) in set(unknown_edges),
        ))

    total_km = round(sum(l.distance_km for l in legs), 4)
    total_locks = sum(l.locks for l in legs)
    total_minutes = sum(l.est_minutes for l in legs)

    warnings: list[str] = []
    if unknown_edges:
        warnings.append(f"draft/beam unknown on {len(set(unknown_edges))} segment(s)")

    days = _chunk_days(legs, constraints.hours_per_day, constraints.days)
    budget = constraints.hours_per_day * 60
    if any(day.cruising_minutes > budget for day in days):
        warnings.append("one or more days exceed hours_per_day budget")

    return RouteResult(
        start=start_name, end=name_attr(end), is_ring=False,
        legs=legs, days=days,
        total_km=total_km, total_locks=total_locks, total_minutes=total_minutes,
        amenities=[], warnings=warnings,
        graph_source_date=graph.graph.get("fetched_at", ""),
    )


def plan_route_from_constraints(
    c: CanalConstraints, *, graph: nx.Graph, snap_tolerance_m: float = 50.0,
) -> RouteResult:
    """CanalConstraints -> resolve -> plan_route. The CLI/Agent Core path."""
    if c.end is None:
        raise NotImplementedError("rings not yet supported (design §5.3)")
    resolved = ResolvedConstraints(
        start_uid=resolve_place(c.start, graph, snap_tolerance_m=snap_tolerance_m),
        end_uid=resolve_place(c.end, graph, snap_tolerance_m=snap_tolerance_m),
        days=c.days, hours_per_day=c.hours_per_day,
        boat_length_m=c.boat_length_m, boat_beam_m=c.boat_beam_m,
        boat_draft_m=c.boat_draft_m, boat_height_m=c.boat_height_m,
        allow_derelict=c.allow_derelict,
    )
    return plan_route(resolved, graph=graph)


def _chunk_days(legs, hours_per_day, max_days) -> list[DayPlan]:
    """Greedy cumulative-minute packing (Scope C, unchanged). See git history."""
    budget = hours_per_day * 60.0
    days: list[DayPlan] = []
    current: list[RouteLeg] = []
    current_min = 0

    def flush():
        nonlocal current, current_min
        if current:
            days.append(DayPlan(
                day=len(days) + 1, legs=current,
                end_near=current[-1].to_place, cruising_minutes=current_min,
            ))
            current, current_min = [], 0

    for leg in legs:
        if current and current_min + leg.est_minutes > budget:
            flush()
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
```

- [ ] **Step 4: Run the route tests + the full hermetic suite**

Run: `uv run pytest tests/route/ -v`
Expected: PASS — all migrated `test_plan_route.py` tests + `test_resolve.py` tests green; no `test_snap.py` remains to collect (already removed in PR #4).

Run: `uv run pytest -q`
Expected: PASS — no lingering caller of the old `plan_route(c, _graph=…, _features=…)` anywhere (the only callers were in `test_plan_route.py`, all migrated). `ruff` clean.

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: PASS.

- [ ] **Step 5: Commit (signature change + all test migrations in one commit)**

```bash
git add pound/route/plan.py tests/route/test_plan_route.py
git commit -m "feat(route): pure plan_route(Resolved, *, graph) + plan_route_from_constraints; fix no-path and single-day-over-budget errors; retire _graph/_features"
```

---

### Task 4: Minimal `pound-plan` CLI + production artifact loading + console script

**Files:**

- Create: `pound/route/cli.py`
- Modify: `pyproject.toml` (add console script)
- Modify: `README.md` (document `pound-plan`)
- Test: `tests/route/test_cli.py`

**Interfaces:**

- Consumes: `load_artifact` (PR1/Scope C), `CanalConstraints`, `plan_route_from_constraints` (Task 3), `RouteResult`. Default artifact path: `pound/artifacts/england.pkl`.
- Produces: `[project.scripts] pound-plan = "pound.route.cli:main"` and a `main(argv) -> int` that:
  - Parses: `pound-plan <start> <end> [--days N] [--hours-per-day H] [--boat-beam M] [--boat-draft M] [--boat-length M] [--boat-height M] [--artifact PATH]` (default artifact `pound/artifacts/england.pkl`).
  - Validates `days`/`hours_per_day` via `CanalConstraints` (pydantic `Field(gt=0)`).
  - `load_artifact(artifact_path)` → graph; sets `graph.graph["fetched_at"]` to `metadata["fetched_at"]` (so `plan_route`'s `graph_source_date` is populated).
  - `plan_route_from_constraints(CanalConstraints(...), graph=graph)` → `RouteResult`.
  - Prints human-readable per-leg list + totals + day breakdown + warnings to stdout. No `--json`, no fancy formatting.
  - Catches `ValueError` from `resolve_place` (unknown/ambiguous name) and `plan_route` (no path) → prints a clear message to stderr and returns non-zero (not a traceback).
  - Returns `0` on success.

- [ ] **Step 1: Write failing tests**

Create `tests/route/test_cli.py`:

```python
import json
from pathlib import Path

import pytest

from pound.graph.artifact import save_artifact
from pound.graph.build import build_graph
from pound.graph.gazetteer import attach_node_names, build_gazetteer
from pound.graph.locks import attach_locks
from pound.ingest.overpass import parse
from pound.route import cli
from tests.fixtures import oxford_fixture_path


def _build_oxford_artifact(out: Path) -> Path:
    raw = json.loads(Path(oxford_fixture_path()).read_text())
    feats = parse(raw["elements"], None,
                  osm_timestamp=raw["osm3s"]["timestamp_osm_base"])
    g, _ = attach_locks(build_graph(feats), feats)
    attach_node_names(g, feats)
    g.graph["gazetteer"] = build_gazetteer(feats)
    g.graph["fetched_at"] = feats.fetched_at
    save_artifact(g, out, {
        "source": feats.source, "fetched_at": feats.fetched_at,
        "built_at": "t", "version": "1",
    })
    return out


def test_pound_plan_prints_human_readable_route(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = cli.main(["Oxford", "Hayfield", "--days", "1", "--artifact", str(art)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Oxford" in out
    assert "Hayfield" in out
    # per-leg list + totals + days + warnings sections present
    assert "legs" in out.lower() or "Leg" in out
    assert "total" in out.lower()


def test_pound_plan_rejects_days_zero(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = cli.main(["Oxford", "Hayfield", "--days", "0", "--artifact", str(art)])
    assert rc != 0
    # pydantic validation surfaces a clear message, not a traceback
    assert "days" in capsys.readouterr().err.lower()


def test_pound_plan_unknown_place_clear_error(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = cli.main(["Narnia", "Hayfield", "--days", "1", "--artifact", str(art)])
    assert rc != 0
    err = capsys.readouterr().err
    assert "not found in gazetteer" in err


def test_pound_plan_no_path_clear_error(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = cli.main(["Oxford", "Hayfield", "--days", "1",
                   "--boat-beam", "99", "--boat-draft", "99",
                   "--artifact", str(art)])
    assert rc != 0
    err = capsys.readouterr().err
    assert "no path" in err.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/route/test_cli.py -v`
Expected: FAIL — `pound.route.cli` does not exist; console script absent.

- [ ] **Step 3: Register the console script**

In `pyproject.toml`, extend `[project.scripts]`:

```toml
[project.scripts]
pound-ingest = "pound.ingest.cli:main"
pound-plan = "pound.route.cli:main"
```

Re-sync: `uv sync --extra dev` (hatchling registers the new entry point).

- [ ] **Step 4: Implement the CLI**

Create `pound/route/cli.py`:

```python
"""Minimal pound-plan CLI — a test harness, not a product surface (design §6).

Type two place names, get a route to eyeball that the engine works on real
data. Plain human-readable stdout; no --json, no fancy formatting. A future
REST API supersedes it.

Usage:
    pound-plan <start> <end> [--days N] [--hours-per-day H]
               [--boat-beam M] [--boat-draft M] [--boat-length M] [--boat-height M]
               [--artifact PATH]
"""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from pound.graph.artifact import load_artifact
from pound.route.plan import plan_route_from_constraints
from pound.schemas import CanalConstraints

_DEFAULT_ARTIFACT = Path("pound/artifacts/england.pkl")


def _render(result) -> str:
    lines = [f"Route: {result.start} -> {result.end}"]
    lines.append("Legs:")
    for leg in result.legs:
        lines.append(
            f"  {leg.from_place} -> {leg.to_place}: "
            f"{leg.distance_km} km, {leg.locks} locks, {leg.est_minutes} min"
        )
    lines.append(f"Totals: {result.total_km} km, {result.total_locks} locks, "
                 f"{result.total_minutes} min")
    lines.append("Days:")
    for day in result.days:
        lines.append(f"  Day {day.day}: {day.cruising_minutes} min, "
                     f"ends near {day.end_near}")
    if result.warnings:
        lines.append("Warnings:")
        for w in result.warnings:
            lines.append(f"  - {w}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pound-plan")
    p.add_argument("start")
    p.add_argument("end")
    p.add_argument("--days", type=int, required=True)
    p.add_argument("--hours-per-day", type=float, default=6.0)
    p.add_argument("--boat-beam", type=float, default=None)
    p.add_argument("--boat-draft", type=float, default=None)
    p.add_argument("--boat-length", type=float, default=None)
    p.add_argument("--boat-height", type=float, default=None)
    p.add_argument("--artifact", default=str(_DEFAULT_ARTIFACT))
    args = p.parse_args(argv)

    try:
        constraints = CanalConstraints(
            start=args.start, end=args.end, days=args.days,
            hours_per_day=args.hours_per_day,
            boat_length_m=args.boat_length, boat_beam_m=args.boat_beam,
            boat_draft_m=args.boat_draft, boat_height_m=args.boat_height,
        )
    except ValidationError as e:
        print(str(e), file=sys.stderr)
        return 2

    artifact = Path(args.artifact)
    if not artifact.exists():
        print(f"artifact not found: {artifact}", file=sys.stderr)
        return 2

    graph, meta = load_artifact(artifact)
    graph.graph["fetched_at"] = meta.get("fetched_at", "")

    try:
        result = plan_route_from_constraints(constraints, graph=graph)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(_render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 5: Run the CLI tests + full suite + ruff**

Run: `uv run pytest tests/route/test_cli.py -v`
Run: `uv run pytest -q`
Run: `uv run ruff check . && uv run ruff format --check .`
Expected: PASS across the board.

- [ ] **Step 6: Manual sanity check against the real England artifact (human-gated)**

After PR1 builds `pound/artifacts/england.pkl`:

```bash
uv run pound-plan Oxford Banbury --days 3
```

A human eyeballs the printed route for sanity. This is design §6 / §7's playable testing — not a CI gate.

- [ ] **Step 7: Update the README**

In `README.md`, add (after the bulk-ingest section PR1 added):

```markdown
## Planning a route (`pound-plan`)

Minimal, eyeballing-only surface over the loaded artifact:

```bash
uv run pound-plan Oxford Banbury --days 3
# override the artifact:
uv run pound-plan Oxford Banbury --days 3 --artifact pound/artifacts/england.pkl
# boat constraints:
uv run pound-plan Oxford Banbury --days 3 --boat-beam 2.0 --boat-draft 0.8
```

Unknown / ambiguous place names and un-routable constraints produce a clear
error, not a traceback. A REST API will eventually supersede this CLI for
product use; it is deliberately a test harness, not a planner.

```

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml pound/route/cli.py tests/route/test_cli.py README.md
git commit -m "feat(route): minimal pound-plan CLI + production artifact loading"
```

---

## PR2 acceptance (exit gate, design §1 consumer-facing criterion)

- `uv run pytest -q` is green **without** `pyosmium`/`osmium-tool` installed (bulk tests still skip; route CLI tests build a fixture-scale artifact into `tmp_path`).
- No caller of the old `plan_route(CanalConstraints, _graph=…, _features=…)` exists anywhere in the tree (`grep -rn "_features" pound/ tests/` returns nothing).
- `pound/route/snap.py` and `tests/route/test_snap.py` are gone; `from pound.route.resolve import resolve_place` is the only place-resolution entry point.
- `pound-plan Oxford Hayfield --days 1 --artifact <oxford.pkl>` prints a real route (per legs, totals, days, warnings); exit `0`.
- `pound-plan Oxford Hayfield --days 0` exits non-zero with a clear pydantic error; `pound-plan Narnia Hayfield --days 1` exits non-zero with "not found in gazetteer"; `pound-plan Oxford Hayfield --days 1 --boat-beam 99 --boat-draft 99` exits non-zero with "no path between ... meets the boat's dimensions".
- Over the PR1 England artifact, `pound-plan Oxford Banbury --days 3` prints a real England route a human eyeballs (design §7 real-data tuning — human-gated, not CI).

## Deferred (do not implement here)

Amenities (§5.4, §3.2 CRT), mooring-aware day placement ("end near winding hole"), rings (`end=None` round trips — still `NotImplementedError`), the external oracle (§8), the network geocoder (`# future: GeocodeResolver` seam left in `resolve.py`), the geography-first `resolve_coord(lat, lon, graph) -> int` helper for a future map-click UI (`# future` seam left in `resolve.py`; mechanically the nearest-node loop `resolve_place` already performs minus the gazetteer lookup — defer to the scope that builds the UI), full-GB scale beyond the England extract, `rtree`/`shapely`/`STRtree` spatial indexing (linear nearest-node is ms at England scale), and the `CanalConstraints.allow_derelict` routing flag (accepted by schema, honored in a future scope).
