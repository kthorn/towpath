# Route POIs, Locks, and Day Overlays Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in route-near POI layers, always-visible route lock markers, and clickable per-day route overlays to the map prototype.

**Architecture:** Extend the existing artifact-backed FastAPI route response with day geometries and route lock records. Add a strict, viewport- and route-aware `/api/route-pois` endpoint backed by a startup-built Shapely STRtree. Extend the existing `MapView` adapter and trip store so the browser owns no POI data and only renders explicitly selected, bounded results.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, NetworkX, Shapely/pyproj STRtree, pytest, Svelte 5, TypeScript, Vitest, Google Maps facade.

## Global Constraints

- POIs are entirely opt-in; no POI markers render by default.
- The server returns no POIs when more than 1,000 matching records are in the viewport/route corridor; use `matching_count=1001` and `zoom_in_required=true` as the over-cap state.
- POI distance limits remain 250 m for `canal_service`/`pedestrian_access` and 1,000 m for `provisions`/`transport`.
- Locks are always rendered for a planned route, with exact source coordinates where available and an `approximate` midpoint fallback otherwise.
- The full route remains muted while a selected day is highlighted and fitted; selecting the active day again restores the full route.
- Existing candidate markers, transfer overlays, canal routing, CLI contracts, and `RouteResult.days` remain compatible.
- No vector-tile pipeline, general map-wide POI browser, or route cost-policy change.
- Use TDD: write the failing focused test, run it, implement the smallest change, run the focused test, then run the relevant suite.
- Do not add dependencies; reuse existing Shapely/pyproj spatial helpers and the existing Google map facade.
- Preserve the current artifact payload contract and accept additive `lock_points` edge data.

---

## File Map

### Backend route/graph files

- `pound/schemas.py`: additive `RouteDayGeometry`, `RouteLock`, `MapBounds`,
  `RoutePoi`, `RoutePoisRequest`, `RoutePoisResponse`, and route overlay fields.
- `pound/graph/locks.py`: retain lock source/fallback coordinates on lock-bearing
  edges.
- `pound/route/plan.py`: retain path edge ranges while chunking days; emit day
  geometries and route lock records.
- `pound/graph/spatial.py`: add an immutable POI STRtree index and bounded route
  query helper.
- `pound/web/api.py`: strict `/api/route-pois` request/response handling.
- `pound/web/app.py`: build and expose the POI index at artifact startup.
- `pound/ingest/ir.py`: only if a shared typed overlay or POI response field
  requires an existing model adjustment; do not duplicate `PointOfInterest`.

### Backend tests

- `tests/graph/test_locks.py`: lock-point retention and midpoint fallback.
- `tests/graph/test_spatial.py`: POI index filtering, route corridor, and cap.
- `tests/route/test_plan_route.py`: day geometries and route lock assignment.
- `tests/web/test_route_pois_api.py`: request validation, revision checks,
  bounded responses, and failures.
- `tests/web/test_startup.py`: POI index creation/replay remains startup-safe.
- `tests/web/conftest.py`: extend artifact fixtures with the new additive fields
  only where required.

### Frontend files

- `web/src/lib/types.ts`: overlay, POI, bounds, and API types.
- `web/src/lib/api.ts`: `routePois()` client method.
- `web/src/lib/google/contracts.ts`: map overlay and viewport interfaces.
- `web/src/lib/google/map.ts`: marker/polyline ownership and viewport events.
- `web/src/lib/google/map.test.ts`: adapter overlay lifecycle tests.
- `web/src/lib/stores/trip.ts`: route overlay state, day selection, POI refresh.
- `web/src/lib/stores/trip.test.ts`: store behavior and stale refresh tests.
- `web/src/component/RouteLayers.svelte`: opt-in POI kind controls and status.
- `web/src/component/TripSummary.svelte`: clickable day rows.
- `web/src/App.svelte`: mount layer controls and day-selection callbacks.
- `web/src/app.css`: minimal layer/day selected states.
- `web/src/component/App.test.ts`: integration-level layer and day interactions.

---

## Task 1: Add route overlay schemas and backend route extraction

**Files:**

