# Hire-base reachability highlight design

- **Date:** 2026-08-29
- **Status:** Refined
- **Scope:** Let one hire-base marker focus the canal network reachable from that base while retaining the all-base reachability context.

## Goal

Clicking an active boat-hire base highlights the canals reachable from that base under the current Days, Hours per day, boat dimensions, and movable-bridge delay. The all-base reachable network remains visible underneath. The selection persists while those controls change and clears when the user clicks the map away from a base.

This work builds on the same branch's approved map visual-hierarchy change: Days and Hours per day move into a full-width Cruising time bar, and canal overlays use pale casing with saturated blue centers. Route planning remains unrestricted by the display overlay.

## User experience

Every hire-base marker remains keyboard accessible and retains its operator/base popup. Clicking or keyboard-activating a marker both opens that popup and selects the base. The selected marker adds a `.selected` class with a double high-contrast ring (`0 0 0 3px #123f37, 0 0 0 5px #f59e0b`), placing dark green against the existing white border and orange against dark green, plus an accessible label ending in “selected.” Selecting another marker switches the focus. Clicking the selected marker again leaves it selected.

The map draws four ordered canal layers:

1. the all-base reachable network (`#0284c7`, center weight 4);
2. the selected base's reachable network (`#00324d`, center weight 6);
3. the planned canal route (`#0369a1`, center weight 7); and
4. the selected route day (`#0ea5e9`, center weight 9).

The union and selected-base centers have at least 3:1 luminance contrast; these values provide approximately 3.28:1. Their casing remains pale blue. The in-progress branch's saturated `#0284c7` union and the dark focused blue use casing, weight, and saturation—not an assumed Google road color—to remain distinguishable from the base map and from each other.

Each canal layer uses a pale casing beneath its blue center. A cloud map style attached to the deployment's existing `VITE_GOOGLE_MAP_ID` makes road strokes lighter and more neutral, reduces POI emphasis, and desaturates rural landscape and land-cover greens toward a pale neutral sage. Labels remain readable and water remains recognizably blue. Embedded JSON map styling is not added.

A click on empty map closes the base popup, clears the selected marker and focused overlay, and leaves the all-base network visible. It preserves the current click-consumption rule: when a popup or base selection is active, that first background click clears it and does not also set a trip endpoint. A later background click continues to set the currently active endpoint.

Days, Hours per day, saved boat dimensions, and movable-bridge delay continue to update the network without route submission. A selected base remains selected while those values change, and its focused reach refreshes automatically. Route submission and Reset trip stay with the origin/destination workflow. `App.svelte` passes `formId="route-actions"` into `BoatConstraints.svelte`; the route-action form uses that `id`, and both top schedule inputs use the received value in their `form` attributes. This explicitly restores the Enter-to-submit behavior lost when the in-progress visual-hierarchy change moved those inputs out of the form without coupling the schedule component to an ID it does not own.

## API contract

Extend the existing strict `CanalNetworkRequest` in `pound/web/api.py` with:

- `selected_base_identity: str | None = Field(default=None, min_length=1)`.

The matching TypeScript request field is optional and nullable so callers in the updated frontend remain source-compatible. Frontend and backend must deploy together because an older strict backend rejects the new field. `TripStore.setNetworkRequest` merges the App-supplied schedule/boat request with the store-owned selected identity into one normalized request; App never owns or overwrites selection. If that normalized request exactly equals `desiredNetworkRequest` across every schedule, boat, bridge-delay, and selected-identity field, `setNetworkRequest` is a no-op. Otherwise it assigns the request, increments the generation, and schedules refresh. The 422 recovery path uses the same normalization after clearing selection.

Extend `CanalNetworkResponse` in `pound/schemas.py` and the matching TypeScript contract with:

- `highlight_lines: list[GeoJSONLineString]`, always present.

When no base is selected, `highlight_lines` is empty. Existing request fields, field bounds, the 168-cruising-hour cap, `artifact_revision`, `lines`, and `bases` retain their current semantics. The request remains one pure `POST /api/canal-network`; no second endpoint or cache is introduced.

