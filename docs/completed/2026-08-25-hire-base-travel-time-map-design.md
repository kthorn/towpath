# Hire-base travel-time map overlay design

- **Date:** 2026-08-25
- **Status:** Refined
- **Scope:** Show active boat-hire bases on the startup map and show only the time-reachable background canal network from those bases. (Update: #52 changed the overlay from a one-way reach to a return-trip allowance; see the schedule-semantics lines below.)

## Goal

Replace the startup-only connected-component overlay introduced by #43 with a live,
user-specific reachability overlay. The map must show every active supported hire base and
only canal edges reachable from at least one of them within the selected cruising
time (return-trip semantics since #52). The full routing graph remains available for all route and candidate operations.

## User experience

The existing planner schedule is the single map-reachability control:

- `Days` is required and starts at **7**, rather than blank; `Hours per day` remains 6.
  These are the planner's existing schedule inputs, so reset restores them and new route
  submissions use a seven-day allocation by default. This intentionally removes the planner
  UI's uncapped submission mode: a longer route remains routable but is rendered in seven
  days with the existing over-budget final-day warning. Users can raise `Days` (up to 365) to
  plan longer journeys. The form changes its label from `Days (optional)` to `Days`, marks it
  required, and applies `min=1`/`max=365`; it also applies `max=24` to `Hours per day`. This
  deliberately tightens planner-UI hours to a physical day, while direct route API/CLI callers
  retain their existing finite-positive upper-bound-free hours contract.
- The map budget is `days * hours_per_day * 60` minutes. (Update: #52 re-scoped this
  budget to a return-trip allowance — the overlay now shows canal routes that can
  return to the same base, computed with an effective one-way cutoff of half the
  budget.)
- A valid edit to either schedule input refreshes the background network without requiring
  the user to plan a route. A short client-side debounce prevents a request for every
  keystroke; response generations ensure an older response cannot overwrite a newer one.
- Saving existing boat dimensions or the movable-bridge delay also refreshes the network.
  The map therefore uses the same constraint and cost model as route planning.
- The schedule UI states that the background map shows canal routes that can return to
  the same hire base within the selected schedule, capped at 168 cruising hours. It does not introduce a second settings screen or a
  separate time control.

Every active base receives a distinct accessible map marker. It has a hover label and a
click popup containing the operator and base name; labels are not permanently shown and
no new external links are added. The initial fit includes both base markers and reached
canal lines. Later nonempty live refreshes preserve the current viewport and any planned route
overlay; when no route is active, a valid empty-network result refits to the bases so the
remaining markers are visible.

A temporarily invalid input does not issue a request or clear the last valid overlay. A
failed refresh likewise preserves the last successful lines and markers. With a retained
overlay, the status says `Canal network overlay could not be updated: <error>`; with none,
it says `Canal network overlay is unavailable: <error>`. A valid response with no reached
lines clears only the background lines and leaves base markers visible.

## Base data and startup validation

The existing enrichment CSV remains the source of truth. `exclude=true` continues to omit
a row entirely, including its marker; blank and `false` rows remain active. Existing header,
identity, coordinate, HTTPS-evidence, 250 m snap validation, and the documented 251 m
`canal-holidays/base:62` exception remain unchanged.

Startup parses and validates active rows once, projects each base onto its nearest
routing-eligible edge, and retains its anchor plus display data in application state. A malformed
active row or failed snap still aborts startup, as it does today. It no longer selects connected
components or prepares network geometry at startup.

Extend `BoatHireSeed` and its loader to retain display fields as well as identity and coordinates.
The base response uses CSV order and supplies stable identity, coordinate, operator
(`source_provider_name` falling back to `source_provider_id`), and base name
(`location_name` falling back to `location_id`), so incomplete display metadata does not
create a new startup failure.

All active bases are returned as markers even when the current boat cannot leave a base's
anchor edge. If CSV exclusion leaves no active base, startup records a
`network_unavailable` state without preparing geometry. Every network POST then returns
`503 network_unavailable`, preserving today's all-excluded behavior rather than returning a
valid empty response.

## API contract

Replace the static `GET /api/canal-network` fetch with a strict, pure
`POST /api/canal-network` request. Define its `CanalNetworkRequest` beside
`CanalRouteRequest` in `pound.web.api`; define the additive `BoatHireBase` response model beside
`CanalNetworkResponse` in `pound.schemas`:

- `days`: required integer from 1 through 365;
- `hours_per_day`: required finite number greater than 0 and at most 24, with no implicit
  default;
- nullable finite positive boat length, beam, draft, and height; and
- nullable finite non-negative `movable_bridge_delay_min`.

This is a new strict request model that mirrors the schedule and boat-constraint fields of a
route request; it is not a literal subset because it has no start/end node or artifact revision and
requires `days`. Declare `hours_per_day` and every optional boat dimension as `FiniteFloat`,
not plain `float`. As the related trust-boundary correction, make those fields finite in
`CanalRouteRequest`, `CanalConstraints`, and `ResolvedConstraints` too, so neither route nor
overlay can accept a non-finite budget or dimension. The existing route models keep
`days: int | None`: seven required days is a planner-UI default, not a breaking API/CLI/Agent
requirement. A single `MAX_NETWORK_TRAVEL_MINUTES = 10_080` (168 cruising hours) constant
in `pound.web.config` bounds the product before Dijkstra; a larger valid field combination
returns `413 network_query_budget_exceeded` with `days` and `hours_per_day` named as fields.
Invalid individual fields receive the normal FastAPI validation response. This bounds every
request without adding a cache layer.

`CanalNetworkResponse` retains `artifact_revision` and `lines`, and adds ordered `bases`.
Each base contains its stable identity, operator, name, and WGS84 coordinate. A valid
request whose selected boat cannot reach any canal edge returns HTTP 200 with `lines: []`
and the active bases. Malformed startup configuration and failed base snapping abort application
startup as today. `503 network_unavailable` is reserved for the startup no-active-base state and
per-request geometry-preparation failure.

## Reachability algorithm

Replace `select_boat_hire_overlay` with a startup-only `snap_boat_hire_bases` function in
`pound.web.boat_hire`. It returns frozen `BoatHireAnchor` records containing the extended seed
and its validated snapped edge. The lifespan calls it once and stores the anchors on application
state; request handling never rereads the CSV or reprojects bases.

For each request, the server calculates the display subgraph from the immutable full graph:

1. Resolve the bridge-delay default through the existing route-cost owner.
2. For each active base whose snapped anchor edge meets the submitted dimensions, add both
   anchor endpoints as zero-cost sources. This preserves the current validated edge-based
   attachment without rebuilding or mutating an artifact for CSV edits. The source edge is
   the intentional graph-granularity approximation: making both endpoints free undercharges
   its whole length, locks, and bridge events, so it can overstate reach at the base. If no
   anchor supplies a source, skip Dijkstra and use no reached nodes, returning HTTP 200 with
   `lines: []` and the active base markers.
3. Run NetworkX multi-source Dijkstra to the time cutoff. Its edge-weight callback uses
   exactly the planner's dimension eligibility and directional traversal-time calculation:
   cruising time, locks, edge bridge events, and arrived-node bridge events. Factor that
   transition calculation into a pure `route.cost` helper that accepts the edge and arrived-node
   bridge IDs rather than a graph object; planner and overlay call it so they cannot drift. The
   callback passes the Dijkstra neighbor's `movable_bridge_ids` as the arrived-node IDs, not a
   canonicalized edge endpoint, preserving the planner's directional bridge charge.
4. Select only edges whose two endpoints are reached **and** whose dimensions pass the same
   `is_eligible` check for the submitted boat; create an edge-induced display view from those
   edges and pass it to the existing `prepare_network_geometry` function. This prevents a
   dimension-ineligible edge from being drawn merely because both endpoints were reached by
   other eligible paths.

The minimum time from any active base wins. A base anchor that is ineligible for the selected
boat contributes no source but remains visible as a marker. The graph is undirected, as it
is for route planning; no timetable, directionality, or new navigation rules are inferred.

Except for the disclosed zero-cost source-edge approximation, display filtering is conservative
at graph-edge boundaries: an edge is displayed only when both endpoints are within the cutoff.
Thus the small reachable part of the first boundary edge may be hidden, rather than displaying a
partial line or any time beyond the threshold.

## Frontend integration

The TypeScript network request/response types, API adapter, trip store, and map contract
are updated together. Extract one small shared schedule parser for `BoatConstraints` submit
validation and `App.svelte` live refresh validation; it accepts only 1–365 whole days and finite
hours greater than 0 through 24, so the two paths cannot drift. `App.svelte` remains the owner of raw
schedule inputs and observes the parsed schedule plus `$boatSettings`. Its 100 ms debounce calls
a new trip-store network-overlay refresh method with the derived request.

That method replaces the no-argument `PoundApi.canalNetwork()` call, owns a desired-request
generation and the last successful lines/bases payload, and retains the desired request while no
map is attached so saving settings refreshes when the planner map remounts. A response may replace
stored payload only when its request generation is still current; it may draw only when its map
attachment generation still identifies the same live `MapView`. Detaching a map increments only
the attachment generation, so a current response can still be retained for the next map without
calling a destroyed view. On attachment, the store immediately replays a retained successful
payload without a second request **only** when that payload's request generation equals the
current desired-request generation; otherwise (or with no payload), it issues the current desired
request. A failed request preserves the last successful payload and sets the stale-versus-
unavailable status above without map replacement. The trip state exposes `hasNetworkOverlay`
alongside `networkError`; `App.svelte` owns the two status templates above and branches on that
boolean, avoiding the current hardcoded `unavailable` prefix for a stale refresh. Route, candidate,
POI, lock, catalog, endpoint, and land-transfer overlays remain independent.

The `MapView` contract gains `hireBases(bases)` alongside `network(lines)`. The Google adapter
stores base coordinates for fitting and owns a dedicated base-marker collection; `hireBases()`
closes an open info window before replacement, and replacement plus `destroy()` remove its
markers and listeners through the same `removeMarkerGroup` path as the existing interactive
marker groups. Base popup content reuses the existing text-node/info-field pattern.

`fitNetwork()` bounds stored base coordinates plus network geometry, rather than lines alone.
When no canal route is active, the store fits after the first successful paint on each newly
attached `MapView`, after trip reset, and whenever a valid empty-network response leaves bases as
the only overlay. When a canal route is active, background overlay replay and refresh never fit;
the route overlay retains control of the viewport. Other in-place schedule or boat-settings
refreshes on the same attached map deliberately do not refit, preserving the user's viewport.

## Verification

Add focused regression coverage for:

- CSV display-field fallback, exclusion, snap validation, and the existing Base 62 exception;
- multi-base minimum reachability; inclusive cutoff behavior; conservative boundary-edge
  omission; no mutation of the full graph;
- identical effects of locks, movable-bridge delay, and dimension eligibility in planning
  and overlay reachability; and an ineligible anchor producing a marker but no source;
- request validation, including non-finite hours/dimensions, required `hours_per_day`, field
  bounds, and the 168-hour `413 network_query_budget_exceeded` path; 200 empty-line responses
  with bases; fail-fast invalid startup seeds; and unchanged full-graph routing and candidate
  behavior;
- the frontend's required 1–365-day/24-hour schedule attributes, seven-day default/reset, and
  intentional seven-day route-submission semantics; valid live updates from App-owned schedule
  and saved boat settings; stale-response rejection; retained-overlay status wording after a
  failed refresh; and attach-time replay only when its request generation remains current;
- base marker rendering, popup/tooltip behavior, popup close before replacement, initial/reset-
  only fitting when no route is active, route-viewport preservation, and destruction; and
- explicit rewrites of `tests/web/test_network_api.py::test_network_startup_failure_is_nonfatal`,
  `tests/web/test_boat_hire_overlay.py`'s `select_boat_hire_overlay` patch/assertions, and the
  existing API-adapter, trip-store, map-adapter, and App component tests that pin GET, component
  filtering, cached replay, empty-day reset, and empty-network no-fit behavior; and deletion of
  `tests/web/test_boat_hire.py` component-selection tests while porting its snap/Base-62 tests to
  `snap_boat_hire_bases`;
- the no-active-base startup state returning 503; source-empty reachability returning 200 with
  markers; the new anchor-retention function being called once at startup; and no request-time
  CSV read or projection;
- shared schedule parsing; optional `days` remaining valid for existing route API/CLI callers;
  finite-hours and finite-dimension rejection across route and network request models; stale
  request and detached-map response handling; and arrived-node bridge charging; and
- `MapView.hireBases`, base-coordinate fitting, marker replacement, and listener cleanup on
  settings navigation.

Run narrow Python and web tests first, then the default suite, Ruff, and real-artifact
startup/API coverage. The real-artifact gate is a documented manual pre-deployment check: start
the web app with real `POUND_ARTIFACT_PATH` and `POUND_BOAT_HIRE_ENRICHMENT_PATH`, POST the
default seven-day payload, and record curl latency plus response line and vertex counts in the PR
verification. It adds neither a committed artifact/output nor a hardware-dependent CI timing
limit. Update the README's map description to state the default seven-day hire-base
reachability behavior (return-trip semantics since #52). When implementation is delivered, move this design
to `docs/completed/` in the same pull request.

## Non-goals

- No return-trip calculation or automatic return-time reservation.
- No base selector, base-specific coloring, permanent labels, or external base links.
- No route/candidate restriction: only the background map is filtered.
- No graph artifact rebuild, request-time data lookup, client-side routing, or new cache layer.
- No exact partial-edge clipping, timetable parsing, or directed-waterway behavior.
