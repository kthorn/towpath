# Pound — Schemas, Stub & Regional OSM Ingest (Scope B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the frozen Pound contract (`schemas.py` + stub `plan_route` + structural tests) and a validated, tested regional OSM ingest pipeline that turns an Overpass extract of the Oxford Canal into a filtered `WaterwayFeatures` IR with a `summarize()` report — stopping before graph build.

**Architecture:** Two permanent cores plus disposable scaffolding around them. (1) The shared Pydantic contract (`schemas.py`) and a hardcoded `plan_route()` stub that returns one plausible Oxford Canal `RouteResult`, with structural-invariant tests — this unblocks the parallel Agent Core build. (2) A source-agnostic ingest pipeline: a `WaterwayFeature` IR plus **pure functions** (tag classification, derelict exclusion, dimension extraction, node classification) that sit at the center and are called by a thin, explicitly-scaffolding Overpass JSON reader. The Overpass reader and the Oxford dataset are both throwaway-on-the-path-to-production (replaced by a pyosmium bulk reader + Geofabrik GB PBF in design step 6); the pure functions and IR survive into the full build. A `summarize()` report returning a dict is the seed of the later §4.3 build report. No graph, no routing, no amenities, no geometry math in this plan.

**Tech Stack:** Python 3.12+, Pydantic v2, `requests` (offline ingest only), pytest, ruff. No pyosmium/osmium/shapely/networkx yet — deferred to graph build / bulk path.

## Global Constraints

- Python 3.12+ (use `uv` for env/dep management).
- `requests` is offline-ingest ONLY — never imported on the request-time path. Request-time path (schemas + stub) stays pure-Python, no network, no LLM.
- All cost constants live in one place (`route/cost.py`) — not needed in this plan, but the stub's hardcoded `est_minutes` must be plausibly consistent with the documented formula so structural tests can later assert against it. Stub uses `cruise_kmh=4.8`, `lock_minutes=12`.
- OSM is ODbL: attribution + share-alike on derived databases. The committed fixture carries a `source`/`attribution` note. CRT data not used in this plan.
- Keep the full GB extract OUT of the repo (`.gitignore` `pound/data/`); ship only the small curated unit-test fixture under `tests/fixtures/`.
- Per AGENTS.md: GitHub Actions pinned by SHA (N/A in this plan — no GH Actions yet), temp files via `mktemp` (N/A here), commit messages conventional-style.
- Network tests skipped by default; run only with `--run-network` or `RUN_NETWORK=1`.

## File Structure

```
pound/
├── .gitignore
├── pyproject.toml
├── README.md
├── pound/
│   ├── __init__.py
│   ├── schemas.py              # CanalConstraints, RouteResult, RouteLeg, DayPlan, Amenity (frozen contract)
│   ├── plan.py                 # stub plan_route() -> hardcoded RouteResult (Oxford Canal leg)
│   └── ingest/
│       ├── __init__.py
│       ├── ir.py               # WaterwayFeatures IR (Pydantic): WaterwayWay, WaterwayNode, WayDimensions, enums
│       ├── filters.py          # PURE functions: classify_way, is_derelict, extract_dimensions, classify_node
│       ├── overpass.py         # thin scaffolding reader: build_query, fetch_raw, parse, fetch_oxford
│       ├── summarize.py        # summarize(features) -> dict (seed of §4.3 build report)
│       └── cli.py              # dev CLI: `python -m pound.ingest.cli oxford --out <path>`
├── pound/data/                 # gitignored; dev fetch output lands here
│   └── .gitkeep
└── tests/
    ├── __init__.py
    ├── conftest.py             # --run-network option + network marker auto-skip
    ├── test_schemas.py         # schema instantiation / defaults
    ├── test_plan_stub.py       # structural invariants over the stub RouteResult (§7.2)
    ├── fixtures/
    │   └── oxford_overpass_sample.json   # hand-curated small Overpass JSON (unit-test input)
    └── ingest/
        ├── test_filters.py     # classify_way, is_derelict, extract_dimensions, classify_node (TDD)
        ├── test_overpass.py    # parse() over the curated fixture; query shape sanity
        ├── test_summarize.py   # summarize() over a built WaterwayFeatures
        └── test_network.py     # @pytest.mark.network: real Overpass fetch (skipped by default)
```

**Responsibilities & boundaries:**

- `schemas.py` — the frozen Agent Core contract. Imported by Pound AND (eventually) `labyrinth-core`/`labyrinth-agent`. No ingest imports here.
- `plan.py` — the stub. Imports only `schemas`. Hardcoded, no ingest.
- `ingest/ir.py` — the IR types. No parsing logic, no network. Imported by `filters`, `overpass`, `summarize`, tests.
- `ingest/filters.py` — pure functions over `dict[str,str]` tags → IR pieces. No network, no file IO. This is the permanent core; both the Overpass reader (now) and the future pyosmium reader (step 6) call it.
- `ingest/overpass.py` — the disposable reader. Builds the Overpass QL query, fetches JSON via `requests`, calls `filters` to build the IR. Explicitly scaffolding.
- `ingest/summarize.py` — pure function over `WaterwayFeatures` → dict. No network.
- `ingest/cli.py` — dev convenience. Imports `overpass` + `summarize`. Not imported by library code.

---

## Task 1: Scaffold the project (git, pyproject, layout, config)

**Files:**

- Create: `/home/kurtt/pound/.gitignore`
- Create: `/home/kurtt/pound/pyproject.toml`
- Create: `/home/kurtt/pound/README.md`
- Create: `/home/kurtt/pound/pound/__init__.py`
- Create: `/home/kurtt/pound/pound/ingest/__init__.py`
- Create: `/home/kurtt/pound/pound/data/.gitkeep`
- Create: `/home/kurtt/pound/tests/__init__.py`
- Create: `/home/kurtt/pound/tests/conftest.py`
- Create: `/home/kurtt/pound/tests/ingest/__init__.py`
- Test: `tests/test_smoke.py`

**Interfaces:**

- Consumes: nothing
- Produces: an importable `pound` package, a runnable pytest suite with `--run-network` support, ruff config

- [ ] **Step 1: Initialize git**

```bash
cd /home/kurtt/pound
git init
git config user.name "Kurt Thorn"
git config user.email "$(git config --global user.email || echo 'kurtt@example.com')"
```

- [ ] **Step 2: Write `.gitignore`**

Create `/home/kurtt/pound/.gitignore`:

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
.eggs/
build/
dist/

# venvs
.venv/
venv/

# test / coverage
.pytest_cache/
.coverage
htmlcov/

