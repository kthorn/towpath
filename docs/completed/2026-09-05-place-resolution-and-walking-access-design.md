# Place resolution and walking access (#77)

Status: approved and implemented. OSM-first lookup, automatic Google fallback, and walking-only
attraction transfers are the initial policy. See implementation notes below for runtime contracts
and the remaining real-catalog measurement gate.

Issue: https://github.com/kthorn/towpath/issues/77

## Outcome and scope

Resolve “visit Bletchley Park” into a sourced attraction and a bounded set of canal access
alternatives, with walking availability checked from each access point to the attraction and
back. Represent the attraction as a required visit, independently of access and turnaround.
This issue supplies the lookup and browser coordination primitives for #20; it does not build
the conversational agent, choose a hire base, or implement closed journeys.

Reuse the OSM catalog, places query machinery, canal-candidate API, Google map display, and
transfer adapters. Do not introduce another attraction database. Driving, cycling, transit,
commercial enrichment, opening-hours planning, and durable Google content are outside scope.

## Lookup policy

1. Search OSM first, using a bounded name lookup over existing catalog records.
2. Resolve automatically only for one exact normalized name or recorded alias match within
   the requested scope, with valid coordinates and no incomplete-search condition. This is
   a deterministic rule, not a confidence score or a guarantee of user intent. Display the
   selected identity and allow correction.
3. Multiple plausible records require selection. A lone partial match also requires
   confirmation. Do not silently merge nearby OSM records or let Google break an OSM tie.
4. Search Google automatically after a complete OSM miss or catalog unavailability, or after
   the user rejects OSM suggestions. Preserve the reason for fallback.
5. Google suggestions require user selection on the browser's Google display surface,
   including when only one suggestion is returned. Retain interactive autocomplete and
   explicit coordinate input as recovery options.
6. An exhausted OSM work/result budget is incomplete search, not a miss. Ask for a narrower
   query or allow an explicit Google search within the remaining overall budget. Do not
   automatically widen geography, paginate indefinitely, or retry on every model turn.

Normalize whitespace and case; only use aliases actually present in source metadata. Do not
invent locality when absent. Report that the catalog covers selected place kinds, not every
named geographic feature. Broader place requests can reach Google through the same fallback.

Use an explicit user-specified area when present. Otherwise use the supported Great Britain
extent for a named-place lookup; a small current map viewport must not silently hide a named
destination elsewhere. Ask for locality when results are ambiguous. Geography must come from
validated application state or a sourced selection, never model-generated coordinates.

## Contracts and ownership

`resolve_place` accepts bounded query text, supported kinds, an application-owned search
scope reference, and a request identifier. Server policy supplies budgets; callers cannot
raise them. Reject unknown fields, invalid kinds, and invalid scope references.

The internal outcome is a discriminated union:

| Outcome | Meaning |
| --- | --- |
| `resolved` | One accepted source-backed place reference |
| `ambiguous` | Bounded options requiring explicit selection; includes lone partial matches |
| `not_found` | Searches attempted completed without a usable match in the stated scope |
| `unavailable` | Required source or browser unavailable; include a typed reason |
| `incomplete` | Work, result, or overall time budget exhausted |

Track each source attempt separately: an empty Google response does not turn an unavailable
OSM catalog into proof that neither source has a match. While waiting for Google or selection,
the operation has a separate `pending` lifecycle state; do not return a false terminal miss.

The owner-side place record carries an option reference, source identity, name, coordinates,
nullable locality, and provenance. OSM identity is element type plus ID, with catalog revision;
Google identity is the provider place ID retained in browser memory for this session. Manual
coordinates have explicit user-input provenance and must not masquerade as a provider match.

Separate this record from the model-visible response. OSM records may expose catalog fields;
Google responses expose only application-owned state and opaque option references to the
model. Google names, addresses, coordinates, IDs, durations, and paths must not enter model
transcripts, tool traces, analytics payloads, or durable catalog/graph records.

After a Google selection, the browser submits its coordinate directly to the existing
validated canal-candidate endpoint, as in manual selection. The server may process that
coordinate for the request; exclude request bodies from logs and discard provider-derived
input after processing. Correlate the returned candidate set with the selected session option.
Browser provenance is an assertion, not independently verified OSM or graph evidence.

## OSM coverage and indexing

This checkout has `pound/web/places.py`, a spatially bounded text filter, and local artifacts
named `england.pkl` and `england-catalog.pkl`. Those filenames do not establish current Great
Britain coverage. The companion agentic discovery proposal describes a newer main with a
`packages/pound-*` layout. Confirm current-main paths before implementation; do not reset
unrelated working-tree changes or implement against obsolete API handles.

Before selecting the lookup index, inspect the active Great Britain catalog's provenance,
extent, record counts, supported kinds, name/alias/locality completeness, and Bletchley record
coverage. Measure exact, partial, duplicate, and missing-name searches at national scope,
including examined records, memory, and latency. Publish the measurements with implementation.