A non-null identity must exactly match one active startup-cached `BoatHireAnchor.seed.identity`. An unknown identity returns a structured 422 response with code `selected_base_not_found` and `selected_base_identity` named in `fields`. FastAPI request-model validation runs before the endpoint, so malformed, empty, or wrongly typed fields receive ordinary validation 422 first. For a valid parsed body, endpoint precedence is `network_unavailable` 503, travel-budget 413, unknown selected identity 422, then graph computation. The web client only sends identities received in `bases`, but the API still validates this trust boundary.

## Server reachability

The API calculates the all-base union with the existing `select_boat_hire_reachability` call. For a selected identity, it filters the immutable startup-cached anchor tuple to the one matching anchor and calls that same function with a one-item tuple. It then passes both edge-subgraphs independently through `prepare_network_geometry`.

The focused calculation therefore inherits the current rules without duplication:

- both endpoints of an eligible anchor edge are zero-cost sources;
- dimensions gate anchors and traversed edges;
- cruising time, locks, edge bridge events, and arrived-node bridge events use the shared route-cost calculation;
- both endpoints of a displayed edge must be reached within the cutoff; and
- neither calculation mutates the full graph or startup anchors.

If the selected anchor edge is ineligible for the current boat, the selected marker remains visible and `highlight_lines` is empty with HTTP 200. Geometry-preparation failure retains the endpoint's existing `503 network_unavailable` behavior rather than returning a partial pair of overlays. A selected request runs one additional Dijkstra traversal, a full-graph eligibility scan to select reached edges, and geometry preparation for the focused subgraph. This deliberate per-refresh cost avoids eager per-base payloads and a second synchronization path. Revisit it only if measured click or refresh latency is unacceptable.

Union and focused geometry are simplified independently and may use different tolerances under the same per-call vertex ceiling; together they may contain up to twice that ceiling. A small visual offset is an accepted initial approximation; the manual map check must exercise dense and sparse areas. If it produces a visible double-line artifact, surface a shared simplification-tolerance primitive before release rather than adding client-side correction.

## Client state and request flow

The trip store owns `selectedHireBaseIdentity` because it already owns the desired network request, request generations, retained successful payload, map attachment generation, and overlay replay.

The store exposes `selectHireBase(identity: string | null)`. If the identity already equals `selectedHireBaseIdentity`, it is a no-op and does not refetch. Selecting a changed non-null identity immediately:

1. records the identity and increments `desiredNetworkGeneration`, invalidating any in-flight pre-selection response;
2. uses the existing guarded `mapCall` path to call `view.hireBases(successfulNetwork.bases, identity)` when a successful payload exists, otherwise making marker repaint a no-op;
3. uses `mapCall` to call `view.focusedNetwork([])`, clearing lines belonging to the previous identity; and
4. schedules the existing debounced network refresh with `selected_base_identity` included.

Clearing selection first records null, increments `desiredNetworkGeneration` to invalidate in-flight selected responses, merges null into `desiredNetworkRequest`, cancels any pending selected refresh, and immediately updates markers and focused lines through `mapCall`. It computes the current canonical constraint key after the null merge. Only when a retained payload exists with an exactly matching `constraintKey` does it advance that record's generation, replace its focus ownership with `selectedBaseIdentity: null` and `highlightLines: []`, and avoid a network request. If no retained payload exists or its key differs, it leaves the record older and schedules the normal debounced null-selection union refresh. Schedule or boat-setting changes preserve a non-null selected identity and issue one combined request for the union and focused lines.

Extend the retained `SuccessfulNetwork` record with `highlightLines`, the `selectedBaseIdentity` captured from the dispatched request, and a canonical `constraintKey` containing every request field except `selected_base_identity`. Represent the key as a fixed-order tuple of Days, Hours per day, length, beam, draft, height, and movable-bridge delay so equality has one implementation shared by clear/reset and 422 recovery. The server does not echo the identity or key. Only a response whose generation is still current may replace this record. Painting is deliberately less strict than response acceptance: `drawNetwork` may paint retained union lines and bases even when their request generation is older than the current desired generation. It paints retained focused lines only when `successfulNetwork.selectedBaseIdentity === selectedHireBaseIdentity`; otherwise it calls `focusedNetwork([])`. On map attachment, the store paints any retained union immediately, applies the identity check to focused lines, and separately starts the current request when generations differ. Consequently schedule edits and failed A-to-B switches keep union context across Settings remount without accepting stale responses or repainting A's focus.