- Modify: `pound/schemas.py`
- Modify: `pound/graph/locks.py`
- Modify: `pound/route/plan.py`
- Test: `tests/graph/test_locks.py`
- Test: `tests/route/test_plan_route.py`
- Test: `tests/test_schemas.py`

**Interfaces:**

- `RouteDayGeometry(day: int, geometry: GeoJSONLineString, start: Coordinate, end: Coordinate)`.
- `RouteLock(coordinate: Coordinate, name: str | None, day: int, approximate: bool)`.
- `CanalRouteResponse.route`, `.geometry`, `.day_geometries`, and `.locks`.
- Each route edge may carry additive `lock_points: list[tuple[float, float]]` in internal `(lat, lon)` order.
- `MapBounds(south, west, north, east)`, `RoutePoi(identity, kind, name, coordinate, distance_to_route_m)`, and strict route-POI request/response models are added in Task 2.

- [ ] **Step 1: Write failing schema tests**

```python
def test_canal_route_response_accepts_overlay_fields():
    response = CanalRouteResponse(
        route=_route_result(),
        geometry=GeoJSONLineString(coordinates=[(-1.0, 51.0), (-1.1, 51.1)]),
        day_geometries=[
            RouteDayGeometry(
                day=1,
                geometry=GeoJSONLineString(coordinates=[(-1.0, 51.0), (-1.1, 51.1)]),
                start=Coordinate(lat=51.0, lon=-1.0),
                end=Coordinate(lat=51.1, lon=-1.1),
            )
        ],
        locks=[
            RouteLock(
                coordinate=Coordinate(lat=51.05, lon=-1.05),
                name=None,
                day=1,
                approximate=True,
            )
        ],
    )
    assert response.day_geometries[0].day == 1
    assert response.locks[0].approximate is True
```

Run:

```bash
uv run pytest tests/test_schemas.py::test_canal_route_response_accepts_overlay_fields -q
```

Expected: FAIL because the overlay models/fields do not exist.

- [ ] **Step 2: Add the additive Pydantic models and defaults**

Add the models beside `GeoJSONLineString` and extend `CanalRouteResponse` with
empty-list defaults so older callers can construct the response unchanged:

```python
class RouteDayGeometry(BaseModel):
    day: int = Field(gt=0)
    geometry: GeoJSONLineString
    start: Coordinate
    end: Coordinate


class RouteLock(BaseModel):
    coordinate: Coordinate
    name: str | None = None
    day: int = Field(gt=0)
    approximate: bool = False


class CanalRouteResponse(BaseModel):
    route: RouteResult
    geometry: GeoJSONLineString
    day_geometries: list[RouteDayGeometry] = Field(default_factory=list)
    locks: list[RouteLock] = Field(default_factory=list)
```

- [ ] **Step 3: Add a failing lock-point retention test**

Use the existing lock fixture/build helper and assert that a source lock node
adds a coordinate to the selected edge. A gateless lock leaves `lock_points`
empty so route extraction can create and mark its midpoint fallback:

```python
def test_attach_locks_retains_source_point_or_edge_midpoint():
    graph, features = _graph_and_features_with_lock_node()
    graph, _ = attach_locks(graph, features, in_place=True)
    lock_edges = [data for _, _, data in graph.edges(data=True) if data.get("locks")]
    assert lock_edges
    assert len(lock_edges[0]["lock_points"]) == 1
    assert lock_edges[0]["lock_points"][0] == (features.nodes[0].lat, features.nodes[0].lon)
```

Run:

```bash
uv run pytest tests/graph/test_locks.py::test_attach_locks_retains_source_point_or_edge_midpoint -q
```

Expected: FAIL because lock edges do not retain `lock_points`.

- [ ] **Step 4: Implement lock-point retention**

In `attach_locks`, initialize `d.setdefault("lock_points", [])` for edges that
receive a lock. Append the matched gate/lock-node coordinate once per chamber.
For a gateless flight, leave `lock_points` empty; route extraction will use the
first lock-bearing edge midpoint and set `approximate=True`. Keep the existing
`locks` count and reports unchanged.

- [ ] **Step 5: Write failing day-geometry and lock-response tests**

Add a fixture graph with four path edges and a small `hours_per_day` so the
planner creates two days. Assert day geometries split at the same leg boundary
as `RouteResult.days`, and lock records carry the correct day:

