# Pound — Canal-Boating Routing Engine

**Status:** Design / implementation brief
**Audience:** Claude Code (implementation agent)
**Builds in parallel with:** `labyrinth-core` + `labyrinth-agent` (the Agent Core)
**Name:** *Pound* — a "pound" is the stretch of level water between two locks,
which is exactly the primitive this engine reasons about (an edge between lock
nodes). The conversational tool wrapping it can carry its own name later.

---

## 1. Scope and boundary

Pound is the **deterministic routing engine** for UK inland waterways. It is a
plain Python library with **no MCP, no LLM, no network at request time**. It
answers: given a start, (optional) end, day budget, and boat dimensions —
produce a route with distances, lock counts, time estimates, and nearby
amenities.

The MCP server (`labyrinth-core`) and the Pydantic AI agent (`labyrinth-agent`)
wrap Pound; they are out of scope here. The integration seam is just:

```python
def plan_route(constraints: CanalConstraints) -> RouteResult: ...
```

This single signature is the contract the Agent Core depends on. **Freeze it
early** so both efforts can proceed in parallel against a stub.

> **No runtime route checker.** An earlier draft specced a `check_route()` that
> recomputed the route's totals from the same legs, lock counts, and cost
> constants the planner used. That is the same arithmetic twice over the same
> data — it shares logic and inputs with the planner, so it only catches
> bookkeeping slips (bad sums, a dropped leg) and confirms any upstream error
> faithfully. That belongs in unit tests, not a runtime component or an MCP
> verb. Real verification lives where there's an actual asymmetry: **build-time
> validation** of the graph (§4.3, §7) and an **optional, permission-gated
> external oracle** (§8). See those sections.

### Parallel-build contract (do this first)

Before either side writes real logic, land:

1. `pound/schemas.py` — `CanalConstraints`, `RouteResult`, `RouteLeg`,
   `Amenity` (Pydantic models; see §6). These are imported by BOTH Pound and
   the Agent Core.
2. A **stub** `plan_route()` that returns a hardcoded plausible `RouteResult`
   for one known route (e.g. a short Cheshire Ring leg). The Agent Core builds
   against this stub until the real engine lands.
3. Structural-invariant **unit tests** (legs connect end-to-end, totals == sum
   of legs). These are tests, not a runtime component — they replace the old
   `check_route()`.

Everything else in this doc is the real engine behind that stub.

---

## 2. Architecture overview

```
                ┌────────────────────────────────────────────┐
  OFFLINE BUILD │  data ingest → graph build → artifact (.pkl/ │
  (one-off /    │  sqlite)  — slow, runs occasionally          │
   scheduled)   └───────────────────┬────────────────────────┘
                                    │  loads prebuilt graph
                ┌───────────────────┴────────────────────────┐
  REQUEST TIME  │  plan_route(constraints) -> RouteResult      │
  (fast, pure)  │   - snap start/end to graph                  │
                │   - filter edges by boat dimensions          │
                │   - shortest path on time-cost               │
                │   - collect amenities near route             │
                └─────────────────────────────────────────────┘
```

Two distinct phases. The **offline build** turns OSM + CRT data into a routable
graph artifact. The **request-time** path loads that artifact and runs queries.
Keep them in separate modules; never ingest OSM at request time.

```
pound/
├── pound/
│   ├── schemas.py          # shared Pydantic models (frozen early)
│   ├── ingest/
│   │   ├── osm.py          # Geofabrik extract -> filtered waterway features
│   │   ├── crt.py          # CRT open-data GeoJSON -> assets/amenities
│   │   └── overpass.py     # optional targeted pulls for dev/regions
│   ├── graph/
│   │   ├── build.py        # features -> noded, connected graph
│   │   ├── locks.py        # attach lock counts/dims to edges
│   │   └── artifact.py     # serialize/load prebuilt graph
│   ├── route/
│   │   ├── cost.py         # the lock-aware time cost model
│   │   ├── snap.py         # geocode/snap a place to nearest graph node
│   │   └── plan.py         # plan_route() — the request-time entry point
│   ├── amenities/
│   │   └── nearby.py       # amenities within buffer of the route
│   ├── validate/
│   │   ├── connectivity.py # BUILD-TIME graph validation (§7)
│   │   └── oracle.py       # OPTIONAL external oracle, permission-gated (§8)
│   └── data/               # small fixtures (NOT the full GB extract)
├── tests/
│   ├── fixtures/           # structural-invariant fixtures
│   └── ...
└── pyproject.toml
```