The store detects `selected_base_not_found` by duck-typing `status === 422` and `code`, matching its existing catalog-error precedent without importing the concrete API error class. It clears selection locally and always schedules one debounced null-selection retry so changed server base records are refreshed. Before retry, it compares the failed request's canonical constraint key with `successfulNetwork.constraintKey`: only an exact match permits advancing the retained union's generation and treating it as current while the retry runs. A mismatch leaves the retained record explicitly older, so remount may paint it only as temporary context and must still start the current null-selection request. The expected selected endpoint failure does not publish `networkError`; if the bounded recovery request fails, normal error reporting applies. The retry cannot repeat because its request contains no selected identity. Other failures retain the existing stale-overlay behavior.

The state exposed to `App.svelte` includes the selected identity so selection survives map remounts during Settings navigation. It is not persisted to browser storage. `TripStore.reset()` invokes the same key-guarded clear-selection path: it clears TripState/internal selection, cancels a pending selected refresh, updates markers and focused lines through `mapCall`, merges null into the desired request, increments the generation, and reuses retained union metadata only when its constraint key matches. A missing or mismatched retained payload schedules a null-selection refresh, preventing Reset during initial load from stranding the app. App's simultaneous reset to a different default schedule then calls `setNetworkRequest`, whose equality guard advances the generation and lets the debounce collapse work into the latest request. If constraints were already default and the retained key matched, App's reactive re-publication compares equal and performs no redundant request.

## Map integration

Extend `MapView` with these required members:

- `focusedNetwork(lines: GeoJSONLineString[]): void`;
- `hireBases(bases: BoatHireBase[], selectedIdentity: string | null): void`; and
- `onHireBaseSelect(callback: (identity: string | null) => void): () => void`.

Every production adapter and test fake implements all three, and every `CanalNetworkResponse` fixture supplies `highlight_lines`. `MapCanvas.svelte` binds `onHireBaseSelect` to a callback supplied by `App.svelte`, following its existing map-click subscription lifecycle. The Google adapter uses a hire-base-specific click binder rather than adding selection behavior to the shared catalog/POI/lock `bindMarker`. It preserves the current hover-tooltip listeners, pushes every listener into both `hireBaseMarkerListeners` and the aggregate `markerListeners` cleanup collection, notifies selection subscribers before opening the existing popup, and relies on the SDK's current `gmp-click` mapping for keyboard activation.

`hireBases` stores `selectedIdentity` as the adapter's selection-active state and reconciles markers by the response's stable, ordered full base records (identity, operator, name, and coordinate). Extend `MarkerInstance` with writable `title: string`; the SDK adapter and map-test fake expose the underlying AdvancedMarker title setter. The adapter retains each marker's content element so unchanged records update its `.selected` class and `aria-label` alongside `marker.title` without closing the InfoWindow or recreating markers. It closes the popup and replaces markers/listeners when any record changes or a new map is attached. If replacement lacks the requested identity, it renders no selected marker and stores null locally but does not notify subscribers from inside reconciliation; reconciliation itself never initiates a store selection clear. This avoids re-entering `hireBases` while marker replacement is in progress.

A background map click checks both `infoWindowOpen` and the stored non-null selected identity. If either is active, it closes the popup, sets adapter selection state to null, notifies hire-base subscribers with null after adapter state is stable, and consumes the click before the endpoint callback. Thus Escape or the InfoWindow close control may dismiss only the popup, while the next background click still clears and consumes the selected base. Marker-specific hover/click listeners are removed on marker replacement. Hire-base selection subscribers belong to the `MapView` lifetime and survive marker replacement; they are removed only through the unsubscribe returned by `onHireBaseSelect` or by `destroy()`. Focused casing/center polylines and all remaining listeners are removed by `destroy()`.

Layer z-indices are explicit and non-overlapping: retain all-base casing/center at 1/2, add focused-base casing/center at 3/4, renumber planned-route casing/center to 5/6 and selected-day casing/center to 7/8, and intentionally set land-transfer polylines to z-index 9 so access legs remain visible above every canal layer. Update network, route, and day style assertions and add a land-transfer z-index assertion. The manual map check confirms that land legs do not obscure selected-day interpretation near route endpoints. The shared cased-line helper continues to own the casing color and weight delta; each layer call site supplies its center color, center weight, and starting z-index.