```python
def test_plan_canal_route_emits_day_geometries_and_route_locks():
    response = plan_canal_route(_constraints(days=None, hours_per_day=1), graph=graph)
    assert [item.day for item in response.day_geometries] == [1, 2]
    assert response.day_geometries[0].start == Coordinate(lat=51.0, lon=-1.0)
    assert response.day_geometries[0].end == response.day_geometries[1].start
    assert [lock.day for lock in response.locks] == [1]
```

Run:

```bash
uv run pytest tests/route/test_plan_route.py::test_plan_canal_route_emits_day_geometries_and_route_locks -q
```

Expected: FAIL because planning only returns one combined geometry.

- [ ] **Step 6: Implement path-aware day extraction**

During `_compute_route`, retain each contiguous path edge range used by
`_chunk_days`. Add a helper with this contract:

```python
def _day_path_ranges(legs, hours_per_day, max_days) -> list[tuple[int, int]]:
    """Return half-open path-edge ranges matching _chunk_days' day grouping."""
```

Use those ranges to build `RouteDayGeometry` values with `_path_geometry` and
`_to_geojson`. Add a route-lock helper that walks the path edges, emits every
`lock_points` coordinate (or the edge midpoint when absent), marks midpoint
records `approximate=True`, and maps each point to its day range. Prefer an
attached graph node/edge name for `name`; leave it null when no name exists.
Preserve route total calculations and warning text.

`plan_route()` continues returning only `RouteResult`; `plan_canal_route()` adds
the web overlay fields.

- [ ] **Step 7: Run the focused backend suite**

```bash
uv run pytest tests/graph/test_locks.py tests/route/test_plan_route.py tests/test_schemas.py -q
```

Expected: all focused tests pass.

- [ ] **Step 8: Commit**

```bash
git add pound/schemas.py pound/graph/locks.py pound/route/plan.py \
  tests/graph/test_locks.py tests/route/test_plan_route.py tests/test_schemas.py
git commit -m "feat(route): expose lock and day overlays"
```

---

## Task 2: Add bounded route-POI querying and API wiring

**Files:**

- Modify: `pound/graph/spatial.py`
- Modify: `pound/web/app.py`
- Modify: `pound/web/api.py`
- Modify: `pound/web/config.py` only if a named cap setting is needed
- Create: `tests/web/test_route_pois_api.py`
- Modify: `tests/graph/test_spatial.py`
- Modify: `tests/web/test_startup.py`
- Modify: `tests/web/conftest.py`

**Interfaces:**

- `PoiSpatialIndex(pois: tuple[PointOfInterest, ...])`.
- `PoiSpatialIndex.query(bounds: MapBounds, route_geometry: GeoJSONLineString, kinds: tuple[str, ...]) -> PoiQueryResult`.
- `MapBounds`, `RoutePoi`, `RoutePoisRequest`, and `RoutePoisResponse` are shared Pydantic models in `pound/schemas.py`.
- `POST /api/route-pois` accepts strict `artifact_revision`, `kinds`, `bounds`, `route_geometry`, optional `day_geometry`, and optional `day`.

- [ ] **Step 1: Write failing spatial-index tests**

```python
def test_poi_spatial_index_filters_kind_viewport_and_route_corridor():
    index = PoiSpatialIndex((_poi("pub", 51.0, -1.0), _poi("pub", 52.0, -2.0), _poi("marina", 51.0, -1.0)))
    result = index.query(
        bounds=MapBounds(south=50.9, west=-1.1, north=51.1, east=-0.9),
        route_geometry=_line([(51.0, -1.1), (51.0, -0.9)]),
        kinds=("pub",),
    )
    assert [poi.kind for poi in result.pois] == ["pub"]
```

```python
def test_poi_spatial_index_returns_over_cap_without_points():
    pois = tuple(_poi("pub", 51.0 + index * 0.00001, -1.0) for index in range(1001))
    result = PoiSpatialIndex(pois).query(
        bounds=MapBounds(south=50.9, west=-1.1, north=51.1, east=-0.9),
        route_geometry=_line([(51.0, -1.1), (51.0, -0.9)]),
        kinds=("pub",),
    )
    assert result.pois == ()
    assert result.zoom_in_required is True
    assert result.matching_count == 1001
```

