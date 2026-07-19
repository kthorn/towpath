# Agentic Map UI: Local Prototype Design

> **Status:** validated design
> **Builds on:** coordinate resolution, noded graph geometry, and point-to-point routing
> **Initial scope:** map-first local prototype; agent and cloud deployment deferred

## 1. Goal

Build a local web application for exploring trips between ordinary places and the UK canal network. A user can search for an attraction or rental base, identify a practical nearby canal meeting point, view the land transfer, and calculate the canal journey between the selected access points.

The prototype validates the complete geography-first workflow without requiring an LLM. Its API boundaries should later be usable as NanoClaw tools.

## 2. Decisions

- Use Google Maps Platform for place search, the base map, land routing, markers, and overlays. It provides the best experience with the least integration work for this small application.
- Use Svelte, Vite, and TypeScript for the frontend. Svelte supplies enough structure for interactive map state without React's runtime and ecosystem weight.
- Use FastAPI as a thin HTTP boundary around Pound.
- Package production as one container: FastAPI serves both the API and built frontend assets.
- Keep deployment portable. AWS versus GCP is explicitly deferred.
- Treat both endpoints, including the rental base, as ordinary Google Place searches.

Google-specific place discovery remains in the frontend; Pound consumes coordinates.

## 3. Architecture

```text
Browser: Svelte application
  |- Google Places search
  |- Google map and land-transfer routes
  |- candidate selection and route summaries
  `- Pound canal-route overlay
                |
                | JSON / GeoJSON
                v
FastAPI
  |- POST /api/canal-candidates
  |- POST /api/canal-route
  |- GET /api/health (status plus loaded artifact revision)
  `- graph artifact loaded once at startup
                |
                v
Pound: deterministic canal routing
```

Google-specific objects must not enter Pound schemas. API responses use WGS84 coordinates and GeoJSON so another map provider can replace Google without changing the routing engine.

Artifacts already serialize a pickle wrapper shaped as `{"graph": graph, "metadata": metadata}`. `save_artifact()` adds an opaque `artifact_revision` (a UUID generated once per successful build) to that metadata mapping, and `load_artifact()` returns it through its existing `(graph, metadata)` result. FastAPI refuses to start if the field is absent, making revisionless older artifacts intentionally incompatible with the web application until rebuilt; existing CLI consumers remain able to load them.

## 4. User Flow

1. Search for an origin using Google Places, or select a point on the map.
2. Send its coordinates to `/api/canal-candidates`.
3. Pound returns the nearest configurable `N` canal graph nodes, sorted by haversine distance. A separate selection stage reduces that pool to the configured Google destination limit, initially using optional greedy geographic spacing. Pool size, destination limit, and minimum spacing are tunable implementation settings rather than API constants. Each candidate is identified by an artifact-scoped integer node handle, called a UID in the existing Pound schemas.
4. Use Google's Route Matrix in the browser to rank the downselected candidates for one configured transfer mode.
5. Recommend the shortest reachable candidate while retaining alternatives for manual selection.
6. Repeat for the destination.
7. Request `/api/canal-route` with the two selected integer node handles, the artifact revision returned with the candidates, and boat constraints.
8. Draw both land transfers and the Pound canal route, with a summary of transfer time, distance, locks, cruising time, warnings, and day divisions.

The initial transfer mode is an easily changed configuration value. The model supports walking, driving (including taxi journeys), transit, and cycling. Automatic cross-mode comparison is deferred.

## 5. Pound and API Changes

Add a pure candidate function similar to:

```python
nearest_coord_candidates(lat, lon, graph, *, limit)
```

Each candidate includes its integer node handle, artifact revision, `{lat, lon}` coordinate object, straight-line distance, and display name. The display name uses the node name, then the first alphabetically sorted distinct name from its incident edges, then `Unnamed canal point`. Node handles are meaningful only within one graph build. The API rejects a route request whose revision does not match the loaded artifact rather than risk resolving a stale handle against a rebuilt graph. A geometric candidate is only a **suggested canal meeting point**, not a verified mooring, pedestrian entrance, parking place, or safe vehicle drop-off.

Candidate generation and candidate selection remain separate. The prototype selection policy greedily retains the nearest candidate, then skips candidates within the configured spacing of an already retained point until the Google destination limit is reached. Setting spacing to zero yields the raw nearest candidates. Later, replace or augment this heuristic with an access score derived from ingested OSM roads, paths, bridges, towpaths, moorings, marinas, parking, and transit features; Google remains responsible for final transfer reachability and duration.

Do not add geometry to the shared, frozen `RouteResult` contract. Instead, factor the planner internally so the existing `plan_route()` still returns exactly `RouteResult`, while a new web-facing function returns `CanalRouteResponse(route: RouteResult, geometry: GeoJSON)`. Both use the same private route computation, which retains the ordered path long enough to assemble geometry without running shortest-path twice. This additive web model does not require `labyrinth-core` or `labyrinth-agent` to change.

