# Route POIs, locks, and day overlays

## Status

Implemented and completed on 2026-07-21.

## Goal

Expose the newly ingested England POIs in the map without overwhelming the
browser, while making planned canal routes easier to inspect by day and by
lock.

## Scope

This feature adds:

- opt-in, route-near POI layers with category/kind filters;
- server-side viewport and route-corridor filtering with a hard 1,000-result
  display cap;
- lock markers on every planned route;
- per-day route geometries and day start/end waypoints;
- clickable day summaries that highlight and fit the selected day.

It does not add a general all-England POI browser or vector tiles. The existing
candidate markers, transfer overlays, and canal route remain unchanged.

## User experience

### POI layers

The map starts with no POI layer enabled. A layer control lets the user opt in
to named kinds grouped for discoverability:

- pubs and food/drink;
- water points;
- marinas and moorings;
- fuel and sanitary facilities;
- shops and provisions;
- transport;
- pedestrian access.

The controls filter by the artifact's existing POI `kind` values rather than
requiring users to understand the broader ingest categories. Empty selections
do not make a request.

POIs are requested only after a canal route exists. The current viewport and
selected route/day geometry constrain the result. The map adapter emits a
debounced viewport-idle event after pan or zoom; layer changes and day
selection also refresh the query.

If the server finds more than 1,000 matching POIs for the selected kinds in the
viewport and route corridor, it returns no display points and a `zoom_in_required`
state. The UI says to zoom in rather than truncating an arbitrary subset.

### Locks and days

Lock markers are always visible when a route is planned. They show the lock
name when available, otherwise a useful fallback label, plus the day on which
the route reaches them.

The full canal route remains visible in a muted style. Selecting a day in the
trip summary:

- highlights that day's route segment;
- fits the map to the segment bounds;
- shows day start/end waypoints;
- associates the visible lock markers and POIs with that day.

Selecting the active day again restores the full-route view. A day with no
travel keeps the existing no-travel behavior and does not add empty overlays.

## Backend design

### Route response extensions

Keep the existing full `geometry` and route summary fields. Extend
`CanalRouteResponse` with optional web-overlay data:

- `day_geometries`: ordered day records containing the day number, a GeoJSON
  LineString, and start/end coordinates;
- `locks`: route lock records containing coordinate, optional name, day number,
  and an `approximate` flag.

These are additive fields so existing CLI and API consumers can ignore them.
The existing `RouteResult.days` remains the textual/day-budget contract.

The planner already chunks contiguous route legs into days. During the same
computation, retain the corresponding path edge ranges and derive each day's
geometry from those ranges. Do not reconstruct day boundaries in the browser.

### Lock positions

The current graph stores lock counts on edges but not the source lock
coordinates. Extend lock attachment to retain lock points on lock-bearing
edges:

- use lock-gate or lock-node coordinates when available;
- preserve one point per attached chamber where the build can identify it;
- use the lock-bearing edge midpoint as a fallback and mark it approximate.

The artifact validator accepts this additive edge attribute while continuing to
require all existing edge fields. The route planner emits only lock points on
the selected path and assigns each point to the path edge's day.

### Route POI endpoint

Add `POST /api/route-pois` with a strict request containing:

- `artifact_revision`;
- selected POI `kinds`;
- viewport bounds (`south`, `west`, `north`, `east`);
- the full route geometry;
- an optional selected-day geometry and day number for response labeling.

The endpoint rejects stale artifact revisions and invalid bounds/kinds. It
returns:

- matching POIs, each with identity, kind, name, coordinate, and distance to
  the selected route/day geometry;
- `zoom_in_required`;
- `matching_count`, capped at 1,001 as the over-cap sentinel;
- the selected day, if any.

Use the existing category corridor limits for route proximity: 250 m for canal
services and pedestrian access, and 1,000 m for provisions and transport.
Distance calculations remain metric and use the existing Shapely/BNG helpers.

Build a POI spatial index once when the artifact is loaded. Query the viewport
first, then filter by selected kinds and distance to the supplied route
geometry. Never scan or serialize all 525,211 POIs per browser request.

The dynamic POI response is deliberately separate from `RouteResult.amenities`:
viewport, kind, zoom, and day selection make it presentation data rather than
stable route summary data.

## Frontend design

Extend the map contract with operations for:

- replacing the route POI markers;
- replacing lock markers;
- highlighting/clearing a day overlay;
- restoring the full route view;
- subscribing to debounced viewport-idle events carrying map bounds.

Keep all marker/polyline ownership inside the Google map adapter so the store
only sends declarative overlay data. Destroy and replace POI markers on every
successful query; clear them when all layers are disabled or the route is
invalidated.

Add route-overlay state to the trip store:

- selected day (`null` means full route);
- enabled POI kinds;
- latest POI response/status;
- zoom-in-required state.

Day selection should not re-plan the canal route. It only changes the selected
geometry sent to `/api/route-pois` and the map highlight.

Keep route context visible: draw the full route muted and the selected day with
the existing canal color and stronger weight. Use distinct lock and waypoint
marker titles for accessibility and browser map inspection.

## Error handling

- Stale artifact revisions return the existing structured 409 error shape.
- Invalid bounds or unknown kinds return structured 400 errors.
- POI query failures leave the route and lock/day overlays intact and show a
  non-blocking layer error.
- A failed POI refresh does not clear the last successful POI set unless the
  route or enabled kinds changed.
- A route replacement clears day, lock, and POI overlays before applying the
  new response.
- Over-cap results are a normal state, not an error.

## Testing

### Python

Add tests for:

- day geometry boundaries matching the planner's greedy day chunks;
- route lock extraction, day assignment, and approximate fallback behavior;
- POI spatial-index viewport/kind/corridor filtering;
- the 1,000-result cap and `zoom_in_required` response;
- stale revisions and invalid request bounds/kinds;
- artifact reloads with additive lock-point data.

### Frontend

Add tests for:

- POI layer toggles being opt-in;
- debounced POI refresh on layer and viewport changes;
- over-cap messaging;
- lock markers and day waypoints being rendered for a route;
- day selection highlighting/fitting the selected segment while retaining the
  muted full route;
- toggling the selected day back to the full route;
- POI and overlay failures not destroying working route planning.

Run the existing Python and frontend test suites plus the existing typecheck
and build commands before completion.

## Non-goals and future work

- No vector-tile pipeline in this iteration.
- No general POI search outside a planned route corridor.
- No arbitrary map-wide display of all retained POIs.
- No change to route cost calculation or day-budget policy.
- Future work may add richer lock metadata, clustering, or route-wide POI
  summaries if this bounded layer proves insufficient.

## Verification notes

- Optional graph-edge `lock_points` are validated during artifact load as finite,
  in-range `(lat, lon)` pairs; valid values survive save/load round-trips and
  malformed values raise `InvalidArtifactError`.
- Frontend coverage verifies that selecting the active day again restores the
  full-route selection (`null`) without replanning.
- Focused and full Python/frontend tests, `svelte-check`, the production build,
  and Ruff were run before completion; all passed.