`fitNetwork()` remains based on all-base geometry plus hire-base coordinates. Focused geometry is a subset and does not independently affect bounds. The adapter owns focused casing/center polylines in a dedicated collection parallel to `networkLines`, replacing them atomically and clearing them on `destroy()`.

## Error handling and accessibility

- Unknown identities receive structured `selected_base_not_found`; empty or wrongly typed identities receive FastAPI's ordinary validation 422. Only the structured missing-base error triggers client recovery.
- An eligible request with no focused reached edges succeeds with an empty highlight.
- Current generation checks prevent stale responses from changing selection or geometry.
- The selected marker uses an outer outline or box-shadow with contrast beyond the existing white border, plus an accessible selected label.
- Keyboard marker activation performs the same selection and popup behavior as pointer activation.
- The schedule inputs retain native route-form ownership and Enter submission despite their visual placement above the map.
- Base-selection failure does not block endpoint selection or route planning.

## Verification

Add focused regression coverage for:

- request parsing with null, valid, and unknown selected identities;
- all-base union stability plus single-base focused reach;
- selected-anchor dimension ineligibility returning HTTP 200 with empty `highlight_lines`;
- identical cutoff, lock, bridge-delay, dimension, and conservative boundary-edge behavior between union and focused calculations;
- no mutation of the full graph or startup anchors;
- Python request-validation precedence for malformed/empty identities, followed for valid parsed bodies by unavailable, budget, unknown identity, and computation; TypeScript API serialization, response parsing, normalized full-request equality, canonical selection-independent constraint keys, generation increments on select and local clear, duck-typed recovery from `selected_base_not_found`, retry debounce/error suppression, and old-backend incompatibility;
- store same-identity no-op, equality-guarded `setNetworkRequest` selection merge, changed-selection generation bump, fixed-order constraint-key equality, matching-key local clear without union fetch, mismatched/missing-key clear refresh, retained `highlightLines`, matching-key generation advancement, mismatched-key 422 recovery after schedule or boat changes, painting older retained union while rejecting stale responses, immediate repaint via `mapCall`, Reset during initial load, switching, schedule/settings refresh, Reset at both changed and already-default constraints, failed-switch remount safety, same-base stale retention, and map-remount replay;
- App→MapCanvas selection wiring and unmount unsubscribe; marker pointer and keyboard selection through a hire-base-specific binder; retained hover behavior; aggregate and group listener cleanup; selection-subscriber survival across full-record replacement; activation of a newly created marker through that same subscription; writable title updates; unchanged-record reconciliation without popup closure; changed metadata/coordinate replacement without re-entrant notification; exact selected styling and accessible label; popup-closed-but-selection-active background clearing; click consumption; focused-layer exclusion from fit bounds; and destruction;
- focused casing/center ordering, union/focus contrast, network/route/day style assertions, deterministic land-transfer z-index, replacement, empty results, and cleanup relative to every map line layer; and
- full-width schedule placement, required App-owned `formId`, the route form's matching `id`, both inputs' matching `form` attributes, component-level form ownership, click submission, validation, reset, and stale route-error suppression;
- a keyless Playwright navigation test that focuses a valid schedule input, presses Enter, and observes the route-submission validation result, proving native browser implicit submission; and
- required focused-painter and selection-subscription implementations across every `MapView` adapter and test fake (including cast fakes that evade compile-time checks), `selectHireBase` across every `TripStore` fake, `selectedHireBaseIdentity` in every typed `TripState` fixture, updated two-argument `hireBases` assertions, and `highlight_lines` in every response fixture.

Run narrow Python API/algorithm tests and web store/map/component tests first. Then run the full default Python and web suites, Ruff, `svelte-check`, and the production web build. Cloud style publication against the deployment Map ID requires a manual check at rural and road-dense town zoom levels: rural greens are visibly desaturated, roads are light and neutral, POIs are subdued, labels and water remain legible, and both canal overlays stay distinct from the base map.

## Non-goals

- No multiple-base selection or comparison colors.
- No eager per-base geometry in the initial response.
- No second focused-network endpoint, cache layer, or client-side reachability calculation.
- No persistence of selected base across browser reloads.
- No base-specific restriction of route planning, candidate selection, or POI queries.
- No exact partial-edge clipping or changes to the existing anchor-edge approximation.