---

## 3. Data sources

### 3.1 OSM — the network geometry (primary)

- **Bulk:** Geofabrik **Great Britain** `.osm.pbf` extract. Filter to waterway
  features with `osmium tags-filter` before doing anything else (the full
  extract is huge; you want ~waterways only).
- **Dev/regional:** Overpass API for a single waterway or bbox (e.g. just the
  Cheshire Ring) so you can iterate without the full GB build.

**Tags that matter (confirmed from OSM wiki):**

| feature | tagging | use in Pound |
|---|---|---|
| canal centreline | `waterway=canal` | routable edge |
| navigable river | `waterway=river` (+ navigation tags) | routable edge |
| fairway | `waterway=fairway` | routable edge |
| **derelict/disused** | `waterway=derelict_canal`, `disused:*`, `abandoned:*` | EXCLUDE by default |
| lock chamber | `waterway=lock` (short way) and/or `lock=yes` | lock edge → time penalty |
| lock gate | node `waterway=lock_gate` | lock counting |
| movable bridge | `bridge:movable=*` / `bridge=movable` / swing/lift | optional time penalty |
| tunnel | `tunnel=yes` on waterway | optional penalty / one-way timing |
| max beam | `maxwidth=*` / `width=*` on way | dimension filter |
| max length | `maxlength=*` | dimension filter |
| draft | `maxdraft=*` / `maxdraught=*` / `depth=*` | dimension filter |
| headroom | `maxheight=*` / `maxclosedheight=*` | dimension filter (boat air-draft) |
| mooring | `mooring=*`, `leisure=marina` | amenity / hire base |

**Connectivity caveat (critical):** OSM routing relies on way-ends sharing
nodes. Per the wiki, "to allow routing, ensure the ends of each way connect
correctly with other waterway features." In practice UK canals are well-noded
but not perfectly. The build MUST run a connectivity pass (§4.3) and report
disconnected components before any route is trusted.

**Prior art to lean on:** BRouter's `WaterwayModel` profile already encodes a
boat cost model with `boat_width`, `boat_draft`, `boat_height`, `speed_normal`,
and a `costfactor` that only traverses `waterway=canal/river/fairway` (everything
else gets cost 100000 = effectively blocked). Use it as a reference for the
edge-eligibility logic and dimension parameters; we reimplement in Python rather
than depend on it.

### 3.2 CRT open data — asset detail + amenities (secondary/enrichment)

ArcGIS Hub (`data-canalrivertrust.opendata.arcgis.com`), downloadable as
GeoJSON. Useful layers: Locks, Winding Holes / Turning Points, Aqueducts,
Culverts, Dry Docks, Wharves, Reservoirs, plus water points / sanitary stations
where published. Use these to (a) enrich lock metadata, (b) provide amenities,
(c) cross-check OSM lock positions.

> Note: CRT data is points + a route layer, NOT a pre-built routable graph. It
> does NOT comprehensively cover hire bases/marinas — get those from OSM
> `leisure=marina` + (later) hire-company sources.

### 3.3 Amenities (OSM POIs)

Pubs (`amenity=pub`), shops (`shop=*`), drinking water (`amenity=drinking_water`
/ canal water points), stations (`railway=station`), snapped to within a buffer
of the towpath/route.

---

## 4. Offline build pipeline

### 4.1 Ingest (`ingest/osm.py`)

