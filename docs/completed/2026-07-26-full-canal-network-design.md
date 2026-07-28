# Full Canal Network View

## Goal

Show the complete available canal network in the initial planner view so users can see where journeys are possible. Do this without introducing a separate explorer mode. After a successful route plan, focus the map on that route. A reset action returns the planner to its entry state and the map to the full network.

This change is limited to network geometry and trip reset behavior. Visitor-attraction discovery, catalog filters, clustering, and commercial enrichment remain out of scope.

## User experience

### Entry state

When the map is ready, the application loads and displays the full canal network and fits the viewport to it. The origin and destination searches are empty, no endpoint candidates or route overlays are shown, and the schedule fields have their default values.

Selecting a place, selecting a canal candidate, or showing a land-transfer preview must not change the viewport. Users can therefore choose endpoints while retaining the national network context.

### Planned route

After `Plan canal route` succeeds, the existing canal route overlay is drawn and the viewport fits its geometry. Existing route details, locks, day selection, and optional POI/catalog behavior continue to work.

### Reset

A `Reset trip` button sits beside `Plan canal route`. It clears both endpoint selections, candidate and transfer state, route errors, the canal route, land routes, locks, selected day, route POIs, catalog places, and the current schedule inputs. It increments request generations so in-flight endpoint or route responses cannot repopulate the cleared trip.

Reset does not clear saved boat dimensions from Settings; those are persistent preferences rather than trip state. The persistent network layer remains visible, and the map fits back to the network. The place-search widgets are remounted so their visible input values return to empty.

## Backend design

### API contract

Add `GET /api/canal-network` with a response equivalent to:

```json
{
  "artifact_revision": "...",
  "lines": [
    {"type": "LineString", "coordinates": [[-1.0, 51.0], [-1.1, 51.1]]}
  ]
}
```

`lines` contains the complete navigable network as display geometry. The response is tied to the loaded routing artifact through `artifact_revision`, allowing clients and operators to detect stale deployments.

### Geometry preparation

Prepare the display geometry once during application startup from the loaded graph artifact and retain it in application state. Do not rebuild or serialize the full graph for every request.

The preparation pipeline will:

1. read the existing edge geometries;
2. dissolve/merge contiguous segments into display line strings while preserving branches;
3. simplify intermediate vertices for display without dropping network branches; and
4. enforce a server-side vertex ceiling of 100,000 coordinates for the response.

The endpoint returns the prepared geometry. It does not expose graph node IDs, routing internals, or catalog records. If preparation or serving fails, the application reports the network overlay as unavailable but leaves route planning available.

## Frontend design

### Map interfaces

Extend the existing map contracts with network operations:

- `network(lines)` draws/replaces the persistent network layer;
- `fitNetwork()` fits the map to the currently loaded network.

The Google map adapter owns the network polylines and removes them on destroy. `marker`, `candidates`, and land-transfer drawing no longer fit the viewport. Canal route drawing continues to fit the route. Clearing a route does not automatically fit the network; only initial network load and reset do so.

### API and store flow

Add the network request to the existing Pound API adapter. When a map view attaches, the trip store requests the network once, draws it when available, and fits it. The store retains the loaded display geometry so a later map-view attachment can replay it without another request. A failed request is represented as a non-blocking network-overlay error; it must not prevent endpoint selection or route planning.

Add `reset()` to `TripStore`. Reset cancels scheduled POI/catalog refreshes, invalidates endpoint and route request generations, restores the initial trip state, clears map overlays, and calls `fitNetwork()` after retaining the network layer.

### Search lifecycle

The search component will dispose the cleanup function returned by its provider adapter. The planner will remount the endpoint search components on reset, which clears provider-owned input contents without adding a provider-specific reset API.

## Error handling and compatibility

- A missing or invalid network response is non-fatal to the planner; the map reports that the network overlay is unavailable.
- The endpoint includes the routing artifact revision but does not require a client-supplied revision, matching the existing read-only health-style behavior.
- Existing artifact loading and route API compatibility rules remain unchanged.
- OSM attribution remains visible in the planner footer and applies to the derived network geometry.

## Tests

Add focused tests for:

- network response schema and API adapter GET behavior;
- network geometry preparation, simplification ceiling, and branch retention using a small graph fixture;
- map adapter network drawing, replacement, fitting, and cleanup;
- store network loading, replay on map attachment, non-blocking failure, and reset invalidation;
- planner reset clearing visible searches, schedule values, state, and overlays;
- route planning still fitting to the successful route;
- existing candidate selection and route-planning behavior remaining usable while the network request is unavailable.

Run the narrow backend/frontend tests first, then the standard Python and frontend test/check/build commands.

## Out of scope

- A separate mode or navigation route;
- map tile infrastructure or viewport-based network queries;
- visitor-attraction layers or catalog changes;
- new commercial provider integrations;
- changing persistent boat settings.