Reuse `/api/places` filtering for suitable bounded spatial queries. If national named lookup
cannot satisfy work limits, derive an in-memory normalized name/alias index once when loading
the same catalog. Index entries reference existing records; there is no new source of truth.
Bound partial-match enumeration too. Rebuild on catalog revision changes. An index is an
implementation choice justified by measurement, not a new persisted artifact requirement.

## Google fallback and display

Add a separate browser text-search capability alongside interactive autocomplete; do not
drive the autocomplete DOM as a headless search API. Use `Place.searchByText` with explicit
extent, a result cap, and the minimum identity/location/display fields. Explicitly validate
returned coordinates against the permitted extent, regardless of provider bias behavior.
See [Google Text Search documentation](https://developers.google.com/maps/documentation/javascript/place-search).

Keep results and selection details on the existing Google map/display path with required
attribution. Do not enrich OSM marker records or persist cross-provider matches. Preserve the
issue's transient-content boundary and follow the applicable
[Places policies](https://developers.google.com/maps/documentation/places/web-service/policies).
This lookup extension does not adopt the separate commercial enrichment work in #28.

## Canal access and walking

Feed the selected attraction coordinate into the same validated candidate request used by
the manual flow. Retain current artifact revision and projected candidate handles. Consume
#6 access evidence/ranking when available. Otherwise label candidates as geometric suggestions
and require confirmation before adoption; neither proximity nor a successful walking route
establishes permission to moor or safe access from a boat.

For each candidate, obtain candidate-to-attraction and attraction-to-candidate walking
results independently. The existing transfer adapter is one-origin/many-destinations: use
one attraction-to-candidates matrix and a bounded one-origin request per candidate for the
other direction. Never copy or reverse a duration/path to manufacture the return walk.

Retain an availability outcome for every candidate and direction. Only candidates with both
directions available can be described as having a checked return walk. Show partial results
separately; never substitute straight-line distance as walking time. Preserve access evidence
ranking, then compare complete walking totals in the browser with stable candidate tie-breaks.
The model receives availability and option references, not provider-derived ranking details.
Fetch detailed walking paths only for the selected access option, in both directions.

## Bounded browser task bridge

Use a small application service independent of an LLM runtime. The server issues tasks via a
session event stream, and the browser posts correlated results. The future agent and manual
flow consume the same request validators and adapters; #77 needs no live model integration.

Bind tasks to authenticated session ownership, run ID, task ID, selected option, candidate
set, artifact revision, fixed `WALK` mode, request digest, and expiry. Validate ownership on
event and result endpoints. Search tasks permit a query and extent; transfer tasks permit
only the registered selected coordinate and candidate coordinates. Accept at most one
terminal result per task with an atomic pending-to-completed transition. Cancellation,
replacement selection, expiry, disconnect, and revision changes invalidate outstanding tasks.

Validate payload size, schema, finite coordinate ranges, allowed candidate IDs, direction,
and bounded counts. Coordinate conversion is explicit: application `{lat, lon}`, Google
`{lat, lng}`, and GeoJSON `[lon, lat]`. Range checks alone cannot detect every swapped pair;
compare transfer inputs with registered coordinates and enforce geographic extent.

Browser transfer results sent to the server contain application-owned availability/reason
enums and option references only. Durations, distances, paths, provider errors, and provider
place details remain browser-side. Treat even valid browser availability as untrusted session
input; it can drive session choices but cannot update durable graph/access evidence.

Proposed defaults, to be checked against existing API ceilings and measurements:

| Limit | Initial value |
| --- | --- |
| Query length | 200 characters |
| Displayed place options | 5; detect overflow rather than silently proving uniqueness |
| OSM lookup work | At most 100,000 examined entries per operation |
| Automatic Google searches | 1 per lookup; no automatic retries or pagination |
| Access alternatives checked | At most 5 from a bounded candidate query |
| Walking matrix work | At most 10 directed pairs, at most 2 requests concurrently |
| Detailed route requests | 2 for the selected candidate |
| Browser provider task deadline | 20 seconds |
| Provider work deadline per operation | 60 seconds, excluding user selection time |
| Pending selection lifetime | 10 minutes; revalidate artifact and option on selection |
| Browser result payload | 16 KiB maximum |

Enforce cumulative session limits in addition to per-operation limits to prevent repeated
fallback and reselection from creating unlimited provider work. Initial session caps: 10
text searches, 100 matrix pairs, and 20 detailed routes within the selection lifetime.
Budget rejection is explicit and offers manual recovery without silently retrying.

## Delivery and verification

Implement in these dependency-ordered slices, adapting paths to current main:

1. Catalog coverage/performance inventory and strict resolution schemas; fake catalog tests.
2. OSM resolver and any measured index extension; deterministic identity/ambiguity tests.
3. Correlated session task service; ownership, expiry, replay, cancellation, and limit tests.
4. Browser Google text-search adapter and source-labelled selection, with fake SDK tests.
5. Shared canal-candidate coordination and both walking directions, with fake transfer tests.
6. Manual integration and a model-free contract harness for #20; aggregate outcome metrics.

Acceptance fixtures cover synthetic Bletchley resolution with multiple access alternatives;
duplicate and partial names; OSM success without a Google call; fallback after miss,
unavailability, and rejected suggestions; both sources missing; truncated results and work
exhaustion; absent locality; Google selection; malformed or out-of-scope coordinates; swapped
axes; unavailable provider/browser; asymmetric and partial walking results; no candidates;
geometric-access confirmation; stale artifact/selection; expired, duplicate, oversized,
cross-session and unknown-candidate results; cancellation races; and provider data exclusion
from model responses and logs.

Tests remain offline with fake catalog, Google, browser, and model-consumer responses. Run
focused Python and frontend tests before the default Python suite, Ruff, frontend tests,
type checks, and build. No live Google or model calls belong in the default suite.

Record aggregate source outcome counts, fallback reasons/frequency, user rejection rate,
lookup work/latency, timeouts, and directional transfer failures. Do not retain query text
or provider payloads for these metrics. Use these measurements to reassess OSM-first ordering.

## Implementation notes

Implementation targets current main `16d2cf4`, using `packages/pound-core`, `packages/pound-web`,
and the existing Svelte frontend. The `pound.catalog.resolve` module is separate from the
existing route/node resolver. It indexes the same catalog records by normalized name and
alias, using trigram postings to bound partial searches. No artifact format changes are made.

The first release exposes the supported Great Britain bounding extent as scope `gb`.
Additional application-owned regional scope references can be added later. Provider searches
use explicit bounds rather than IP or map-viewport bias. For multiple Google matches, names
and addresses remain available in browser selection cards; neither enters server task results.

The HTTP bridge is under `/api/place-sessions`:

| Operation | Method/path | Request/result |
| --- | --- | --- |
| Create | `POST /api/place-sessions` | Session ID, bearer token, 600-second expiry; browser memory only |
| Resolve | `POST /{session_id}/resolve` | `ResolvePlaceRequest` → run/status, OSM result, optional browser task |
| Reject OSM/search Google | `POST /{session_id}/google` | `run_id` → bounded search task |
| Select | `POST /{session_id}/select` | `run_id`, `option_ref`, Google coordinate only → walking task |
| Manual recovery | `POST /{session_id}/manual` | Coordinate and optional existing run → walking task |
| Browser event | `GET /{session_id}/events` | One pending SSE event; bearer header required, never token in URL |
| Complete | `POST /{session_id}/tasks/{task_id}/result` | Run/digest, outcome and opaque refs or directional availability only |
| Model-safe status | `GET /{session_id}/result` | Application-owned state, references and availability; no Google details |
| Cancel | `DELETE /{session_id}` | Invalidate session and pending work |

All per-session operations require its bearer token. Tokens are separate from model-visible
run/task/option references. Request bodies are bounded to 16 KiB before parsing, validation
errors omit input values, and responses are `no-store`. A provider option binds to a hash of
its first selected coordinate; this prevents later coordinate substitution without claiming
independent verification of the browser's source assertion. Pending task digest and candidate
set remain server-owned. Expiry, cancellation, replay and artifact change invalidate work.

The registry is bounded to 1,024 sessions and is process-local, matching the current single
Uvicorn worker. Restarts lose sessions and require a new lookup. Multiple workers/replicas
would require session affinity or a shared ephemeral registry before enabling this bridge.
Expired sessions cannot be accessed and are removed on access or the next session creation.
Do not add request-body logging or persist bearer credentials/provider input.

Limits implemented include 20 resolutions, 10 Google searches, 100 directional matrix pairs,
and 20 detailed routes per session. The detailed-route ceiling is enforced in the browser;
provider billing quotas remain the deployment control for direct browser SDK calls. A single
operation permits 60 seconds of provider work, excluding time awaiting user selection. Browser
tasks have at most 20 seconds each, with a small client margin to report before expiry.

The manual attraction panel keeps attraction state separate from trip endpoints. It requires
acknowledgement of unconfirmed geometric access before previewing both walking directions.
Clearing/replacing the attraction restores existing endpoint overlays. This is access preview,
not a claim of an adopted complete boating journey; #20 owns conversational integration.

Structured logs contain only source/outcome enums, work counts, lookup timing, fallback
reasons and counts of unavailable directions. They exclude queries, provider payloads and
coordinates. The same controller and HTTP contracts can be driven by a model-free browser
consumer; no agent SDK or live model is introduced.

Real Great Britain catalog coverage and latency could not be measured locally: the available
England catalog predates the current safe loader. The checked-in GB build reports 218,443
records, exceeding the 100,000-entry national scan budget. The reproducible inventory and
its measured limitations are documented in `2026-09-05-place-resolution-inventory.md`.
A current GB artifact must be staged before the real-catalog Bletchley/latency release check.
Implementation tests use synthetic source-backed places and fake provider/browser responses.

Keep any later step-by-step execution plan disposable and do not commit review transcripts.