Run:

```bash
uv run pytest tests/graph/test_spatial.py -q
```

Expected: FAIL because `PoiSpatialIndex`, bounds, and query result types do not exist.

- [ ] **Step 2: Implement the immutable POI index**

Reuse `_TO_BNG`, `lat_lon_to_xy`, `box`, `transform`, and `STRtree` from
`pound.graph.spatial`. Index `Point(poi.lon, poi.lat)` in WGS84 and retain the
POI tuple in the same sorted order. Query the viewport tree first, filter
selected `kind` values, transform the selected route/day line to BNG, and
measure POI-to-line distance using the existing category corridor limits.
Stop collecting after the 1,001st match and return the sentinel result.

Use a small immutable result model/dataclass:

```python
@dataclass(frozen=True)
class PoiQueryResult:
    pois: tuple[RoutePoi, ...]
    matching_count: int
    zoom_in_required: bool
```

- [ ] **Step 3: Write failing API tests**

Cover valid results, no selected kinds, invalid bounds/kinds, stale revisions,
and over-cap output:

```python
def test_route_pois_returns_selected_kinds_and_revision(client):
    response = client.post("/api/route-pois", json={
        "artifact_revision": "revision-test",
        "kinds": ["pub"],
        "bounds": {"south": 50, "west": -2, "north": 52, "east": 0},
        "route_geometry": {"type": "LineString", "coordinates": [[-1.1, 51.0], [-0.9, 51.0]]},
    })
    assert response.status_code == 200
    assert response.json()["day"] is None
    assert all(item["kind"] == "pub" for item in response.json()["pois"])
```

Run:

```bash
uv run pytest tests/web/test_route_pois_api.py -q
```

Expected: FAIL because the endpoint and startup index do not exist.

- [ ] **Step 4: Add strict request/response models and endpoint**

Add `MapBounds`, `RoutePoi`, `RoutePoisRequest`, and `RoutePoisResponse` to
`pound/schemas.py`. `RoutePoisRequest` and the API body use
`ConfigDict(extra="forbid", strict=True)`. Validate bounds ordering and kinds
against the retained POI kind allowlist, reject empty route geometry, and return
the existing structured API error shape for bad input. Add:

```python
@router.post("/route-pois", response_model=RoutePoisResponse)
def route_pois(body: RoutePoisRequest, request: Request) -> RoutePoisResponse:
    if body.artifact_revision != request.app.state.artifact_revision:
        raise _error(409, code="artifact_revision_mismatch", ...)
    result = request.app.state.poi_spatial_index.query(
        body.bounds,
        body.day_geometry or body.route_geometry,
        tuple(body.kinds),
    )
    return RoutePoisResponse(
        pois=result.pois,
        zoom_in_required=result.zoom_in_required,
        matching_count=result.matching_count,
        day=body.day,
    )
```

The actual implementation must preserve the existing structured error fields;
do not leak raw validation tracebacks.

- [ ] **Step 5: Build the POI index at startup**

In `create_app` lifespan, construct `PoiSpatialIndex(artifact.pois)` once and
store it as `app.state.poi_spatial_index`. Keep `app.state.pois` unchanged for
existing tests and callers. Extend the test fixture artifact with a small set
of valid POIs attached to fixture edges.

- [ ] **Step 6: Run the focused backend suite**

```bash
uv run pytest tests/graph/test_spatial.py tests/web/test_route_pois_api.py \
  tests/web/test_startup.py -q
```

Expected: all focused tests pass.

- [ ] **Step 7: Commit**

```bash
git add pound/graph/spatial.py pound/web/app.py pound/web/api.py \
  pound/web/config.py tests/graph/test_spatial.py tests/web/test_route_pois_api.py \
  tests/web/test_startup.py tests/web/conftest.py
 git commit -m "feat(web): expose bounded route POIs"
```

---

## Task 3: Extend the browser API types and Google map overlay adapter

**Files:**