The current noded graph builder emits one edge per consecutive OSM-node pair, so every edge stores a strict two-point `(lat, lon)` segment. Geometry assembly orients each segment to the selected path direction, appends it in traversal order, and omits the duplicated coordinate where adjacent segments meet. A single conversion helper then emits GeoJSON `[lon, lat]`; candidate JSON remains named `{lat, lon}` fields and the Google adapter converts it explicitly to `{lat, lng}`. Tests pin direction reversal, join de-duplication, and all three coordinate representations. If graph construction later stores variable-length edge polylines, the same assembly contract applies to every coordinate in the oriented edge geometry.

The current `RouteResult` schema permits empty `legs` and `days` because neither list has a minimum-length constraint. For `start_uid == end_uid`, return a successful zero-distance `RouteResult` with those lists empty and a two-coordinate, zero-length `LineString` containing the selected node twice; the UI labels it `No canal travel required`.

The `/api/canal-route` handler validates JSON types, the artifact revision, and the existence of both integer handles in the loaded graph before constructing `ResolvedConstraints`. A well-typed but nonexistent handle returns HTTP 400 with an `invalid_node_handle` error identifying whether `start_uid`, `end_uid`, or both failed; it never reaches NetworkX or becomes a 500. The handler invokes the new web-facing planner function that returns `CanalRouteResponse`; it does not call `plan_route()` and then attempt to reconstruct geometry from `RouteResult`. The graph is immutable after startup; request handlers and routing helpers must not annotate or mutate it. Concurrent requests share the same read-only graph rather than deep-copying the England artifact.

## 6. Failure Handling

- If the graph is empty, return a clear no-candidate response. Otherwise return the requested nearest pool; the UI shows the straight-line distance even when the canal is impractically far away.
- Treat Google Route Matrix results per candidate: retain successful elements and preserve an explicit unavailable status and failure reason for `ZERO_RESULTS` and other failed elements. If every element fails, rank geometric alternatives by straight-line distance, show a prominent transfer-data warning, and require manual confirmation.
- If Google routing fails, retain place and canal markers and allow canal routing without land overlays.
- If the map-view portion of the Maps JavaScript SDK fails after endpoint selections and candidates are available, render those candidates and the route summary in a non-map list so canal routing remains usable. Place search still requires its configured provider.
- If Pound cannot find a route, preserve endpoint selections and report whether connectivity or boat constraints caused the failure.
- Missing, invalid, or revisionless graph artifacts fail application startup, so no HTTP endpoints are served. After successful startup, `/api/health` reports healthy status and the loaded artifact revision for deployment diagnostics.

## 7. Testing

- Unit-test nearest-candidate ordering, pool limits, route-geometry orientation/join de-duplication, and coordinate conversion with fixture graphs.
- Test spacing disabled, greedy spacing downselection, tunable destination limits, and the node-name, incident-edge-name, and unnamed display fallbacks.
- Test FastAPI request validation, artifact-revision mismatch, nonexistent start/end handles (including same-handle input), and structured error responses without network access.
- Test that saving an artifact persists one revision across repeated loads and that missing revisions fail web startup.
- Exercise concurrent route requests against one loaded graph and assert that graph attributes and results do not leak across requests.
- Put Google Maps and Routes calls behind small TypeScript interfaces; frontend tests use deterministic fixtures rather than paid live requests.
- Cover mixed Route Matrix results, all-elements-failed fallback, and map-view load failure after candidates are available in frontend tests.
- Add one opt-in browser smoke test against Google for place selection, candidate ranking, and overlay rendering.
- Manually validate the primary scenario using Bletchley Park and a searched rental base.
- Test at the schema level that `RouteResult` accepts empty `legs`/`days`, then test the same-node route as a successful zero-distance journey with valid GeoJSON.

## 8. Local Development and Packaging

Development runs Vite and FastAPI separately, with Vite proxying `/api`. A multi-stage Dockerfile builds the Svelte assets and packages them with the Python application. The container accepts the artifact path and Google configuration through environment variables and mounts the graph artifact read-only.

The browser Maps key must be restricted by allowed website origins and enabled APIs. Configure conservative per-API quotas and billing alerts before sharing a hosted instance, and monitor usage so an exposed browser key cannot create unbounded spend. Any future server-side Google key must be separate and secret.

## 9. Deferred Work

- NanoClaw, natural-language planning, and agent tool definitions
- Curated moorings and access points, including pedestrian, vehicle, parking, transit, and mooring capabilities
- OSM-derived access scoring from roads, paths, bridges, towpaths, moorings, marinas, parking, and transit features ([GitHub issue #6](https://github.com/kthorn/towpath/issues/6))
- Saved rental bases, accounts, sharing, and trip persistence
- Taxi booking, fares, and automatic comparison of transfer modes
- AWS/GCP selection and production infrastructure
- Native mobile applications

## 10. Prototype Acceptance Criteria

1. Both endpoints can be selected through Google Place search.
2. Reachable canal candidates are ranked by a Google land route and can be manually overridden.
3. Each successful artifact build persists a revision, and stale candidate handles are rejected after that revision changes.
4. Pound routes between the selected canal nodes using supplied boat constraints without mutating the shared graph.
5. The map displays both land transfers and an accurate canal polyline.
6. Partial Google results expose per-candidate availability and reasons; total transfer-routing failure shows a prominent warning, and a map-view failure after candidate loading leaves a usable non-map candidate list.
7. The summary exposes transfer and canal metrics plus routing warnings.
8. The application runs locally in development mode and as one portable container.
