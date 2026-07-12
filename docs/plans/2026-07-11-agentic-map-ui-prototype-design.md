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
  |- GET /api/health
  `- graph artifact loaded once at startup
                |
                v
Pound: deterministic canal routing
```

Google-specific objects must not enter Pound schemas. API responses use WGS84 coordinates and GeoJSON so another map provider can replace Google without changing the routing engine.

## 4. User Flow

1. Search for an origin using Google Places, or select a point on the map.
2. Send its coordinates to `/api/canal-candidates`.
3. Pound returns the nearest 5-10 canal graph nodes within a configurable radius.
4. Use Google's Route Matrix in the browser to rank reachable candidates for one configured transfer mode.
5. Recommend the shortest reachable candidate while retaining alternatives for manual selection.
6. Repeat for the destination.
7. Request `/api/canal-route` with the two selected node UIDs and boat constraints.
8. Draw both land transfers and the Pound canal route, with a summary of transfer time, distance, locks, cruising time, warnings, and day divisions.

The initial transfer mode is an easily changed configuration value. The model supports walking, driving (including taxi journeys), transit, and cycling. Automatic cross-mode comparison is deferred.

## 5. Pound and API Changes

Add a pure candidate function similar to:

```python
nearest_coord_candidates(lat, lon, graph, *, limit, radius_m)
```

Each candidate includes its UID, coordinate, straight-line distance, and available waterway or node name. A geometric candidate is only a **suggested canal meeting point**, not a verified mooring, pedestrian entrance, parking place, or safe vehicle drop-off.

Extend route output with the selected route's ordered geometry. Graph edges already retain two-point `(lat, lon)` segments. The API assembles these in traversal order and emits a GeoJSON `LineString`, whose coordinate order is `[lon, lat]`. Existing CLI and pure routing contracts remain compatible.

## 6. Failure Handling

- If no candidate is within the initial radius, expand the search once, then return a clear no-nearby-canal response.
- If Google finds no reachable candidate, show geometric alternatives and require manual selection.
- If Google routing fails, retain place and canal markers and allow canal routing without land overlays.
- If Pound cannot find a route, preserve endpoint selections and report whether connectivity or boat constraints caused the failure.
- Missing or invalid graph artifacts fail application startup and make `/api/health` unhealthy.

## 7. Testing

- Unit-test candidate ordering, radius limits, route-geometry ordering, and coordinate conversion with fixture graphs.
- Test FastAPI request validation and structured error responses without network access.
- Put Google Maps and Routes calls behind small TypeScript interfaces; frontend tests use deterministic fixtures rather than paid live requests.
- Add one opt-in browser smoke test against Google for place selection, candidate ranking, and overlay rendering.
- Manually validate the primary scenario using Bletchley Park and a searched rental base.

## 8. Local Development and Packaging

Development runs Vite and FastAPI separately, with Vite proxying `/api`. A multi-stage Dockerfile builds the Svelte assets and packages them with the Python application. The container accepts the artifact path and Google configuration through environment variables and mounts the graph artifact read-only.

The browser Maps key must be restricted by allowed website origins and enabled APIs. Any future server-side Google key must be separate and secret.

## 9. Deferred Work

- NanoClaw, natural-language planning, and agent tool definitions
- Curated moorings and access points, including pedestrian, vehicle, parking, transit, and mooring capabilities
- Saved rental bases, accounts, sharing, and trip persistence
- Taxi booking, fares, and automatic comparison of transfer modes
- AWS/GCP selection and production infrastructure
- Native mobile applications

## 10. Prototype Acceptance Criteria

1. Both endpoints can be selected through Google Place search.
2. Reachable canal candidates are ranked by a Google land route and can be manually overridden.
3. Pound routes between the selected canal nodes using supplied boat constraints.
4. The map displays both land transfers and an accurate canal polyline.
5. The summary exposes transfer and canal metrics plus routing warnings.
6. The application runs locally in development mode and as one portable container.