- Modify: `web/src/lib/types.ts`
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/lib/google/contracts.ts`
- Modify: `web/src/lib/google/map.ts`
- Modify: `web/src/lib/google/map.test.ts`

**Interfaces:**

- `MapBounds`, `RoutePoi`, `RoutePoisResponse`, `RouteDayGeometry`, and `RouteLock` TypeScript types matching Task 1/2 JSON.
- `createPoundApi().routePois(request)`.
- `MapView.pois(pois)`, `MapView.locks(locks)`, `MapView.day(dayGeometry | null)`, and `MapView.onViewportIdle(callback)`.
- `MapFacade.getBounds(map)` and `MapInstance.addListener('idle', ...)`.

- [ ] **Step 1: Add failing adapter tests**

```typescript
it('replaces POI and lock markers and highlights a selected day', () => {
  const { view, markers, polylines, facade } = setup();
  view.pois([{ identity: 'node/1/pub', kind: 'pub', name: 'The Pub', coordinate: { lat: 51, lon: -1 }, distance_to_route_m: 12 }]);
  view.locks([{ coordinate: { lat: 51.1, lon: -1.1 }, name: null, day: 1, approximate: true }]);
  view.day({ day: 1, geometry: { type: 'LineString', coordinates: [[-1, 51], [-1.1, 51.1]] }, start: { lat: 51, lon: -1 }, end: { lat: 51.1, lon: -1.1 } });
  expect(markers.some((marker) => marker.title === 'The Pub')).toBe(true);
  expect(markers.some((marker) => marker.title === 'Lock (approximate) — day 1')).toBe(true);
  expect(polylines.at(-1)?.options.strokeWeight).toBe(8);
  expect(facade.fitBounds).toHaveBeenCalled();
});
```

Run:

```bash
cd web && npm test -- --run src/lib/google/map.test.ts
```

Expected: FAIL because overlay methods and types do not exist.

- [ ] **Step 2: Add matching TypeScript data types and API method**

Add types with exact JSON names:

```typescript
export interface MapBounds { south: number; west: number; north: number; east: number }
export interface RoutePoi { identity: string; kind: string; name: string | null; coordinate: LatLon; distance_to_route_m: number }
export interface RoutePoisRequest { artifact_revision: string; kinds: string[]; bounds: MapBounds; route_geometry: GeoJSONLineString; day_geometry?: GeoJSONLineString; day?: number | null }
export interface RoutePoisResponse { pois: RoutePoi[]; zoom_in_required: boolean; matching_count: number; day: number | null }
```

Add `routePois(request: RoutePoisRequest): Promise<RoutePoisResponse>` to the
Pound API client and keep its error handling identical to existing POST calls.

- [ ] **Step 3: Extend the map contract and facade**

Add the overlay methods and viewport callback. Extend marker options with a
`title` only unless the current Google facade already supports a stable icon
option; do not introduce a second marker abstraction. Own separate marker
arrays for POIs, locks, and day waypoints, and separate polylines for the full
route and highlighted day.

`onViewportIdle` must call back with current map bounds obtained through the
facade, invoke the callback once immediately with the current bounds, and return
an unsubscribe function. Remove all listeners and markers in `destroy()`.

- [ ] **Step 4: Implement adapter lifecycle behavior**

`pois()` and `locks()` replace only their own marker groups. `day(null)` removes
the highlight and waypoint markers without removing the muted full route.
`day(value)` creates the stronger polyline and endpoint waypoints, then calls
`fitBounds` on the day points. `destroy()` clears every group.

- [ ] **Step 5: Run frontend focused tests**

```bash
cd web && npm test -- --run src/lib/google/map.test.ts src/lib/api.test.ts
```

Expected: all focused tests pass.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/types.ts web/src/lib/api.ts web/src/lib/google/contracts.ts \
  web/src/lib/google/map.ts web/src/lib/google/map.test.ts
git commit -m "feat(web): render route overlay markers"
```

---

## Task 4: Add trip-store overlay state and map controls

**Files:**

- Modify: `web/src/lib/stores/trip.ts`
- Modify: `web/src/lib/stores/trip.test.ts`
- Create: `web/src/component/RouteLayers.svelte`
- Modify: `web/src/component/TripSummary.svelte`
- Modify: `web/src/App.svelte`
- Modify: `web/src/app.css`
- Modify: `web/src/component/App.test.ts`