1. `osmium tags-filter GB.osm.pbf w/waterway=canal,river,fairway \
   n/waterway=lock_gate nwr/lock=yes ... -o waterways.osm.pbf`
   (filter ways + the lock/mooring nodes you need; drop everything else).
2. Parse with `pyosmium` (or `osmnx`-style logic adapted for waterways —
   osmnx is road-oriented, so likely a custom `pyosmium` handler).
3. Emit an intermediate representation: ways (with tags + node refs) and tagged
   nodes (locks, gates, moorings).

### 4.2 Graph build (`graph/build.py`)

- Node = waterway junction or endpoint; also force a node at every lock and at
  snap targets (places).
- Edge = a **pound**: a stretch of waterway between nodes, carrying
  `length_m`, geometry, and the restrictive `max_beam/length/draft/height`
  (min along the segment), plus a `locks` count for any lock(s) on it.
- Exclude `derelict_canal` / `disused:*` / `abandoned:*` by default
  (configurable — restoration routes are a future flag).
- Tooling: **NetworkX** for a pure-Python first cut; **pgRouting/PostGIS** if you
  want SQL-side topology (`pgr_createTopology`) and easy joins to CRT assets in
  the same DB. Start with NetworkX; the artifact interface (§4.4) hides the
  choice so you can swap later.

### 4.3 Connectivity validation (`graph/build.py`)

- Compute connected components. Report count + size of the largest.
- The connected English network + Scottish canals should form a small number of
  large components; a long tail of tiny components usually means tagging gaps or
  un-noded way-ends.
- Emit a **build report** (JSON): component sizes, count of edges missing
  dimension tags, count of locks attached, suspicious zero-length edges.
- Tests assert the main network is one component and known routes are connected.

### 4.4 Artifact (`graph/artifact.py`)

- Serialize the built graph + spatial index to a single loadable artifact
  (pickle for NetworkX, or the PostGIS DB). Version it; include the source
  extract date in metadata.
- Request-time loads this once (module-level / cached), never re-ingests.

---

## 5. Request-time routing

### 5.1 Snap (`route/snap.py`)

- Resolve a place string → coordinate (geocode; can be offline gazetteer from
  OSM names + CRT place names to keep request-time network-free).
- Snap coordinate → nearest graph node within tolerance. Return a clear error if
  the place is off-network or in a different component than the other endpoint.

### 5.2 Cost model (`route/cost.py`) — the heart of it

Edge traversal time:

```
time_min(edge) = (length_m / 1000) / cruise_kmh * 60
               + edge.locks * lock_minutes
               + movable_bridges * bridge_minutes   # optional
```

Defaults (tunable, expose as constants):

- `cruise_kmh ≈ 4.8` (~3 mph — the standard canal cruising assumption)
- `lock_minutes ≈ 12` (typical 10–15; single lock, single boat)
- `bridge_minutes ≈ 5` for movable bridges (optional, off by default)

This matches the boater "lock-miles" heuristic. Keep all constants in one place
and document them; the checker (§7) recomputes from the same constants.

**Eligibility filter (before pathfinding):** drop edges where the boat exceeds
`max_beam / max_length / max_draft / max_height` (when the constraint provides
dimensions and the edge has the tag). Missing tag = assume passable but flag in
the result so the agent can caveat. (Mirrors BRouter's approach of blocking
ineligible edges.)

### 5.3 Plan (`route/plan.py`) — `plan_route()`

Modes driven by `CanalConstraints`:

- **Point-to-point:** `start` + `end` → shortest path by time cost.
- **Round trip / ring:** `end is None` → find a closed loop returning to start
  within the day budget (rings are the classic canal holiday; the Cheshire Ring,
  Four Counties Ring, etc.). v1 can support an explicit `via` or a named ring;
  general loop-finding within a time budget can be a later enhancement.
- **Day budgeting:** split the path into days of ≤ `hours_per_day` cruising,
  preferring to end days near moorings/amenities (winding holes for turning).

Use Dijkstra/A*(NetworkX `shortest_path` with `weight=time_min`, or A* with a
straight-line/time heuristic).

