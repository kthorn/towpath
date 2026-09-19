# Loop trips from a base

## Scope

Complete the circular-trip portion of #18 alongside the existing out-and-back mode.
Discover both a simple circuit through the selected base and a simple connecting path
from the base to a circuit, followed by that circuit once and the reversed connection.
Only the connection may be retraced. No repeated laps or multiple-circuit itineraries.
An optional visit must occur on the complete trip. Base and visit support current projected
canal handles and artifact revisions. No turnaround index is required for continuous travel.

## Search and route contract

Use a deterministic, iterative search over boat-eligible public graph edges. A simple path
from the base can close onto an earlier vertex, identifying the circuit and its connection.
Require at least three distinct circuit vertices and positive circuit distance. Keep both
travel directions as alternatives, because directional events and day packing can differ.
Deduplicate by the full ordered trip. Peel unreachable dead ends while preserving the base
and its connection. Use shortest return-time lower bounds to prune paths
that cannot get home, then apply the shared conservative reporting-segment day budget to
every complete candidate. Count locks and bridge events on every traversal.

Order alternatives by descending complete distance, then raw cruising time and ordered path.
The first is the default; all retained alternatives have complete geometry, days, budget,
warnings and deterministic request/route identities. Work, result, and geometry limits fail
explicitly rather than returning an incomplete collection as successful.

Add `/api/loop-candidates` and `/api/loop-route`, using existing finite closed-trip constraints
and paired selection IDs. Responses identify `journey_type: loop`, circuit distance, one-way
connection distance, branch descriptions, and the existing journey with `is_ring: true`.
No feasible loop returns `no_feasible_loop`; changed selections use `stale_route_selection`.
Existing artifact-revision, invalid-handle and search-limit errors retain their semantics.

## Manual UI

Add a Loop journey mode alongside Point to point and Out-and-back. Require a base and time
budget; retain optional Visit on the way. Show circuit-through-base and circuit-with-connection
alternatives, full totals and remaining time. Selecting one displays its exact preview.
Endpoint, constraint and mode changes invalidate candidates; late responses cannot restore them.

## Verification

Fixture tests cover circuits through the base, retraced connections, directional alternatives,
multiple circuits, excluded repeated laps, optional visits, dimension/access restrictions,
exact and fractional budgets, locks and bridges, day packing, projection, graph immutability,
stable ordering and IDs, stale selections, and search caps. API and UI tests verify discovery,
selection and invalidation. Run the full default Python suite, Ruff, web tests/check/build,
and applicable fixture-backed browser tests. No new artifact format or download is needed.

## Validation notes

The default Python suite passes with the new routing/API fixtures. Additional independent
cycle-plus-disjoint-stem enumeration on 30 seeded small graphs agrees with the discovered
path sets. A local Great Britain artifact smoke check near Stone finds 30 alternatives for
three days at six hours per day (longest total distance 50.7219 km). Dense Alvechurch-area
searches exceed the default work cap; with a higher work cap, the three-day search exceeds
1,000 results. Limits are deliberate and must remain visible, not treated as no feasible loop.