**Interfaces:**

- `TripState.selectedDay: number | null`.
- `TripState.enabledPoiKinds: string[]`.
- `TripState.routePois: RoutePoisResponse | null` and `poiError: string | null`.
- `TripStore.togglePoiKind(kind: string): void`.
- `TripStore.selectDay(day: number | null): void`.
- `TripStore.refreshRoutePois(bounds: MapBounds): Promise<void>`.
- `RouteLayers` emits kind toggles and renders zoom-in/error status.
- `TripSummary` accepts `onDaySelect(day: number): void`.

- [ ] **Step 1: Write failing store tests**

```typescript
it('keeps POIs opt-in and refreshes selected route/day data', async () => {
  const routePois = vi.fn(async () => ({ pois: [], zoom_in_required: false, matching_count: 0, day: null }));
  const { store } = setup({ routePois });
  await store.setEndpointCoordinate('origin', place('origin', 51));
  await store.setEndpointCoordinate('destination', place('destination', 53));
  await store.planCanalRoute({});
  expect(routePois).not.toHaveBeenCalled();
  store.togglePoiKind('pub');
  await store.refreshRoutePois({ south: 50, west: -2, north: 54, east: 0 });
  expect(routePois).toHaveBeenCalledWith(expect.objectContaining({ kinds: ['pub'] }));
});
```

```typescript
it('selects a day without replanning', async () => {
  const { store, canalRoute } = setup();
  await store.planCanalRoute({});
  store.selectDay(2);
  expect(get(store).selectedDay).toBe(2);
  expect(canalRoute).toHaveBeenCalledTimes(1);
});
```

Run:

```bash
cd web && npm test -- --run src/lib/stores/trip.test.ts
```

Expected: FAIL because overlay state and methods do not exist.

- [ ] **Step 2: Extend store state and API dependencies**

Add `routePois` to the injected Pound API dependency, initialize overlay state
with no enabled kinds and no selected day, and expose `togglePoiKind`,
`selectDay`, and `refreshRoutePois`.

`refreshRoutePois` must return immediately when there is no route or no enabled
kind. It sends the current artifact revision, `route_geometry`, optional
selected `day_geometry`, bounds, and enabled kinds. It records errors without
clearing the route, locks, or day overlay.

- [ ] **Step 3: Wire map replay and viewport refresh**

When `setMapView` attaches, replay endpoint/candidate/land state, full route,
locks, selected day, and the last successful POIs. Subscribe to
`onViewportIdle`; the store callback calls `refreshRoutePois` only when kinds
are enabled. Unsubscribe when the map is replaced or destroyed.

On route invalidation, clear selected day, POIs, and lock overlays. On successful
route planning, draw the full route and returned lock markers but do not query
POIs until a kind is explicitly enabled.

- [ ] **Step 4: Add the route-layer controls**

Create `RouteLayers.svelte` with grouped checkbox labels using the existing
kind strings:

```typescript
const layers = [
  { label: 'Pubs', kinds: ['pub'] },
  { label: 'Water points', kinds: ['water_point'] },
  { label: 'Marinas and moorings', kinds: ['marina', 'mooring'] },
  { label: 'Fuel and sanitary', kinds: ['fuel', 'sanitary_disposal'] },
  { label: 'Shops and provisions', kinds: ['bakery', 'butcher', 'cafe', 'convenience', 'deli', 'greengrocer', 'restaurant', 'supermarket'] },
  { label: 'Transport', kinds: ['bus_stop', 'rail_station', 'taxi_rank'] },
  { label: 'Pedestrian access', kinds: ['entrance', 'path_connection', 'pedestrian_bridge', 'steps', 'stile', 'gate', 'cycle_barrier', 'kissing_gate'] },
];
```

Each checkbox calls `store.togglePoiKind(kind)`. Render the over-cap message
when `routePois.zoom_in_required`, and render a non-blocking error when `poiError`
is set.

- [ ] **Step 5: Make day rows selectable**

Change each day row in `TripSummary.svelte` to a button. Apply an active class
when it equals `state.selectedDay`; clicking the active day calls
`onDaySelect(null)`, otherwise `onDaySelect(day.day)`. Keep the existing day
text and no-travel output.