Output a `RouteResult` (§6): ordered legs, per-leg distance/locks/time, totals,
day breakdown, and amenities.

### 5.4 Amenities (`amenities/nearby.py`)

- For the chosen route geometry, find POIs within a buffer (e.g. 250 m of the
  towpath). Filter by `constraints.amenity_prefs`. Attach to the nearest leg /
  day. Cap count; rank by proximity.

---

## 6. Schemas (`pound/schemas.py`) — shared, freeze early

```python
from pydantic import BaseModel

class CanalConstraints(BaseModel):
    start: str
    end: str | None = None              # None => ring / round trip
    days: int
    hours_per_day: float = 6.0
    boat_length_m: float | None = None
    boat_beam_m: float | None = None
    boat_draft_m: float | None = None
    boat_height_m: float | None = None
    amenity_prefs: list[str] = []       # ["pub", "water_point", "shop", ...]
    allow_derelict: bool = False

class Amenity(BaseModel):
    kind: str                           # "pub" | "water_point" | "marina" | ...
    name: str | None
    lat: float
    lon: float
    distance_m: float                   # from route
    source: str                         # "osm" | "crt"

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
    end_near: str | None                # mooring/town the day ends at
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
    warnings: list[str] = []            # e.g. "draft unknown on 3 segments"
    graph_source_date: str              # provenance from the artifact
```

> No `CheckResult` — there is no runtime checker (see §1, §7). Structural
> invariants are asserted in unit tests; graph validation has its own report
> type in §7.

---

## 7. Validation — where verification actually pays off

There is **no runtime route checker**. Recomputing a route's totals from the
same legs and the same cost constants the planner used is the same arithmetic
twice over the same data: it shares both logic and inputs with the planner, so
it cannot catch the errors that matter (a wrong lock count on an edge is read
identically by both) and only flags bookkeeping slips. Those are covered by
ordinary unit tests, not a component.

Real verification needs an **asymmetry** — a check that is cheaper than, and
independent of, the thing it checks. For Pound that asymmetry exists at **build
time**, not request time, because the highest-risk failures are in the graph
build (un-noded way-ends, a lock node that didn't attach to its edge, a
`derelict_canal` segment that slipped the filter, a missing dimension tag
silently treated as passable). A correctly-computed route over a wrong graph is
still wrong, and no amount of total-recomputation reveals it.

### 7.1 Build-time graph validation (`validate/connectivity.py`) — REQUIRED

Runs as the last step of the offline build (this is §4.3, stated as the primary
validation). Produces a build report (JSON) and fails the build on hard errors:

- **Connectivity:** connected-component count and largest-component size. The
  main connected English network (+ Scottish canals) should be a small number of
  large components; a long tail of tiny components signals tagging gaps or
  un-noded ends. Assert known routes (e.g. the Cheshire Ring) are within one
  component.
- **Lock attachment:** every lock node/way resolved onto an edge; report any
  orphans.
- **Filter sanity:** zero `derelict_canal`/`disused:*`/`abandoned:*` edges in the
  routable graph (unless `allow_derelict`).
- **Tag coverage:** count edges missing dimension tags (informational; surfaced
  later as route `warnings`).
- **Degenerate geometry:** zero-length or self-looping edges.

### 7.2 Structural-invariant unit tests — REQUIRED

Plain `pytest` over `plan_route` outputs (no separate component, no MCP verb):

- legs connect end-to-end (`leg.to_place == next.from_place`);
- `total_km` / `total_locks` / `total_minutes` == sum over legs (float eps);
- per-leg `est_minutes` matches the cost formula for `(distance, locks)`;
- day cruising minutes ≤ `hours_per_day` (small overflow → warning);
- every amenity `distance_m` within the buffer.

### 7.3 Relation to the Agent Core `validate` verb

Because Pound has no genuine runtime checker, **it does not implement the
optional `validate` MCP verb**. That verb is for tools with a real
proposer/checker asymmetry (e.g. the megaminx solver: apply moves, assert
solved). Confirm the Agent Core treats `validate` as optional, not required.

