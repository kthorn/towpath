# Turnaround endpoints and default out-and-back routing

Status: implemented on the out-and-back feature branch.

## Purpose and agreed behavior

Implement the first increment of [issue #18](https://github.com/kthorn/towpath/issues/18):
route from an origin to a winding hole or canal junction and return along the same path.
Pound explores every feasible combination of outbound branch choices and returns one route
to the furthest eligible turnaround along each combination, within the complete journey budget.
The globally furthest result is the default displayed route; all other branch routes are returned
for selection, including different paths that reach the same turnaround.

The user's decisions in this design discussion supersede two requirements in the original
issue: explicit turnaround confirmation is no longer mandatory, and canal junctions are
assumed to permit turning without separate evidence. Known access and dimensional
restrictions still apply. An LLM does not select the default; Pound's deterministic policy does.

“Furthest” means greatest outbound distance along the selected canal route. It does not mean
straight-line distance or greatest cruising time. Different simple branch paths are evaluated
separately; repeated-vertex detours to consume the budget are excluded.

An origin and a finite positive day budget are required. An optional destination is a required
outbound waypoint, not an instruction to turn there. The selected turnaround may equal that
waypoint. The final destination is always the origin.

Named rings, arbitrary loop discovery, multiple via-point editing, mooring selection, and the
production conversational agent are outside this increment. Existing point-to-point routing
remains available.

## Approach

Add an offline turnaround index and a pure out-and-back routing service. Reuse the existing
planner's boat constraints, traversal costs, route rendering, geometry, warnings, and day
packing. Introduce additive API operations for discovering choices and producing a route
for every branch combination, with an automatic default and user-selectable route alternatives.

This keeps endpoint eligibility separate from route search. Reusing ordinary nearby-place
snapping would risk ending before or beyond the winding hole. General loop search would add
a different routing problem and would not implement the requested retraced return journey.

## Turnaround data

### Winding holes

Retain OSM nodes tagged `waterway=turning_point` through offline ingest. Preserve source identity,
name, coordinate, source tags, source date, and attribution. The first implementation must
specify and fixture-test its supported source tags; it must not infer winding holes from a
name containing “turn” or from a wide-looking map feature.

Use OSM features from the existing ingest pipeline initially, with CRT records supplied through
the enrichment work in #17 when available. Junction-based routing and OSM-backed winding
holes do not depend on completion of every CRT layer. No request-time source lookups occur.

Represent a winding hole at its actual canal attachment. An existing matching graph vertex
can be reused; an interior attachment requires splitting the source edge before infrastructure
cost attachment and artifact finalization. Preserve total length, geometry, dimensions, access,
and each infrastructure occurrence exactly once across the split. Resolve equal-distance
attachment ambiguity explicitly during the build; do not silently attach across parallel canals.
Unmatched, ambiguous, and conflicting records stay visible in build diagnostics and are not
selectable destinations.

Do not treat the ordinary POI `nearest_node_uid` as a precise winding-hole attachment. Its
nearest edge and projected position are useful matching inputs, but the route must reach the
attached turning position.

### Canal junctions

A junction is a vertex with at least three distinct incident navigable canal-network branches
in the validated, public-access graph. Include canal lock/bridge segments connecting those
branches; exclude nonrouting features, isolated geometry crossings, and pure river junctions.
For the current simple graph, count distinct neighboring routing vertices and require at least
one incident canal segment. Preserve this classification before any future graph contraction.

Derive junction identity and eligibility once at build time, before filtering for a particular
boat. A boat-specific restriction on one branch must not make the underlying junction cease
to exist. The chosen outbound and return edges must still be traversable by that boat.

All such junctions permit turning by product assumption. Store `eligibility_basis` as
`junction_assumption`; do not label them surveyed or verified. A known explicit turning
prohibition overrides the assumption. Degree-two bends and dead ends are not inferred
turnarounds. Confirmed topology corrections belong in source overrides and a rebuild.

### Normalized record

Each record contains:

| Field | Meaning |
| --- | --- |
| `turnaround_id` | Stable namespaced source identity, or deterministic derived junction identity |
| `kind` | `winding_hole` or `junction` |
| `node_uid` | Attachment in this artifact; never portable between revisions |
| `coordinate`, `display_name` | Location and useful fallback label |
| `eligibility_basis` | `mapped_winding_hole` or `junction_assumption` |
| `sources` | Source identities, dates, tags/evidence, and required attribution |
| `turning_limits` | Known length/beam/draft/height limits and explicit prohibitions |

Merge a winding hole and junction at the same attachment into one choice, retaining both
sources and displaying the winding-hole identity preferentially. Do not merge nearby records
solely on distance. Conflicting restrictions use the more restrictive accepted value and are
reported in build diagnostics.

Unknown turning dimensions do not exclude a mapped winding hole or assumed junction.
Surface available limits and retain existing unknown-dimension warning behavior. If a known
turning limit cannot be evaluated because the boat dimension is missing, reject that choice
with the relevant field requested. Supplied dimensions exceeding a known limit also reject it.

Store the index with the artifact and validate references on load. Coordinate the serialization
change with the compact-artifact design; do not add a competing file format. Turnaround
attachments must be protected from contraction. New builds include an index even when empty;
older artifacts lacking it produce a rebuild-required capability error for out-and-back routing
while keeping existing point-to-point routing usable.

## Branch combinations and deterministic route selection

Enumerate eligible simple outbound paths from the origin: a path cannot repeat a vertex,
reverse before its final turnaround, or return to the origin during its outbound traversal.
At each fork explore every eligible unvisited continuation. Choices at successive forks form
an ordered branch combination. Alternatives that rejoin remain distinct because their earlier
paths differ. This replaces the previous proposal to find one canonical shortest path per
turnaround. Existing traversal costs evaluate paths; they do not discard a branch in favor of
a faster path to the same endpoint.

“Every combination” means every realizable combination within these simple-path and budget
rules, not a Cartesian product of choices at junctions the journey never visits. Circuits may
provide multiple simple paths to a turnaround, but outbound paths may not complete a cycle
and revisit a vertex. Each result still returns by exactly reversing its own outbound path.

Define the furthest result along a branch combination using path prefixes:

1. Traverse eligible continuations in stable vertex/edge order, retaining the ordered path,
   visited vertices, waypoint status, and traversal costs. Do not globally mark a vertex visited;
   another branch history reaching the same vertex must be explored independently.
2. At every eligible turnaround other than the origin, append the reversed outbound path,
   compute the full journey's day plan, and record it if feasible and the waypoint is satisfied.
3. Retain a recorded path as an output route only if no other recorded feasible turnaround path
   has it as a strict prefix. Thus a nearer stop on the same branch is replaced by the further
   stop, while different fork choices remain separate results.
4. Deduplicate identical complete outbound paths. If several explorations fail beyond the same
   last feasible junction, return that junction route once; do not invent separate routes for
   branches the boat would never actually traverse.
5. Render every retained journey. Rank by descending unrounded outbound canal distance, then
   ascending full travel time, then turnaround identity and lexicographic outbound vertex path.
   The first route is the display default; ranking never removes another branch combination.

This selects the furthest reachable turning point on each continuation, rather than returning
all intermediate winding holes. A path ending at a junction remains a result when no feasible
turnaround can be reached further along any continuation. Never manufacture a turning point
at the budget boundary. When some continuations fail, report their rejection reasons without
removing successful alternatives.

For example, if a first fork has left/right choices and each branch has a second fork with
upper/lower choices, return four routes when all four combinations have feasible turnarounds.
If the left and right branches rejoin before the same winding hole, return two routes to that
winding hole. Their distance, costs, day plans, and route identities may differ. If a branch's
furthest winding hole exceeds the budget, use its last feasible turning point, subject to the
prefix and deduplication rules above.

The optional waypoint is a search-state constraint: only record turnarounds after the path
has visited it. Do not independently join shortest paths to and from the waypoint. Enumerating
branch paths can find a valid waypoint journey that shortest-leg joining would miss. A waypoint
at origin is already satisfied; one at the turnaround is valid. If no feasible simple outbound
path visits it, report `waypoint_unreachable_within_constraints`, with budget or connectivity
reasons where established. No intermediate reversal is introduced to satisfy it.

Enumeration can grow exponentially. Use request-local state, deterministic work and result
caps, and admissible lower-bound pruning. Total outbound-plus-reversed travel cost is a valid
budget lower bound as the path grows; test any stronger pruning rule before relying on it.
Failure of a partial day schedule alone is not a pruning proof, since extending the outbound
path changes where the return legs enter the schedule. Do not merge states based only on
current vertex, or stop at the first/best turnaround. If complete enumeration or full response
construction exceeds a cap, return `candidate_search_limit` rather than a truncated success
or a purported globally furthest default. Performance tests must include repeated branch/rejoin
structures and deterministic limit behavior.

The returned `RouteResult.end` equals its start and `is_ring` remains `false`: a retraced
out-and-back is not a ring. `journey_type: "out_and_back"` conveys closure. The optional
waypoint is traversed on both the outward and return portions.

## Costs and budget feasibility

Require `days > 0` and finite `hours_per_day > 0`, defaulting hours per day to 6. Carry the
existing boat dimensions and movable-bridge delay unchanged. Omitted days remain legal in
the existing point-to-point API but are invalid for automatic turnaround discovery.

Calculate each traversal in its actual direction. Arrival-node bridge charging means doubling
the outward total is insufficient. Count locks and bridge operations again on the return.
Geometry, lock occurrences, warnings, and day ranges must follow the full ordered path.

Use existing leg boundaries and greedy day packing, without the existing overflow behavior
that folds extra travel into the last allowed day. A candidate is feasible only when its
uncapped day plan uses no more than the requested days and no day exceeds its time allowance.
For this new flow, pack using the larger of each leg's raw and publicly rounded minutes;
this prevents either rounding or reported totals from admitting an over-budget day. Keep
public totals equal to the sums of public legs and days. Return remaining minutes based on
the conservative budget usage, and label it as estimated cruising time.

An indivisible leg longer than a day makes that candidate infeasible. Day endpoints are
planning boundaries, not vetted overnight moorings; suitable day-stop selection remains #8.
Dimension warnings must refer to traversed edges, not edges merely explored by the search.

## API contract

Keep `POST /api/canal-route` unchanged. Add:

### `POST /api/turnaround-candidates`

Request:

```json
{
  "artifact_revision": "fixture-revision",
  "start_uid": 10,
  "waypoint_uid": null,
  "days": 3,
  "hours_per_day": 6,
  "boat_length_m": 18,
  "boat_beam_m": 2.1
}
```

Support the remaining existing boat dimensions and bridge-delay fields as well. Validate
finite numbers, reject extra fields, check revision before graph handles, and reject handles
missing from that artifact.

Respond with the artifact revision, `request_id`, `default_route_id`, ordered `routes`,
and deterministic `rejections`. Return one complete route per retained branch combination,
including its `route_id`, ordered `branch_choices`, turnaround metadata, outbound distance,
full totals, budget usage, days used, warnings, and `journey: CanalRouteResponse` with geometry
and day/lock details. This is a collection of complete journeys, not only a list of endpoints.

Each branch choice identifies the junction and the chosen outgoing edge in traversal order,
with `junction_name` and `continuation_name` for display;
route identity includes the entire ordered outbound path, even when branch labels coincide.
Derive `request_id` from canonical constraints, artifact revision, and routing-policy version.
Derive `route_id` from that request identity, turnaround identity, and ordered outbound path.
Two paths to the same turnaround must have different route IDs. Identical requests and graph
contents must produce the same ordered route collection regardless of insertion order.

### `POST /api/out-and-back-route`

Accept the same constraints with optional `route_id` and `request_id`.

- Without `route_id`, run the complete branch enumeration and return the globally furthest
  default. This convenience operation must not replace the collection operation in discovery.
- With `route_id`, require the discovery `request_id`, validate it, and recompute/validate the
  exact branch route. Never substitute another path, even to the same turnaround, on failure.
- Return `journey_type`, artifact revision, request identity, route identity, branch choices,
  selected turnaround, `selection_basis` (`furthest_reachable` or `user_selected`), budget usage,
  and the existing `CanalRouteResponse` as `journey`.

A `turnaround_id` alone is insufficient for route selection and is not an override parameter.
No graph paths supplied by the client are trusted. Request identities detect stale selections;
they are not authentication tokens and do not purport to prove human confirmation. Clients
may display a route directly from the returned collection without a second request.

### Errors

Use the existing `detail: {code, message, fields}` envelope; extend it with optional sorted
candidate-rejection details where useful. Existing clients can ignore the additional field.

| Condition | HTTP/code | User action |
| --- | --- | --- |
| Invalid constraints or missing days | 422 validation | Correct identified fields |
| Artifact revision changed | 409 `artifact_revision_mismatch` | Refresh candidates |
| Unknown origin/waypoint handle | 400 `invalid_node_handle` | Select endpoint again |
| Old artifact has no turnaround index | 503 `turnarounds_unavailable` | Rebuild artifact |
| Index contains no usable turnarounds | 422 `no_turnaround_candidates` | Choose another area |
| All candidates fail path, boat, waypoint, or budget checks | 422 `no_feasible_turnaround` | Inspect reasons/change constraints |
| Override/request identity stale or unknown | 409 `stale_route_selection` | Rediscover choices |
| Candidate search exceeds configured work cap | 422 `candidate_search_limit` | Reduce scope/budget |

Rejection reasons distinguish budget excess, known turning limits, missing boat dimensions,
unreachable public-network paths, and unsatisfied waypoints. Report necessary minutes/days where
computed. Since prohibited ways may already be absent from the graph, do not invent a specific
access restriction as the cause of a disconnected route. A work cap must not produce a partial
route collection labeled complete or claim its first element is the furthest overall.

## Manual UI and conversational clients

Add an “Out and back” journey mode. Require origin and days, and label the optional destination
“Visit on the way.” Planning uses the default automatically and shows its turnaround, outward
distance, full return totals, and selection reason. Show winding-hole versus junction kind;
make the assumed junction-turning basis available in the details.

Planning requests the complete route collection. The alternatives control lists branch routes
furthest first, with ordered canal/junction choices so routes sharing a turnaround can be
distinguished. Selecting another displays that exact returned journey (or sends its route ID
for server revalidation) and replaces the active route. There is no mandatory confirmation dialog. Changes
to origin, waypoint, boat settings, budget, or artifact invalidate old candidates and overrides;
the next plan uses the new default. Ignore stale asynchronous responses using the trip store's
existing request-generation pattern.

Reuse map, lock, day, and POI overlays. The outward and return lines overlap geographically;
the summary and day itinerary must still show both traversals. Out-and-back mode uses the
origin for the journey's final land-transfer endpoint, not the optional canal waypoint.

#20 tools should submit the same validated constraints and allow Pound's automatic default.
A conversational client receives all branch routes and can explain them, but must not collapse
different paths to the same turnaround or replace them with invented routes. Fake tool tests
should verify complete branch-set parity with the manual UI, the same default, and faithful
application of an explicit route override. No live model is required for this increment.

## Code boundaries and delivery

| Area | Expected changes |
| --- | --- |
| `pound/ingest/ir.py`, `filters.py`, `overpass.py`, `osm.py`, `prune.py` | Retain supported winding-hole features consistently across ingest paths |
| `pound/graph/turnarounds.py` (new), `build.py`, `artifact.py` | Precise attachments, junction classification, normalized index, validation |
| `pound/schemas.py` | Discovery, route, turnaround, budget, and rejection contracts |
| `pound/route/plan.py` | Extract shared rendering of an explicit traversed path |
| `pound/route/round_trip.py` (new) | Branch enumeration, full return feasibility, prefix filtering, route identities, overrides |
| `pound/web/app.py`, `api.py` | Load index and expose additive endpoints |
| `web/src/lib/types.ts`, `api.ts`, `stores/trip.ts` | Typed calls, default/override state, invalidation |
| `web/src/App.svelte`, `component/TripSummary.svelte`, new turnaround list | Mode, alternatives, selected turnaround and closed itinerary |

Deliver offline data/index support first, then pure routing and shared rendering, then API and
manual UI. Test fixture journeys before using a rebuilt regional artifact. Implementation must
account for any compact-artifact changes that land first, while preserving this product contract.

## Acceptance and verification

- A branched fixture includes winding holes and degree-three canal junctions without turning
  evidence. Junctions qualify; degree-two bends, disconnected crossings, and dead ends do not.
- A two-level binary fork returns all four feasible branch combinations, each ending at its
  furthest feasible turning point. Shorter strict-prefix routes are omitted.
- Branches that rejoin return distinct route IDs and journeys even with the same turnaround.
  A blocked or over-budget continuation falls back to the last feasible turning point, with
  identical fallback paths returned once. No feasible combination is discarded by ranking.
- The globally furthest route is the display default; every other branch result is selectable.
  Cyclic and zero-cost fixtures terminate without repeated outbound vertices or lost alternatives.
- Work/result caps return an explicit error, never a partial collection presented as complete.
- Ranking uses canal distance and remains stable under reordered graph construction and ties.
- Known restrictions reject candidates; unknown junction turning limits do not undo the assumption.
- Winding-hole attachment preserves position and total edge costs, including infrastructure.
- Optional waypoint is visited before turnaround, including when a shortest-leg approach would
  miss a valid branch path; otherwise return a precise constraint failure.
- Return path exactly reverses outbound geometry. Locks/bridges are charged per traversal;
  totals equal leg/day sums, day geometry covers the complete path, and the graph is unchanged.
- Exact budget boundaries, fractional-minute rounding, and oversized individual legs are tested.
- Discovery returns full geometry and day plans for every branch route. Default and override
  API calls agree with those journeys; stale overrides never silently select a different path.
  Empty results and work caps have deterministic errors.
- UI and fake tool tests prove automatic defaults, manual overrides, settings invalidation, and
  suppression of late responses. Existing point-to-point behavior remains covered.

Use pytest tests mirroring ingest/graph/route/web modules, Vitest for API/store/components, and
a fixture-backed browser flow. Run narrow changed suites first, then `uv run pytest`,
`uv run ruff check .`, `npm --prefix web test -- --run`, `npm --prefix web run check`,
`npm --prefix web run build`, and the applicable Playwright navigation suite. Live source checks
remain explicitly network-marked; generated artifacts and downloads are not committed.

This specification replaces the earlier full-ring execution draft and is retained in
`docs/completed/` with the implementation. Separate execution plans remain disposable
and uncommitted.