- [ ] **Step 6: Connect App and CSS**

Mount `RouteLayers` in the planner column near `TripSummary`, pass the store,
and pass `selectDay` to `TripSummary`. Add keyboard-visible focus and selected
styles without changing the existing map layout.

- [ ] **Step 7: Run focused frontend tests**

```bash
cd web && npm test -- --run src/lib/stores/trip.test.ts src/component/App.test.ts
npm run check
```

Expected: all focused tests pass and `svelte-check` reports zero errors.

- [ ] **Step 8: Commit**

```bash
git add web/src/lib/stores/trip.ts web/src/lib/stores/trip.test.ts \
  web/src/component/RouteLayers.svelte web/src/component/TripSummary.svelte \
  web/src/App.svelte web/src/app.css web/src/component/App.test.ts
git commit -m "feat(web): add POI layers and day selection"
```

---

## Task 5: Integration verification and user documentation

**Files:**

- Modify: `README.md`
- Modify: `web/src/lib/api.test.ts` for route-POI client coverage

**Interfaces:**

- README documents the new route POI endpoint/layer behavior and the day/lock
  map interaction.
- Existing route API consumers continue accepting additive overlay fields.

- [ ] **Step 1: Add API-client compatibility coverage**

```typescript
it('posts route POI queries and returns the typed response', async () => {
  const fetchFn = vi.fn(async () => new Response(JSON.stringify({
    pois: [], zoom_in_required: false, matching_count: 0, day: null,
  }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  await createPoundApi(fetchFn).routePois({
    artifact_revision: 'rev',
    kinds: ['pub'],
    bounds: { south: 50, west: -2, north: 52, east: 0 },
    route_geometry: { type: 'LineString', coordinates: [[-1, 51], [-1.1, 51.1]] },
  });
  expect(fetchFn).toHaveBeenCalledWith('/api/route-pois', expect.objectContaining({ method: 'POST' }));
});
```

- [ ] **Step 2: Document use and behavior**

Add a short README section after the map prototype instructions describing:

- POI layers start disabled;
- layer toggles are route-near and viewport-bounded;
- “zoom in” is expected when a selected layer exceeds 1,000 matches;
- locks appear on planned routes;
- clicking a day highlights/fits its route segment;
- the new `/api/route-pois` endpoint is artifact-revision scoped.

- [ ] **Step 3: Run the complete verification set**

Run from the worktree root:

```bash
uv run pytest
uv run ruff check .
cd web
npm test -- --run
npm run check
npm run build
```

Expected: all Python and frontend tests pass, Ruff is clean, type checking is
clean, and the production frontend build succeeds.

- [ ] **Step 4: Run a live artifact/API smoke check**

Use the rebuilt England artifact:

```bash
POUND_ARTIFACT_PATH="$PWD/pound/artifacts/england.pkl" \
POUND_STATIC_DIR="$PWD/web/dist" \
uv run uvicorn pound.web.app:app --host 127.0.0.1 --port 8000
```

Verify `/api/health`, then use the browser Bletchley Park → Black Prince
Holidays scenario. Enable pubs and water points separately, zoom out until the
cap message appears, zoom in to restore markers, plan a route, click each day,
and confirm locks and day waypoints remain visible.

- [ ] **Step 5: Commit documentation and final verification changes**

```bash
git add README.md tests web/src/lib/api.test.ts
 git commit -m "docs: explain route overlays and POI layers"
```

---

## Execution Order and Review Gates

1. Implement Task 1 in one backend writer; run its focused tests and review the
   diff.
2. Implement Task 2 in one backend writer after Task 1; run focused tests and
   review the diff.
3. Implement Task 3 in one frontend adapter writer after the backend contracts
   exist; run focused tests and review the diff.
4. Implement Task 4 in one frontend/store writer after Task 3; run focused tests
   and type checking and review the diff.
5. Implement Task 5 as the final integration/documentation pass; run the full
   verification set and perform whole-branch review.

Use a fresh reviewer after each implementation task. Do not let two writers
modify the same file concurrently. If a reviewer finds a correctness issue,
fix it in the task's writer context, rerun that task's tests, and re-review with
the same reviewer model before advancing.