---

## 8. Optional external oracle (`validate/oracle.py`) — PERMISSION-GATED, off by default

A genuinely independent check would compare Pound's distance + lock counts
against a **separate dataset and codebase**. **CanalPlanAC** is the obvious
candidate — it publishes distance + lock counts between adjacent places (e.g.
"X — 22.74 km and 5 locks away"), derived from its own database, so agreement is
real corroboration in a way self-recomputation never is.

**This is an optional add-on, not part of the core engine, for two reasons:**

1. **Different data source.** It pulls from outside the OSM/CRT pipeline the rest
   of Pound is built on, so it has no place on the critical path of the build.
2. **Licensing is not settled.** Unlike the core sources, CanalPlanAC is **not
   clearly open**. OSM is ODbL and the CRT open data is published under an open
   (OGL-style) licence — both usable with attribution. CanalPlanAC is one
   developer's project; the site disclaimer is liability-only and grants no
   reuse rights, and the compiled distance/lock figures are a substantial
   database likely covered by copyright/database right. "Provided for interest"
   is not a licence. Using it as a baked-in oracle would mean scraping at scale
   or hand-transcribing a meaningful portion of its data — **either of which
   needs the author's (Nick Atty's) explicit permission first.**

**Therefore:**

- The core engine ships and is fully testable WITHOUT this module (build-time
  validation in §7 stands alone).
- `validate/oracle.py` is gated behind an explicit opt-in flag and is **not**
  populated with CanalPlanAC data unless/until permission is obtained.
- Until then, a few reference routes (e.g. Cheshire Ring) may be **hand-entered
  by the developer** as test fixtures from publicly visible figures for personal
  validation — kept minimal, attributed, and clearly separated. Do not automate
  bulk extraction.
- If permission is granted, this module can grow into a proper cross-check
  (distance ±5%, locks exact where possible) against an agreed data slice.

---

## 9. Build order (Pound, internal)

1. **Freeze `schemas.py` + stub `plan_route` + structural unit tests.** Unblocks
   the Agent Core. (Day 1.)
2. **Regional ingest + graph build** for ONE area via Overpass (Cheshire Ring).
   Small, fast, iterable.
3. **Cost model + point-to-point routing** on that region. Get a real route out.
4. **Build-time graph validation** (connectivity/lock-attachment/filter) for the
   region. Trust the graph before trusting routes.
5. **Amenities** (OSM POIs + CRT) within the region.
6. **Scale to full GB** via Geofabrik + osmium; run connectivity validation;
   fix/flag gaps.
7. **Day budgeting + rings.** (Ring loop-finding can be last.)
8. **(Optional, only if permission obtained)** External oracle cross-check
   (§8) — separate, gated, never on the critical path.

---

## 10. Dependencies & notes

- `pyosmium` (OSM parsing), `osmium` CLI (`tags-filter`), `shapely` (geometry,
  buffers), `networkx` (graph v1), optionally `psycopg`/PostGIS + pgRouting
  (graph v2), `rtree`/`shapely.STRtree` (spatial index for snap/amenities),
  `pydantic` (schemas), `requests` only for the OFFLINE ingest (Overpass/CRT),
  never at request time.
- Python 3.12+.
- Keep the full GB extract OUT of the repo (gitignore `data/`); ship only small
  regional fixtures.
- All cost constants in `route/cost.py`, documented, single source of truth for
  the planner (and for the structural unit tests in §7.2).
- The request-time path must run with no network and no LLM — that is what keeps
  Pound testable and self-contained.
- **Data licensing (load-bearing):** OSM is **ODbL** — attribution + share-alike
  on derived databases; comply in any distributed artifact. CRT open data is
  published under an **open (OGL-style)** licence — attribution. **CanalPlanAC is
  NOT open** — no reuse grant, compiled-database rights likely apply; treat as
  permission-gated per §8 and keep it out of the core build entirely.

```