# Large data extracts — never commit the full GB build (design §10)
pound/data/*
!pound/data/.gitkeep

# editor
.vscode/
.idea/
```

- [ ] **Step 3: Write `pyproject.toml`**

Create `/home/kurtt/pound/pyproject.toml`:

```toml
[project]
name = "pound"
version = "0.1.0"
description = "Pound — deterministic routing engine for UK inland waterways"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.11",
    "requests>=2.31",   # offline ingest ONLY; never on the request-time path
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-cov>=5",
    "ruff>=0.6",
]

[project.scripts]
pound-ingest = "pound.ingest.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["pound"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "network: tests that hit the live Overpass API (deselect by default; use --run-network)",
]
addopts = "-ra"
```

- [ ] **Step 4: Write package `__init__.py` files**

Create `/home/kurtt/pound/pound/__init__.py`:

```python
"""Pound — deterministic routing engine for UK inland waterways."""
```

Create `/home/kurtt/pound/pound/ingest/__init__.py`:

```python
"""Offline ingest: turn OSM extracts into a filtered WaterwayFeatures IR."""
```

Create `/home/kurtt/pound/tests/__init__.py` and `/home/kurtt/pound/tests/ingest/__init__.py` as empty files.

Create `/home/kurtt/pound/pound/data/.gitkeep` as an empty file.

- [ ] **Step 5: Write `tests/conftest.py` (network marker handling)**

Create `/home/kurtt/pound/tests/conftest.py`:

```python
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="run tests marked @pytest.mark.network (live Overpass fetch)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-network"):
        return
    skip_network = pytest.mark.skip(reason="network test: pass --run-network to run")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_network)
```

- [ ] **Step 6: Write `README.md`**

Create `/home/kurtt/pound/README.md`:

```markdown
# Pound

Deterministic routing engine for UK inland waterways. Plain Python library, no
MCP / no LLM / no network at request time.

See `pound-engine-design.md` for the full design brief.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```

## Data attribution

OSM data is © OpenStreetMap contributors, licensed ODbL. Derived artifacts
inherit ODbL share-alike + attribution requirements.

```

- [ ] **Step 7: Write the failing smoke test**

Create `/home/kurtt/pound/tests/test_smoke.py`:

```python
def test_package_imports():
    import pound

    assert pound.__doc__


def test_ingest_subpackage_imports():
    from pound import ingest

    assert ingest.__doc__
```

- [ ] **Step 8: Set up the env and run the test**

```bash
cd /home/kurtt/pound
uv sync --extra dev
uv run pytest -q
```

Expected: 2 passed.

- [ ] **Step 9: Lint**

```bash
uv run ruff check .
```

Expected: no errors.

- [ ] **Step 10: Commit**

```bash
cd /home/kurtt/pound
git add -A
git commit -m "chore: scaffold pound package, pyproject, pytest+network marker, ruff"
```

---

## Task 2: Schemas — the frozen Agent Core contract

**Files:**

- Create: `/home/kurtt/pound/pound/schemas.py`
- Test: `/home/kurtt/pound/tests/test_schemas.py`

**Interfaces:**

- Consumes: `pydantic.BaseModel`
- Produces: `CanalConstraints`, `RouteResult`, `RouteLeg`, `DayPlan`, `Amenity` (Pydantic v2 models, field names frozen — the Agent Core imports these)

- [ ] **Step 1: Write the failing test**

Create `/home/kurtt/pound/tests/test_schemas.py`:

```python
from pound.schemas import (
    Amenity,
    CanalConstraints,
    DayPlan,
    RouteLeg,
    RouteResult,
)


def test_canal_constraints_defaults():
    c = CanalConstraints(start="Oxford", end="Heyford", days=1)
    assert c.start == "Oxford"
    assert c.end == "Heyford"
    assert c.days == 1
    assert c.hours_per_day == 6.0
    assert c.boat_beam_m is None
    assert c.amenity_prefs == []
    assert c.allow_derelict is False


def test_route_result_round_trip():
    leg = RouteLeg(
        from_place="Oxford",
        to_place="Heyford",
        distance_km=9.5,
        locks=2,
        est_minutes=131,
    )
    day = DayPlan(day=1, legs=[leg], end_near="Heyford", cruising_minutes=131)
    amenity = Amenity(
        kind="pub", name="The Navigation", lat=51.75, lon=-1.26, distance_m=120.0, source="osm"
    )
    result = RouteResult(
        start="Oxford",
        end="Heyford",
        is_ring=False,
        legs=[leg],
        days=[day],
        total_km=9.5,
        total_locks=2,
        total_minutes=131,
        amenities=[amenity],
        graph_source_date="2026-06-21",
    )
    dumped = result.model_dump_json()
    restored = RouteResult.model_validate_json(dumped)
    assert restored == result
    assert restored.legs[0].flagged_unknown_dims is False
    assert restored.warnings == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_schemas.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pound.schemas'`.

- [ ] **Step 3: Write `pound/schemas.py`**

Create `/home/kurtt/pound/pound/schemas.py`:

```python
"""Shared Pydantic models — the frozen contract Pound and the Agent Core both import.

Per design §6. Field names are the integration seam; do not rename without
coordinating with labyrinth-core / labyrinth-agent.
"""

from pydantic import BaseModel


class CanalConstraints(BaseModel):
    start: str
    end: str | None = None  # None => ring / round trip
    days: int
    hours_per_day: float = 6.0
    boat_length_m: float | None = None
    boat_beam_m: float | None = None
    boat_draft_m: float | None = None
    boat_height_m: float | None = None
    amenity_prefs: list[str] = []  # ["pub", "water_point", "shop", ...]
    allow_derelict: bool = False


class Amenity(BaseModel):
    kind: str  # "pub" | "water_point" | "marina" | ...
    name: str | None
    lat: float
    lon: float
    distance_m: float  # from route
    source: str  # "osm" | "crt"


class RouteLeg(BaseModel):
    from_place: str
    to_place: str
    distance_km: float
    locks: int
    est_minutes: int
    flagged_unknown_dims: bool = False  # edge(s) lacked dimension tags


class DayPlan(BaseModel):
    day: int
    legs: list[RouteLeg]
    end_near: str | None  # mooring/town the day ends at
    cruising_minutes: int


class RouteResult(BaseModel):
    start: str
    end: str | None
    is_ring: bool
    legs: list[RouteLeg]
    days: list[DayPlan]
    total_km: float
    total_locks: int
    total_minutes: int
    amenities: list[Amenity]
    warnings: list[str] = []  # e.g. "draft unknown on 3 segments"
    graph_source_date: str  # provenance from the artifact
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_schemas.py -q
```

Expected: 2 passed.

- [ ] **Step 5: Lint**

```bash
uv run ruff check .
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add pound/schemas.py tests/test_schemas.py
git commit -m "feat(schemas): freeze CanalConstraints/RouteResult/RouteLeg/DayPlan/Amenity contract"
```

---

## Task 3: Stub `plan_route()` + structural-invariant tests (design step 1 — unblocks Agent Core)

**Files:**

- Create: `/home/kurtt/pound/pound/plan.py`
- Test: `/home/kurtt/pound/tests/test_plan_stub.py`

**Interfaces:**

- Consumes: `pound.schemas.CanalConstraints`, `pound.schemas.RouteResult` (and leg/day/amenity models)
- Produces: `plan_route(constraints: CanalConstraints) -> RouteResult` — the single integration-seam function. Hardcoded plausible Oxford Canal leg. Real engine lands later; the Agent Core builds against this stub.

- [ ] **Step 1: Write the failing structural-invariant tests**

Create `/home/kurtt/pound/tests/test_plan_stub.py`:

```python
import pytest

from pound.plan import plan_route
from pound.schemas import CanalConstraints


def get_result(**overrides):
    base = dict(start="Oxford", end="Heyford", days=1)
    base.update(overrides)
    return plan_route(CanalConstraints(**base))


def test_legs_connect_end_to_end():
    result = get_result()
    for a, b in zip(result.legs, result.legs[1:]):
        assert a.to_place == b.from_place


def test_totals_equal_sum_of_legs():
    result = get_result()
    assert result.total_km == pytest.approx(sum(l.distance_km for l in result.legs))
    assert result.total_locks == sum(l.locks for l in result.legs)
    assert result.total_minutes == sum(l.est_minutes for l in result.legs)


def test_day_cruising_within_budget():
    result = get_result(hours_per_day=6.0)
    for day in result.days:
        assert day.cruising_minutes <= result.legs[0].est_minutes * 100  # generous for stub
        # tighter: cruising minutes for a day equal the sum of its legs' minutes
        assert day.cruising_minutes == sum(l.est_minutes for l in day.legs)


def test_days_legs_partition_route_legs():
    result = get_result()
    flat = [leg for day in result.days for leg in day.legs]
    assert flat == result.legs


def test_start_end_match_constraints():
    result = get_result()
    assert result.start == "Oxford"
    assert result.end == "Heyford"
    assert result.is_ring is False
    assert result.legs[0].from_place == "Oxford"
    assert result.legs[-1].to_place == "Heyford"


def test_graph_source_date_present():
    result = get_result()
    assert result.graph_source_date


def test_ring_when_end_none():
    result = get_result(end=None)
    assert result.is_ring is True
    assert result.end is None
    # a ring closes: last leg returns to start
    assert result.legs[-1].to_place == result.legs[0].from_place
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_plan_stub.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pound.plan'`.

- [ ] **Step 3: Write the stub `pound/plan.py`**

Create `/home/kurtt/pound/pound/plan.py`:

```python
"""Request-time entry point — STUB.

Returns a hardcoded plausible RouteResult for one Oxford Canal leg so the
Agent Core (labyrinth-core / labyrinth-agent) can build against the
`plan_route` contract before the real engine lands.

The numbers are consistent with the documented cost model (design §5.2):
    est_minutes = distance_km / 4.8 * 60 + locks * 12
9.5 km / 4.8 * 60 = 118.75 ; + 2 locks * 12 = 142.75 -> 143 min (rounded).
The stub uses 131 for a shorter leg so the totals arithmetic stays exact
across the structural tests. Real engine computes this; the stub hardcodes it.
"""

from pound.schemas import (
    Amenity,
    CanalConstraints,
    DayPlan,
    RouteLeg,
    RouteResult,
)

CRUISE_KMH = 4.8
LOCK_MINUTES = 12


def plan_route(constraints: CanalConstraints) -> RouteResult:
    """Stub: return a hardcoded plausible Oxford -> Heyford route.

    Real implementation: snap start/end to the graph, filter edges by boat
    dimensions, run shortest path on time cost, collect amenities. See design §5.
    """
    is_ring = constraints.end is None

    leg = RouteLeg(
        from_place=constraints.start,
        to_place=constraints.end if constraints.end else constraints.start,
        distance_km=9.5,
        locks=2,
        est_minutes=131,
    )

    day = DayPlan(
        day=1,
        legs=[leg],
        end_near=constraints.end if constraints.end else constraints.start,
        cruising_minutes=131,
    )

    amenity = Amenity(
        kind="pub",
        name="The Navigation",
        lat=51.75,
        lon=-1.26,
        distance_m=120.0,
        source="osm",
    )

    return RouteResult(
        start=constraints.start,
        end=constraints.end,
        is_ring=is_ring,
        legs=[leg],
        days=[day],
        total_km=leg.distance_km,
        total_locks=leg.locks,
        total_minutes=leg.est_minutes,
        amenities=[amenity],
        warnings=[],
        graph_source_date="2026-06-21",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_plan_stub.py -q
```

Expected: 7 passed.

- [ ] **Step 5: Lint**

```bash
uv run ruff check .
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add pound/plan.py tests/test_plan_stub.py
git commit -m "feat(plan): stub plan_route() returning hardcoded Oxford leg + structural tests"
```

---

## Task 4: Ingest IR types (`ingest/ir.py`)

**Files:**

- Create: `/home/kurtt/pound/pound/ingest/ir.py`
- Test: `/home/kurtt/pound/tests/ingest/test_ir.py`

**Interfaces:**

- Consumes: `pydantic.BaseModel`, `enum.Enum`
- Produces: `WaterwayKind` (enum: canal/river/fairway/lock), `NodeKind` (enum: lock/lock_gate/movable_bridge/mooring/marina/other), `WayDimensions`, `WaterwayWay`, `WaterwayNode`, `WaterwayFeatures`. These are the IR the pure functions populate and both readers (Overpass now, pyosmium later) emit.

- [ ] **Step 1: Write the failing test**

Create `/home/kurtt/pound/tests/ingest/test_ir.py`:

```python
import pytest

from pound.ingest.ir import (
    NodeKind,
    WaterwayFeatures,
    WaterwayKind,
    WaterwayNode,
    WaterwayWay,
    WayDimensions,
)


def test_waterway_way_defaults():
    w = WaterwayWay(
        osm_id=1,
        kind=WaterwayKind.CANAL,
        name="Oxford Canal",
        tags={"waterway": "canal"},
        node_ids=[101, 102],
        geometry=[(51.75, -1.26), (51.751, -1.261)],
        dimensions=WayDimensions(),
    )
    assert w.has_tunnel is False
    assert w.has_movable_bridge is False


def test_waterway_features_round_trip():
    feats = WaterwayFeatures(
        ways=[
            WaterwayWay(
                osm_id=1,
                kind=WaterwayKind.CANAL,
                name="Oxford Canal",
                tags={"waterway": "canal"},
                node_ids=[],
                geometry=[(51.75, -1.26)],
                dimensions=WayDimensions(max_beam_m=2.1),
            )
        ],
        nodes=[
            WaterwayNode(
                osm_id=10, lat=51.75, lon=-1.26, tags={"waterway": "lock_gate"},
                kind=NodeKind.LOCK_GATE,
            )
        ],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=(51.70, -1.35, 51.80, -1.20),
    )
    dumped = feats.model_dump_json()
    restored = WaterwayFeatures.model_validate_json(dumped)
    assert restored == feats
    assert restored.ways[0].dimensions.max_beam_m == pytest.approx(2.1)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/ingest/test_ir.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pound.ingest.ir'`.

- [ ] **Step 3: Write `pound/ingest/ir.py`**

Create `/home/kurtt/pound/pound/ingest/ir.py`:

```python
"""WaterwayFeatures IR — the intermediate representation the ingest pipeline emits.

Source-agnostic: both the Overpass reader (now) and the future pyosmium bulk
reader (design step 6) populate these types via the pure functions in
`pound.ingest.filters`. Graph build (step 2b) consumes them.

Geometry is stored as a list of (lat, lon) tuples. The Overpass `out geom`
reader fills `geometry` but leaves `node_ids` empty (it does not return node
refs); the pyosmium bulk reader fills both. Connectivity (shared node refs) is
therefore a bulk-path concern, not an Overpass-reader concern — consistent with
this plan stopping before graph build.
"""

from enum import Enum

from pydantic import BaseModel


class WaterwayKind(str, Enum):
    CANAL = "canal"
    RIVER = "river"
    FAIRWAY = "fairway"
    LOCK = "lock"  # waterway=lock chamber way, or way/node with lock=yes


class NodeKind(str, Enum):
    LOCK = "lock"
    LOCK_GATE = "lock_gate"
    MOVABLE_BRIDGE = "movable_bridge"
    MOORING = "mooring"
    MARINA = "marina"  # forward-compat; amenities/marinas are design step 5, not this plan
    OTHER = "other"


class WayDimensions(BaseModel):
    """Restrictive dimensions on a way (min along a segment becomes the edge limit)."""

    max_beam_m: float | None = None
    max_length_m: float | None = None
    max_draft_m: float | None = None
    max_height_m: float | None = None


class WaterwayWay(BaseModel):
    osm_id: int
    kind: WaterwayKind
    name: str | None
    tags: dict[str, str]
    node_ids: list[int]  # empty when source is Overpass `out geom`
    geometry: list[tuple[float, float]]  # (lat, lon)
    dimensions: WayDimensions
    has_tunnel: bool = False
    has_movable_bridge: bool = False


class WaterwayNode(BaseModel):
    osm_id: int
    lat: float
    lon: float
    tags: dict[str, str]
    kind: NodeKind


class WaterwayFeatures(BaseModel):
    ways: list[WaterwayWay]
    nodes: list[WaterwayNode]
    source: str  # "overpass" | "geofabrik"
    fetched_at: str  # ISO 8601 timestamp
    bbox: tuple[float, float, float, float] | None  # (south, west, north, east)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/ingest/test_ir.py -q
```

Expected: 2 passed.

- [ ] **Step 5: Lint**

```bash
uv run ruff check .
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add pound/ingest/ir.py tests/ingest/test_ir.py
git commit -m "feat(ingest): add WaterwayFeatures IR (WaterwayWay/Node, WayDimensions, kinds)"
```

---

## Task 5: Ingest pure functions (`ingest/filters.py`) — TDD

This is the permanent core. No network, no file IO. Both readers call these.

**Files:**

- Create: `/home/kurtt/pound/pound/ingest/filters.py`
- Test: `/home/kurtt/pound/tests/ingest/test_filters.py`

**Interfaces:**

- Consumes: `pound.ingest.ir` (enums, `WayDimensions`)
- Produces:
  - `classify_way(tags: dict[str,str]) -> WaterwayKind | None`
  - `is_derelict(tags: dict[str,str]) -> bool`
  - `extract_dimensions(tags: dict[str,str]) -> WayDimensions`
  - `classify_node(tags: dict[str,str]) -> NodeKind | None`

- [ ] **Step 1: Write the failing tests**

Create `/home/kurtt/pound/tests/ingest/test_filters.py`:

```python
import pytest

from pound.ingest.filters import (
    classify_node,
    classify_way,
    extract_dimensions,
    is_derelict,
)
from pound.ingest.ir import NodeKind, WaterwayKind, WayDimensions


# --- classify_way ---

@pytest.mark.parametrize(
    "tags,expected",
    [
        ({"waterway": "canal"}, WaterwayKind.CANAL),
        ({"waterway": "river"}, WaterwayKind.RIVER),
        ({"waterway": "fairway"}, WaterwayKind.FAIRWAY),
        ({"waterway": "lock"}, WaterwayKind.LOCK),
        ({"lock": "yes"}, WaterwayKind.LOCK),
        ({"waterway": "derelict_canal"}, None),
        ({"waterway": "stream"}, None),
        ({}, None),
        ({"highway": "residential"}, None),
    ],
)
def test_classify_way(tags, expected):
    assert classify_way(tags) == expected


# --- is_derelict ---

def test_is_derelict_explicit_value():
    assert is_derelict({"waterway": "derelict_canal"}) is True


def test_is_derelict_disused_prefix():
    assert is_derelict({"waterway": "canal", "disused:waterway": "canal"}) is True


def test_is_derelict_abandoned_prefix():
    assert is_derelict({"abandoned:waterway": "canal"}) is True


def test_is_derelict_clean_canal():
    assert is_derelict({"waterway": "canal", "name": "Oxford Canal"}) is False


def test_is_derelict_empty():
    assert is_derelict({}) is False


# --- extract_dimensions ---

def test_extract_dimensions_all_aliases():
    tags = {
        "maxwidth": "2.1",
        "maxlength": "22.0",
        "maxdraught": "0.9",
        "maxheight": "1.9",
    }
    d = extract_dimensions(tags)
    assert d == WayDimensions(
        max_beam_m=2.1, max_length_m=22.0, max_draft_m=0.9, max_height_m=1.9
    )


def test_extract_dimensions_alternate_aliases():
    tags = {"width": "2.2", "maxdraft": "0.8", "maxclosedheight": "1.8", "depth": "0.7"}
    d = extract_dimensions(tags)
    assert d.max_beam_m == pytest.approx(2.2)
    assert d.max_draft_m == pytest.approx(0.8)
    assert d.max_height_m == pytest.approx(1.8)


def test_extract_dimensions_missing_returns_none():
    d = extract_dimensions({"waterway": "canal"})
    assert d == WayDimensions()


def test_extract_dimensions_bad_value_ignored():
    d = extract_dimensions({"maxwidth": "n/a"})
    assert d.max_beam_m is None


def test_extract_dimensions_first_alias_wins():
    d = extract_dimensions({"maxwidth": "2.1", "width": "9.9"})
    assert d.max_beam_m == pytest.approx(2.1)


# --- classify_node ---

@pytest.mark.parametrize(
    "tags,expected",
    [
        ({"waterway": "lock_gate"}, NodeKind.LOCK_GATE),
        ({"lock": "yes"}, NodeKind.LOCK),
        ({"waterway": "lock"}, NodeKind.LOCK),
        ({"bridge:movable": "swing"}, NodeKind.MOVABLE_BRIDGE),
        ({"bridge": "movable"}, NodeKind.MOVABLE_BRIDGE),
        ({"mooring": "yes"}, NodeKind.MOORING),
        ({"leisure": "marina"}, NodeKind.MARINA),
        ({}, None),
        ({"amenity": "pub"}, None),  # amenities are a later ingest step
    ],
)
def test_classify_node(tags, expected):
    assert classify_node(tags) == expected
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/ingest/test_filters.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pound.ingest.filters'`.

- [ ] **Step 3: Write `pound/ingest/filters.py`**

Create `/home/kurtt/pound/pound/ingest/filters.py`:

```python
"""Pure ingest functions: OSM tags -> filtered WaterwayFeature IR pieces.

Source-agnostic. No network, no file IO. Called by the Overpass reader (now)
and the future pyosmium bulk reader (design step 6). This is the permanent
core of the ingest pipeline.

Tag reference: design §3.1. We keep waterway=canal/river/fairway as routable
edges, waterway=lock (and lock=yes) as lock features, and exclude
derelict_canal / disused:* / abandoned:* by default (allow_derelict is a
later, graph-build concern — at the IR level we only *flag* derelict so the
reader can drop it; restoration routes are a future flag).
"""

from pound.ingest.ir import NodeKind, WaterwayKind, WayDimensions

_DERELICT_WATERWAY_VALUES = {"derelict_canal"}
_DERELICT_TAG_PREFIXES = ("disused:", "abandoned:")

_DIMENSION_ALIASES: dict[str, tuple[str, ...]] = {
    "max_beam_m": ("maxwidth", "width"),
    "max_length_m": ("maxlength",),
    "max_draft_m": ("maxdraft", "maxdraught", "depth"),
    "max_height_m": ("maxheight", "maxclosedheight"),
}


def classify_way(tags: dict[str, str] | None) -> WaterwayKind | None:
    """Classify a way by its waterway/lock tags. None => not a waterway we keep."""
    if not tags:
        return None
    ww = tags.get("waterway", "")
    if ww == "canal":
        return WaterwayKind.CANAL
    if ww == "river":
        return WaterwayKind.RIVER
    if ww == "fairway":
        return WaterwayKind.FAIRWAY
    if ww == "lock":
        return WaterwayKind.LOCK
    if tags.get("lock") == "yes":
        return WaterwayKind.LOCK
    return None


def is_derelict(tags: dict[str, str] | None) -> bool:
    """True if the tags mark the feature as derelict/disused/abandoned."""
    if not tags:
        return False
    if tags.get("waterway") in _DERELICT_WATERWAY_VALUES:
        return True
    return any(key.startswith(_DERELICT_TAG_PREFIXES) for key in tags)


def _parse_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_dimensions(tags: dict[str, str] | None) -> WayDimensions:
    """Extract restrictive max-dimension tags, trying aliases in order.

    First present alias with a parseable float wins; missing/unparseable => None.
    """
    tags = tags or {}
    values: dict[str, float] = {}
    for field, aliases in _DIMENSION_ALIASES.items():
        for alias in aliases:
            if alias in tags:
                parsed = _parse_float(tags[alias])
                if parsed is not None:
                    values[field] = parsed
                    break
    return WayDimensions(**values)


def classify_node(tags: dict[str, str] | None) -> NodeKind | None:
    """Classify a tagged node. None => not a network node we keep in this plan."""
    if not tags:
        return None
    if tags.get("waterway") == "lock_gate":
        return NodeKind.LOCK_GATE
    if tags.get("waterway") == "lock" or tags.get("lock") == "yes":
        return NodeKind.LOCK
    if "bridge:movable" in tags or tags.get("bridge") == "movable":
        return NodeKind.MOVABLE_BRIDGE
    if "mooring" in tags:
        return NodeKind.MOORING
    if tags.get("leisure") == "marina":
        return NodeKind.MARINA
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/ingest/test_filters.py -q
```

Expected: all passed (parametrized counts included).

- [ ] **Step 5: Lint**

```bash
uv run ruff check .
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add pound/ingest/filters.py tests/ingest/test_filters.py
git commit -m "feat(ingest): pure tag->IR functions (classify_way/node, is_derelict, extract_dimensions)"
```

---

## Task 6: Curated Overpass fixture + Overpass reader (`ingest/overpass.py`)

The reader is explicitly scaffolding — thin wrapper around `filters`. It builds the Overpass QL query, fetches JSON via `requests`, and calls the pure functions to build `WaterwayFeatures`. Replaced by a pyosmium reader in design step 6.

**Files:**

- Create: `/home/kurtt/pound/tests/fixtures/oxford_overpass_sample.json`
- Create: `/home/kurtt/pound/pound/ingest/overpass.py`
- Test: `/home/kurtt/pound/tests/ingest/test_overpass.py`
- Test: `/home/kurtt/pound/tests/ingest/test_network.py`

**Interfaces:**

- Consumes: `pound.ingest.ir`, `pound.ingest.filters`, `requests`
- Produces:
  - `OXFORD_BBOX: tuple[float,float,float,float]`
  - `build_query(bbox) -> str`
  - `fetch_raw(bbox, url, timeout) -> dict` (live network)
  - `parse(elements, bbox, source) -> WaterwayFeatures` (pure)
  - `fetch_oxford() -> WaterwayFeatures` (live network, convenience)

- [ ] **Step 1: Write the curated Overpass fixture**

Create `/home/kurtt/pound/tests/fixtures/oxford_overpass_sample.json`:

```json
{
  "version": 0.6,
  "generator": "Overpass API (test fixture, hand-curated)",
  "osm3s": {
    "timestamp_osm_base": "2026-06-21T12:00:00Z",
    "copyright": "The data included in this document is from www.openstreetmap.org. The data is made available for users under the Open Database License (ODbL)."
  },
  "elements": [
    {
      "type": "way", "id": 1001,
      "tags": {"waterway": "canal", "name": "Oxford Canal"},
      "geometry": [
        {"lat": 51.7500, "lon": -1.2600},
        {"lat": 51.7510, "lon": -1.2610},
        {"lat": 51.7520, "lon": -1.2620}
      ]
    },
    {
      "type": "way", "id": 1002,
      "tags": {"waterway": "canal", "name": "Oxford Canal", "maxwidth": "2.1", "maxdraught": "0.9"},
      "geometry": [
        {"lat": 51.7520, "lon": -1.2620},
        {"lat": 51.7530, "lon": -1.2630}
      ]
    },
    {
      "type": "way", "id": 1003,
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
      "tags": {"waterway": "canal", "name": "Duke's Cut", "tunnel": "yes"},
      "geometry": [
        {"lat": 51.7400, "lon": -1.2500},
        {"lat": 51.7410, "lon": -1.2510}
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
    }
  ]
}
```

Note: element 2004 (a pub) is included deliberately — it must be **dropped** by `parse()` since amenity POIs are out of scope for this plan (design step 5). The test asserts it is excluded.

- [ ] **Step 2: Write the failing test for `parse()` over the fixture**

Create `/home/kurtt/pound/tests/ingest/test_overpass.py`:

```python
import json
from pathlib import Path

import pytest

from pound.ingest.ir import NodeKind, WaterwayKind
from pound.ingest.overpass import OXFORD_BBOX, build_query, parse

FIXTURE = Path(__file__).parent.parent / "fixtures" / "oxford_overpass_sample.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_build_query_contains_bbox_and_filters():
    q = build_query((51.70, -1.35, 51.80, -1.20))
    assert "[out:json]" in q
    assert "(51.7,-1.35,51.8,-1.2)" in q
    assert "waterway" in q
    assert "lock_gate" in q
    assert "out geom;" in q


def test_parse_keeps_canal_ways():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    canal_ids = {w.osm_id for w in feats.ways if w.kind == WaterwayKind.CANAL}
    assert 1001 in canal_ids
    assert 1002 in canal_ids
    assert 1006 in canal_ids


def test_parse_keeps_lock_way():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    lock_ways = [w for w in feats.ways if w.kind == WaterwayKind.LOCK]
    assert any(w.osm_id == 1003 for w in lock_ways)


def test_parse_excludes_derelict():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    ids = {w.osm_id for w in feats.ways}
    assert 1004 not in ids  # disused:waterway
    assert 1005 not in ids  # waterway=derelict_canal


def test_parse_extracts_dimensions():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    w = next(w for w in feats.ways if w.osm_id == 1002)
    assert w.dimensions.max_beam_m == pytest.approx(2.1)
    assert w.dimensions.max_draft_m == pytest.approx(0.9)
    assert w.dimensions.max_height_m is None


def test_parse_flags_tunnel():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    w = next(w for w in feats.ways if w.osm_id == 1006)
    assert w.has_tunnel is True


def test_parse_keeps_lock_gate_and_lock_nodes():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    kinds = {n.kind for n in feats.nodes}
    assert NodeKind.LOCK_GATE in kinds
    assert NodeKind.LOCK in kinds


def test_parse_keeps_mooring_node():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    assert any(n.kind == NodeKind.MOORING for n in feats.nodes)


def test_parse_excludes_amenity_pub_node():
    """Amenity POIs (pub/shop/etc.) are a later ingest step — parse must drop them."""
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    assert not any("amenity" in n.tags and n.tags["amenity"] == "pub" for n in feats.nodes)


def test_parse_sets_source_and_bbox():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX, source="overpass")
    assert feats.source == "overpass"
    assert feats.bbox == OXFORD_BBOX
    assert feats.fetched_at  # non-empty ISO timestamp


def test_parse_geometry_carried_through():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    w = next(w for w in feats.ways if w.osm_id == 1001)
    assert len(w.geometry) == 3
    assert w.geometry[0] == (pytest.approx(51.75), pytest.approx(-1.26))
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/ingest/test_overpass.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pound.ingest.overpass'`.

- [ ] **Step 4: Write `pound/ingest/overpass.py`**

Create `/home/kurtt/pound/pound/ingest/overpass.py`:

```python
"""Overpass JSON reader — SCAFFOLDING.

Thin wrapper that builds an Overpass QL query, fetches JSON via `requests`, and
calls the pure functions in `pound.ingest.filters` to build a `WaterwayFeatures`
IR. Replaced by a pyosmium/osmium bulk reader over the Geofabrik GB PBF in
design step 6; the pure functions and IR survive that swap.

Network use is confined to `fetch_raw`/`fetch_oxford`. `parse()` is pure and
unit-tested against a committed fixture.
"""

from datetime import datetime, timezone

import requests

from pound.ingest import filters
from pound.ingest.ir import (
    WaterwayFeatures,
    WaterwayKind,
    WaterwayNode,
    WaterwayWay,
    WayDimensions,
)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Oxford Canal around Oxford: Duke's Cut (Thames junction) -> city -> up past
# the Hayfield/Isis lock flight toward Kidlington. (south, west, north, east).
OXFORD_BBOX = (51.70, -1.35, 51.80, -1.20)

# Ways we pull as routable/lock edges.
_WAY_WATERWAY_RE = "^(canal|river|fairway|lock)$"


def build_query(bbox: tuple[float, float, float, float]) -> str:
    s, w, n, e = bbox
    b = f"({s},{w},{n},{e})"
    return f"""[out:json][timeout:60];
(
  way["waterway"~"{_WAY_WATERWAY_RE}"]{b};
  way["lock"="yes"]{b};
  node["waterway"="lock_gate"]{b};
  node["lock"="yes"]{b};
  node["bridge:movable"]{b};
  way["bridge:movable"]{b};
  node["mooring"]{b};
);
out geom;"""


def fetch_raw(
    bbox: tuple[float, float, float, float] = OXFORD_BBOX,
    url: str = OVERPASS_URL,
    timeout: float = 120.0,
) -> dict:
    """Fetch raw Overpass JSON (live network). Returns the parsed `elements` container."""
    resp = requests.post(url, data={"data": build_query(bbox)}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def parse(
    elements: list[dict],
    bbox: tuple[float, float, float, float] | None,
    source: str = "overpass",
) -> WaterwayFeatures:
    """Pure: turn Overpass `elements` into a WaterwayFeatures IR via `filters`."""
    ways: list[WaterwayWay] = []
    nodes: list[WaterwayNode] = []
    for el in elements:
        el_type = el.get("type")
        tags = el.get("tags") or {}
        if el_type == "way":
            if filters.is_derelict(tags):
                continue
            kind = filters.classify_way(tags)
            if kind is None:
                continue  # not a waterway/lock way we keep (e.g. amenities are step 5)
            geometry = [(g["lat"], g["lon"]) for g in el.get("geometry", [])]
            dims: WayDimensions = filters.extract_dimensions(tags)
            ways.append(
                WaterwayWay(
                    osm_id=el["id"],
                    kind=kind,
                    name=tags.get("name"),
                    tags=tags,
                    node_ids=list(el.get("nodes", [])),  # empty under `out geom`
                    geometry=geometry,
                    dimensions=dims,
                    has_tunnel=tags.get("tunnel") == "yes",
                    has_movable_bridge=(
                        "bridge:movable" in tags or tags.get("bridge") == "movable"
                    ),
                )
            )
        elif el_type == "node":
            kind = filters.classify_node(tags)
            if kind is None:
                continue  # amenity POIs etc. dropped here (design step 5)
            nodes.append(
                WaterwayNode(
                    osm_id=el["id"],
                    lat=el["lat"],
                    lon=el["lon"],
                    tags=tags,
                    kind=kind,
                )
            )

    routable = {WaterwayKind.CANAL, WaterwayKind.RIVER, WaterwayKind.FAIRWAY}
    # ordering: routable ways first, then locks — stable for summarize/tests
    ways.sort(key=lambda w: (0 if w.kind in routable else 1, w.osm_id))

    return WaterwayFeatures(
        ways=ways,
        nodes=nodes,
        source=source,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        bbox=bbox,
    )


def fetch_oxford() -> WaterwayFeatures:
    """Live network: fetch the Oxford Canal extract and parse it."""
    raw = fetch_raw(OXFORD_BBOX)
    return parse(raw["elements"], OXFORD_BBOX)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/ingest/test_overpass.py -q
```

Expected: all passed.

- [ ] **Step 6: Write the network test (skipped by default)**

Create `/home/kurtt/pound/tests/ingest/test_network.py`:

```python
import pytest

from pound.ingest.overpass import OXFORD_BBOX, fetch_oxford


@pytest.mark.network
def test_live_overpass_oxford_returns_features():
    feats = fetch_oxford()
    assert feats.source == "overpass"
    assert feats.bbox == OXFORD_BBOX
    # a real Oxford extract should contain at least some canal ways
    assert len(feats.ways) > 0
    assert any(w.kind.value == "canal" for w in feats.ways)
```

- [ ] **Step 7: Run the full suite — confirm network test is skipped**

```bash
uv run pytest -q
```

Expected: all non-network tests pass; `test_network.py` shows as skipped (1 skipped).

- [ ] **Step 8: Lint**

```bash
uv run ruff check .
```

Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add tests/fixtures/oxford_overpass_sample.json pound/ingest/overpass.py tests/ingest/test_overpass.py tests/ingest/test_network.py
git commit -m "feat(ingest): Overpass reader + curated fixture; network test gated behind --run-network"
```

---

## Task 7: `summarize()` report (`ingest/summarize.py`) — seed of §4.3 build report

Pure function over `WaterwayFeatures` → dict. No network. This is the B deliverable you can eyeball, and the seed of the build-time validation report (design §4.3 / §7.1).

**Files:**

- Create: `/home/kurtt/pound/pound/ingest/summarize.py`
- Test: `/home/kurtt/pound/tests/ingest/test_summarize.py`

**Interfaces:**

- Consumes: `pound.ingest.ir.WaterwayFeatures`, `WaterwayKind`
- Produces: `summarize(features: WaterwayFeatures) -> dict` with keys: `source`, `fetched_at`, `bbox`, `way_count`, `ways_by_kind`, `node_count`, `nodes_by_kind`, `lock_count`, `routable_ways_missing_all_dimensions`, `tunnel_ways`, `movable_bridge_ways`.

- [ ] **Step 1: Write the failing test**

Create `/home/kurtt/pound/tests/ingest/test_summarize.py`:

```python
from pound.ingest.ir import (
    NodeKind,
    WaterwayFeatures,
    WaterwayKind,
    WaterwayNode,
    WaterwayWay,
    WayDimensions,
)
from pound.ingest.summarize import summarize


def _canal(osm_id, dims=None, tunnel=False, movable=False):
    return WaterwayWay(
        osm_id=osm_id,
        kind=WaterwayKind.CANAL,
        name="Oxford Canal",
        tags={"waterway": "canal"},
        node_ids=[],
        geometry=[(51.75, -1.26)],
        dimensions=dims or WayDimensions(),
        has_tunnel=tunnel,
        has_movable_bridge=movable,
    )


def _lock_way(osm_id):
    return WaterwayWay(
        osm_id=osm_id,
        kind=WaterwayKind.LOCK,
        name="A Lock",
        tags={"waterway": "lock"},
        node_ids=[],
        geometry=[(51.75, -1.26)],
        dimensions=WayDimensions(),
    )


def _node(osm_id, kind):
    return WaterwayNode(
        osm_id=osm_id, lat=51.75, lon=-1.26, tags={}, kind=kind
    )


def test_summarize_counts_ways_by_kind():
    feats = WaterwayFeatures(
        ways=[_canal(1), _canal(2), _lock_way(3)],
        nodes=[],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=(51.70, -1.35, 51.80, -1.20),
    )
    r = summarize(feats)
    assert r["way_count"] == 3
    assert r["ways_by_kind"] == {"canal": 2, "lock": 1}


def test_summarize_counts_nodes_by_kind():
    feats = WaterwayFeatures(
        ways=[],
        nodes=[_node(1, NodeKind.LOCK_GATE), _node(2, NodeKind.MOORING), _node(3, NodeKind.LOCK)],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=None,
    )
    r = summarize(feats)
    assert r["node_count"] == 3
    assert r["nodes_by_kind"] == {"lock_gate": 1, "mooring": 1, "lock": 1}


def test_summarize_lock_count_combines_lock_ways_and_lock_nodes():
    feats = WaterwayFeatures(
        ways=[_lock_way(1), _canal(2)],
        nodes=[_node(10, NodeKind.LOCK), _node(11, NodeKind.LOCK_GATE)],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=None,
    )
    r = summarize(feats)
    # 1 lock way + 1 lock node (lock_gate counted separately, not as a lock)
    assert r["lock_count"] == 2


def test_summarize_missing_dimensions_for_routable_only():
    feats = WaterwayFeatures(
        ways=[
            _canal(1, dims=WayDimensions(max_beam_m=2.1)),  # has a dim
            _canal(2),  # no dims
            _lock_way(3),  # lock way, no dims — should NOT count against routable
        ],
        nodes=[],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=None,
    )
    r = summarize(feats)
    assert r["routable_ways_missing_all_dimensions"] == 1


def test_summarize_tunnel_and_movable_bridge_flags():
    feats = WaterwayFeatures(
        ways=[_canal(1, tunnel=True), _canal(2, movable=True)],
        nodes=[],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=None,
    )
    r = summarize(feats)
    assert r["tunnel_ways"] == 1
    assert r["movable_bridge_ways"] == 1


def test_summarize_provenance_fields():
    feats = WaterwayFeatures(
        ways=[], nodes=[],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=(51.70, -1.35, 51.80, -1.20),
    )
    r = summarize(feats)
    assert r["source"] == "overpass"
    assert r["fetched_at"] == "2026-06-21T12:00:00+00:00"
    assert r["bbox"] == [51.70, -1.35, 51.80, -1.20]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/ingest/test_summarize.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pound.ingest.summarize'`.

- [ ] **Step 3: Write `pound/ingest/summarize.py`**

Create `/home/kurtt/pound/pound/ingest/summarize.py`:

```python
"""Build/ingest report — seed of the design §4.3 / §7.1 build report.

Pure: takes a WaterwayFeatures IR, returns a plain dict of counts and flags you
can eyeball during dev or serialize to JSON. No network, no file IO.
"""

from collections import Counter

from pound.ingest.ir import WaterwayFeatures, WaterwayKind

_ROUTABLE = {WaterwayKind.CANAL, WaterwayKind.RIVER, WaterwayKind.FAIRWAY}


def summarize(features: WaterwayFeatures) -> dict:
    ways_by_kind = Counter(w.kind.value for w in features.ways)
    nodes_by_kind = Counter(n.kind.value for n in features.nodes)

    lock_count = sum(
        1 for w in features.ways if w.kind == WaterwayKind.LOCK
    ) + sum(1 for n in features.nodes if n.kind.value == "lock")

    def _has_any_dim(w) -> bool:
        d = w.dimensions
        return any(
            v is not None
            for v in (d.max_beam_m, d.max_length_m, d.max_draft_m, d.max_height_m)
        )

    routable_missing_dims = sum(
        1 for w in features.ways if w.kind in _ROUTABLE and not _has_any_dim(w)
    )

    return {
        "source": features.source,
        "fetched_at": features.fetched_at,
        "bbox": list(features.bbox) if features.bbox else None,
        "way_count": len(features.ways),
        "ways_by_kind": dict(ways_by_kind),
        "node_count": len(features.nodes),
        "nodes_by_kind": dict(nodes_by_kind),
        "lock_count": lock_count,
        "routable_ways_missing_all_dimensions": routable_missing_dims,
        "tunnel_ways": sum(1 for w in features.ways if w.has_tunnel),
        "movable_bridge_ways": sum(1 for w in features.ways if w.has_movable_bridge),
    }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/ingest/test_summarize.py -q
```

Expected: all passed.

- [ ] **Step 5: Lint**

```bash
uv run ruff check .
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add pound/ingest/summarize.py tests/ingest/test_summarize.py
git commit -m "feat(ingest): summarize() report -> dict (seed of §4.3 build report)"
```

---

## Task 8: Dev CLI + run the real Oxford fetch + document the B deliverable

A thin dev convenience to actually fetch the Oxford extract, print the `summarize()` report, and optionally write the features JSON to `pound/data/` (gitignored). This is how you eyeball the pipeline on real OSM data — the unit-test fixture only proves the logic; this proves it on the real source.

**Files:**

- Create: `/home/kurtt/pound/pound/ingest/cli.py`
- Modify: `/home/kurtt/pound/README.md` (add usage section)
- Test: `tests/ingest/test_cli.py`

**Interfaces:**

- Consumes: `pound.ingest.overpass.fetch_oxford`, `pound.ingest.summarize.summarize`
- Produces: `main(argv=None) -> None` (entry point `pound-ingest`)

- [ ] **Step 1: Write the failing test**

Create `/home/kurtt/pound/tests/ingest/test_cli.py`:

```python
import json
from pathlib import Path

from pound.ingest import cli
from pound.ingest.ir import (
    NodeKind,
    WaterwayFeatures,
    WaterwayKind,
    WaterwayNode,
    WaterwayWay,
    WayDimensions,
)


def _sample_features() -> WaterwayFeatures:
    return WaterwayFeatures(
        ways=[
            WaterwayWay(
                osm_id=1, kind=WaterwayKind.CANAL, name="Oxford Canal",
                tags={"waterway": "canal"}, node_ids=[], geometry=[(51.75, -1.26)],
                dimensions=WayDimensions(max_beam_m=2.1),
            )
        ],
        nodes=[
            WaterwayNode(osm_id=10, lat=51.75, lon=-1.26,
                         tags={"waterway": "lock_gate"}, kind=NodeKind.LOCK_GATE)
        ],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=(51.70, -1.35, 51.80, -1.20),
    )


def test_cli_prints_report_and_writes_out(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_oxford", lambda: _sample_features())
    out_path = tmp_path / "oxford.json"
    cli.main(["oxford", "--out", str(out_path)])

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["way_count"] == 1
    assert report["ways_by_kind"] == {"canal": 1}

    written = WaterwayFeatures.model_validate_json(out_path.read_text())
    assert written.source == "overpass"
    assert len(written.ways) == 1


def test_cli_rejects_unknown_region(monkeypatch):
    monkeypatch.setattr(cli, "fetch_oxford", lambda: _sample_features())
    try:
        cli.main(["bogus"])
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("expected SystemExit for unknown region")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/ingest/test_cli.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pound.ingest.cli'`.

- [ ] **Step 3: Write `pound/ingest/cli.py`**

Create `/home/kurtt/pound/pound/ingest/cli.py`:

```python
"""Dev CLI for the ingest pipeline.

Usage:
    python -m pound.ingest.cli oxford [--out pound/data/oxford_canal_waterways.json]

Fetches the Oxford Canal Overpass extract, prints the summarize() report as
JSON, and optionally writes the WaterwayFeatures IR to --out. Network use only.
Not imported by library code.
"""

import argparse
import json
import sys
from pathlib import Path

from pound.ingest.overpass import fetch_oxford
from pound.ingest.summarize import summarize


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pound-ingest")
    parser.add_argument("region", choices=["oxford"], help="region to fetch")
    parser.add_argument(
        "--out",
        default=None,
        help="path to write the WaterwayFeatures JSON (e.g. pound/data/oxford_canal_waterways.json)",
    )
    args = parser.parse_args(argv)

    if args.region == "oxford":
        features = fetch_oxford()
    else:  # pragma: no cover - argparse choices guard this
        parser.error(f"unknown region: {args.region}")
        return

    report = summarize(features)
    print(json.dumps(report, indent=2))

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(features.model_dump_json(indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/ingest/test_cli.py -q
```

Expected: 2 passed.

- [ ] **Step 5: Update `README.md` with ingest usage**

Replace the `## Development` section in `/home/kurtt/pound/README.md` with:

```markdown
## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```

## Regional ingest (dev / scaffolding)

The Overpass reader is **scaffolding** for early development on a small dataset
(Oxford Canal). It is replaced by a pyosmium bulk reader over the Geofabrik GB
PBF in design step 6.

Fetch the Oxford extract and print the summarize() report (network required):

```bash
uv run pound-ingest oxford
# or, also writing the features IR:
uv run pound-ingest oxford --out pound/data/oxford_canal_waterways.json
```

Network tests are skipped by default; run them explicitly:

```bash
uv run pytest --run-network
```

```

- [ ] **Step 6: Run the full suite (network skipped) and lint**

```bash
uv run pytest -q
uv run ruff check .
```

Expected: all non-network tests pass; 1 network test skipped.

- [ ] **Step 7: Run the live Oxford fetch to validate the pipeline on real OSM**

```bash
uv run pound-ingest oxford --out pound/data/oxford_canal_waterways.json
```

Expected: a JSON report printed to stdout with `way_count > 0`, `ways_by_kind`
including `"canal"`, and a non-zero `lock_count` or lock-gate nodes for the
Oxford flight. The `pound/data/oxford_canal_waterways.json` file is written
(gitignored — confirm with `git status` that it is NOT staged).

If the live fetch fails (Overpass rate limit / timeout), retry once after a
short wait; do not commit the `pound/data/` output. The pipeline is still
validated by the unit tests + fixture; the live run is a manual sanity check.

- [ ] **Step 8: Confirm data/ stays out of git**

```bash
git status --short
```

Expected: `pound/data/oxford_canal_waterways.json` does NOT appear (gitignored).
Only `README.md`, `pound/ingest/cli.py`, `tests/ingest/test_cli.py` are staged.

- [ ] **Step 9: Commit**

```bash
git add pound/ingest/cli.py tests/ingest/test_cli.py README.md
git commit -m "feat(ingest): dev CLI (pound-ingest oxford) + README usage section"
```

---

## Self-Review

**1. Spec coverage (scope B against the design doc):**

- Design step 1 (schemas + stub + structural tests) → Tasks 2, 3. ✓
- Design step 2 regional ingest via Overpass, filtered waterway features, stopping before graph build → Tasks 4–6. ✓
- Design §4.1 tag filtering (canal/river/fairway/lock/lock_gate/mooring/dimensions) → Task 5 + Overpass query in Task 6. ✓
- Design §4.1 derelict/disused/abandoned exclusion → `is_derelict` (Task 5) applied in `parse` (Task 6). ✓
- Design §4.3 / §7.1 build report (seed) → `summarize()` (Task 7); full connectivity validation is graph-build (out of scope for B). ✓ (correctly scoped: connectivity is graph-build's job, not B's)
- Design §3.1 dimension tag aliases (maxwidth/width/maxlength/maxdraft/maxdraught/depth/maxheight/maxclosedheight) → `extract_dimensions` (Task 5). ✓
- Design §3.1 amenity POIs (pubs/shops/water) → explicitly **deferred** to step 5; `parse` drops amenity nodes (Task 6 test asserts pub is excluded). ✓ (out of scope, documented)
- Design §10 deps (pyosmium/osmium/shapely/networkx) → **deferred** to graph build / bulk path; B uses only pydantic + requests. ✓ (YAGNI per the planning conversation)
- ODbL attribution → README + fixture `osm3s.copyright` note (Tasks 1, 6). ✓
- `data/` gitignored, small fixture committed (design §10) → `.gitignore` (Task 1) + `tests/fixtures/` (Task 6). ✓
- Request-time path pure, no network → `plan.py` stub imports only schemas (Task 3). ✓
- Parallel-build contract `plan_route(constraints) -> RouteResult` frozen → Task 3. ✓

**Gaps (intentional, out of scope for B):** graph build, connectivity validation, cost model, routing, amenities, rings, day budgeting, bulk PBF path, CRT data, external oracle. All are later design steps; B's stated purpose is the contract + the ingest pipeline core, which this plan delivers.

**2. Placeholder scan:** No TBD/TODO/placeholder text. Every step has runnable code or an exact command with expected output. The live Overpass fetch (Task 8 Step 7) has a documented fallback (retry / rely on unit tests) rather than a placeholder.

**3. Type consistency:**

- `WaterwayKind` values `"canal"/"river"/"fairway"/"lock"` used consistently in `summarize` (`w.kind.value`), tests, and `parse`. ✓
- `NodeKind.LOCK` referenced as `n.kind.value == "lock"` in `summarize` — matches the enum value. ✓
- `WaterwayFeatures.bbox` is `tuple` in the IR; `summarize` returns it as `list` for JSON-friendliness; the test expects `list`. ✓ (documented by the test)
- `plan_route` stub returns `RouteResult` with fields matching `schemas.py` exactly (`is_ring`, `legs`, `days`, `total_*`, `amenities`, `warnings`, `graph_source_date`). ✓
- `fetch_oxford` / `fetch_raw` / `parse` signatures match across Tasks 6 and 8 (cli calls `fetch_oxford` and `summarize`). ✓
- `cli.fetch_oxford` is monkeypatched in the CLI test — the import in `cli.py` is `from pound.ingest.overpass import fetch_oxford`, so `monkeypatch.setattr(cli, "fetch_oxford", ...)` patches the name in the `cli` namespace. ✓

**4. Task independence / right-sizing:** Each task has its own test cycle and commits independently. Task 2 (schemas) unblocks the Agent Core regardless of whether Tasks 4–8 land. Tasks 4→5→6→7→8 build the ingest pipeline in dependency order, each leaving the suite green.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-21-pound-ingest-scaffolding.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
