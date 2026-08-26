# Route-independent places query design

> **Status:** Refined and user-approved
> **Issue:** #15 — Build offline amenity index and location-based POI search

## Goal

Replace the OSM-only `POST /api/catalog-places` surface with one route-independent
`POST /api/places` API. It returns nearby or viewport-visible points of interest from
both the independent OSM catalog and the curated boat-hire CSV, while preserving each
source's identity and provenance.

A caller supplies geographic points or canal line segments when it needs nearby
results. The places API does not know about route legs, days, graph node handles, or
`RouteResult`.

## Scope

- Rename the public HTTP endpoint to `POST /api/places` and remove
  `/api/catalog-places` without an alias.
- Support two explicit request modes:
  - `viewport` for the existing map-layer use case;
  - `nearby` for a batch of caller-named points or canal line segments.
- Query the existing OSM catalog and the validated boat-hire enrichment CSV through one
  API, returning one flat result list with explicit provenance.
- Refactor boat-hire CSV loading so the existing network-overlay seed selection and
  places queries consume the same validated parsed records.
- Deduplicate CSV hire bases against OSM only through explicit OSM identity evidence.
- Preserve complete-result semantics: a query either succeeds with every bounded match
  or fails explicitly.

## Non-goals

- No route planner enrichment, `RouteResult.amenities` population, leg/day assignment,
  or graph-node/edge-handle input or output.
- No new OSM amenity taxonomy, boat-rental OSM ingestion, geocoding, request-time
  network access, CLI, or UI controls.
- No catalog-artifact schema change and no merger of provider data into the OSM catalog.
- No arbitrary GeoJSON geometry, pagination, partial responses, or proximity/name-based
  cross-source deduplication.
- No change to the legacy graph-bound `/api/route-pois` endpoint.

## Architecture

### Sources remain independent

`pound/catalog` remains the OSM-only artifact, spatial index, metadata normalization,
and internal build provenance surface. The boat-hire CSV remains a curated provider
source with its own provider/location identities. Coordinate or name similarity is not
identity evidence.

Implement this design after the hire-base travel-time-map change (`feat/hire-base-travel-time-map`,
through `96d1d2f`) lands. Reuse its extended `BoatHireSeed`, one-time loader, and
`snap_boat_hire_bases` contracts; do not restore `select_boat_hire_overlay` or create a
second CSV parser. Extend the shared parsed representation only with fields required by
public places.

At application startup, parse and validate the boat-hire CSV once into rich internal
records. The existing map-network overlay continues to derive seeds from every
non-excluded row, preserving the sibling design's marker and reachability behavior.
Public places output selects only non-excluded `record_type=company_base` rows; internal
`review_positive` rows remain curation evidence and are never returned as hire
providers. The richer company-base records retain only output fields that have been
validated for public use:

- provider ID and provider name;
- location ID and `location_name` as the display name;
- WGS84 coordinate;
- validated provider, location/OSM, evidence, and booking URLs where present.

Raw notes, telephone, email, and arbitrary CSV columns stay internal. Validate every
row's `record_type` against the closed set `company_base | review_positive`; unknown or
misspelled values fail startup rather than silently disappearing from public output.
Excluded rows are then skipped before coordinate and public-URL validation, preserving
the current allowance for incomplete out-of-coverage records. Blank optional values
remain valid. A nonblank
newly exposed URL receives the same absolute-HTTPS validation already used for active
location evidence; fields never exposed in `PlaceResponse` remain ignored and must not
become new startup-fatal validation input.

For a non-excluded company base, nonblank `osm_url` must additionally be the canonical
absolute HTTPS form `https://www.openstreetmap.org/{node|way|relation}/{positive_id}`
with no credentials, query, or fragment; malformed values fail startup. Blank remains
valid when the existing evidence requirement is otherwise satisfied.

### Runtime query composition

Build one concrete runtime `PlacesIndex` during app startup. It owns the existing
`CatalogSpatialIndex`, the parsed boat-hire records, and the existing
`GraphSpatialIndex` where waterway-distance filtering is needed. It is a concrete
composition, not a source-plugin framework.

`CatalogSpatialIndex` must stop accepting the public HTTP request model directly.
Refactor it into source-level viewport and nearby operations with domain inputs: selected
OSM catalog kinds, normalized text, optional route/day policy geometry, target metric
geometry/radius, and supplied remaining-work and remaining-result budgets. Source
operations stop and signal before exceeding either remainder; `PlacesIndex` decrements
both across sources and targets, owns the aggregate result ceiling, and identifies the
target that exhausts it. `PlacesIndex` owns HTTP mode validation and the combined kind
allowlist; catalog code continues to accept only its unchanged OSM `CATALOG_KINDS`.
Viewport candidate accounting must be kind-aware so a `boat_hire`-only request does not
consume OSM work budget.

Nearby catalog lookup stores normalized catalog geometry in BNG and adds an STRtree over
that full metric geometry, while the existing WGS84 display-point tree remains the
viewport-marker index. Transform each target to BNG and call Shapely STRtree
`query(target, predicate="dwithin", distance=radius_m)`; do not materialize a buffer
polygon. Count returned candidate positions against one aggregate batch work budget,
then compute exact distance values for output ordering. This gives inclusive radius-zero
and boundary semantics, avoids reprojection-envelope undercoverage and target-buffer
cost, and prevents area/line records whose representative marker lies outside the
corridor from being missed. Measure the extra
BNG geometry/tree startup time and memory; do not silently fall back to
representative-point candidates if it exceeds the measured deployment budget.

For boat-hire records, directly scan the small curated record set and calculate the same
metric distances. The implementation should leave a `ponytail:` comment documenting
that the direct scan is intentional and should become an STRtree only if the curated
source materially grows.

For either source, apply selected kind and optional Unicode-casefolded text filtering.
Boat-hire text matches provider and location names. Merge source results only after each
source has calculated its own distances.

Before returning merged results, parse each nonblank company-base `osm_url` as an exact
OpenStreetMap node/way/relation identity. When that exact identity matches OSM results, suppress every selected catalog kind with
the same `(osm_type, osm_id)` only when the matching CSV `boat_hire` record is itself
emitted for the same viewport or nearby target after kind, text, and distance filtering.
A marina-only query or text filter that
excludes the hire record must retain the requested OSM result. Do not suppress OSM from
`review_positive` rows because no public provider record replaces it. Do not infer
identity from coordinates, names, other URLs, or proximity. Multiple genuine CSV
providers at the same physical base remain distinct.
The internal slash-joined overlay exception key remains unchanged; structured identities
are required only at the public API boundary.

### No public places revision handshake

`catalog_revision` remains in the serialized OSM artifact for developer/build
provenance only. The public places endpoint has no revision request field, response
field, health preflight, or retry behavior. A query is self-contained geographic input
against the snapshot loaded by the server.

Routing artifact revisions remain unchanged because they protect client-supplied graph
node handles; that is a separate correctness concern.

## Public API

### Endpoint and public naming

Replace the public `CatalogPlacesRequest`, `CatalogPlaceResponse`, and
`CatalogPlacesResponse` contracts with `PlacesRequest`, `PlaceResponse`, and
`PlacesResponse`. Migrate TypeScript types, the API client, tests, documentation, and
in-repository callers in the same change. Repository search confirms no external
labyrinth consumer imports these web catalog models; this approved breaking rename does
not require a compatibility alias. Do not rename the internal OSM catalog artifact
classes or modules.

`POST /api/places` accepts a discriminated request on `mode`. Define the HTTP-only
`PLACE_KINDS` allowlist as `CATALOG_KINDS | {"boat_hire"}`. Do not add `boat_hire` to
`CATALOG_KINDS`, `CatalogPlace`, or the OSM artifact validator.

### Viewport mode

`viewport` preserves the current map-layer behavior:

```json
{
  "mode": "viewport",
  "kinds": ["pub", "marina"],
  "bounds": {"south": 51.0, "west": -2.0, "north": 52.0, "east": -1.0},
  "text": "canal",
  "route_geometry": {"type": "LineString", "coordinates": [[-1.5, 51.5], [-1.4, 51.6]]},
  "day_geometry": {"type": "LineString", "coordinates": [[-1.5, 51.5], [-1.45, 51.55]]},
  "policy": {"basis": "route", "radius_m": 2000}
}
```

Its policy bases remain `route`, `waterway`, and `none`. `route` requires
`route_geometry` and a radius; `waterway` requires a radius; `none` permits neither
radius nor route filtering. The existing optional selected-day geometry keeps its
current meaning for map display: `day_geometry` is optional, but when supplied it
requires `route_geometry`; `route_geometry` remains valid without `day_geometry`.
Both use the same nonempty finite WGS84 LineString validation. The client already owns
the day label, so the API no longer accepts or echoes a separate `day` integer. The old
`segment` policy and `segment_geometry` are
removed; `nearby` is the replacement for segment proximity.

`boat_hire` is a valid kind in viewport mode. Route and waterway policies apply the
same metric-distance semantics to it as to OSM records.

### Nearby mode

`nearby` has no route/day/leg fields and no client-supplied bounds:

```json
{
  "mode": "nearby",
  "kinds": ["pub", "boat_hire"],
  "radius_m": 1000,
  "targets": [
    {
      "id": "day-1",
      "geometry": {
        "type": "LineString",
        "coordinates": [[-1.0, 52.0], [-1.01, 52.01]]
      }
    },
    {
      "id": "overnight-stop",
      "geometry": {"type": "Point", "coordinates": [-1.02, 52.02]}
    }
  ]
}
```

Each request has one nonnegative, finite radius, one nonempty selected kind list, one to
64 targets, and an optional text filter; those values apply to every target. Add a strict
`GeoJSONPoint` model beside the existing `GeoJSONLineString`. Each target has a
caller-unique, bounded, nonblank ID and one GeoJSON `Point` or `LineString` in
`[lon, lat]` order. Points have one finite in-range coordinate pair and count as one
vertex; lines have at least two and count each coordinate pair. The aggregate count uses
the existing shared geometry-vertex ceiling. The server derives safe candidate
envelopes from target geometry and radius.

Do not accept graph edges, node IDs, OSM way IDs, polygons, or arbitrary GeoJSON.
Current graph-edge identities are synthetic/rebuild-dependent, while an OSM way ID can
span multiple graph edges or be merged with another source edge. Published geometry is
the stable route-independent value contract.

A place within radius of more than one target is emitted once per matching target with
that target's distance. This lets a caller map results to any grouping it owns without
making the API infer day or leg meaning.

### Result model

A successful `PlacesResponse` contains only a flat `places` list. It has no revision,
matching-count, or over-cap field: list length is the successful count and successful
results are complete.

Every `PlaceResponse` includes `kind` (including `boat_hire`), display `name`, WGS84
coordinate, and these explicit context fields:

- `target_id: str | null` and `distance_to_target_m: float | null`;
- `distance_to_full_route_m: float | null`;
- `distance_to_selected_geometry_m: float | null`;
- `waterway_distance_m: float | null`;
- discriminated `provenance` with a source-specific structured identity.

For `nearby`, `target_id` and `distance_to_target_m` are non-null, while
`distance_to_full_route_m`, `distance_to_selected_geometry_m`, and
`waterway_distance_m` are always null. For `viewport`, target fields are null and only metrics actually
calculated by its policy/geometry are non-null. OSM provenance contains OSM element
type/ID and existing normalized `CatalogMetadata`. Boat-hire provenance contains
`provider_id`, `provider_name`, `location_id`, `location_name`, `provider_url`,
`osm_url`, `evidence_url`, and `booking_url`; optional URL fields are null when absent.
The boat-hire popover displays `osm_url` as an ordinary validated source link, separate
from the provider link. Structured identities avoid ambiguous slash-joined
provider/location strings. The discriminator in
`provenance` is `osm` or `boat_hire`.

Nearby results sort by input target order, then increasing distance, source, and
source-specific identity. Viewport results use the active proximity distance when one
exists, then source and identity. Source order is fixed as `osm` before `boat_hire`;
exact distance/identity ties are deterministic.

The TypeScript response is likewise a provenance-discriminated union. The viewport
store derives a collision-free `placeKey` from the structured source identity when
merging independent policy-group responses. The map renderer branches explicitly:

- OSM places pass `provenance.metadata` to the existing catalog information renderer,
  derive the OSM link from structured element type/ID, preserve Google Maps search and
  OSM attribution, and keep the current distance fields;
- boat-hire places render provider/location identity plus validated provider, location,
  evidence, and booking links, without pretending they are OSM metadata or adding a new
  layer control.

This is a response-model migration, not a compatibility shim with flat `identity` or
`metadata` fields.

## Validation, limits, and availability

Keep the existing bounded-query posture. Preserve existing `catalog_max_*` settings and
`POUND_CATALOG_*` environment keys so deployment configuration does not break; public
endpoint/model/error names become places-oriented. Add only a new
`places_max_targets` setting and `POUND_PLACES_MAX_TARGETS` environment key for the
nearby batch ceiling. This split is deliberate: existing catalog keys retain deployment
compatibility and now bound both `/api/places` modes, while target batching never existed
in the OSM-only API. Create `pound/web/places.py` for combined places orchestration and
move the live query ceilings there as `MAX_PLACES_RESULTS = 1_000`,
`MAX_PLACES_QUERY_WORK`, and `MAX_PLACES_VIEWPORT_SPAN_DEGREES`; explicitly delete
`MAX_CATALOG_RESULTS` and its catalog-package export, migrate config/import/inventory
limit tests, and remove the other obsolete catalog query-limit exports so there is one
live constant for each ceiling. Remove source-level result-cap enforcement from catalog
querying. OSM artifact taxonomy, kind/radius policy, and artifact-build limits remain in
`pound/catalog`.

- selected kinds must be nonempty, known, and within the existing maximum;
- viewport span, radius, aggregate vertex count, and candidate-work limits retain their
  current configured ceilings;
- nearby adds a named target-count ceiling (initially 64) and shares the aggregate
  geometry-vertex ceiling;
- the existing 1,000-result ceiling applies to the complete response: one viewport
  result set or the aggregate of every nearby target.

A request over target, kind, radius, viewport, vertex, or work ceilings fails with
status `413` and code `places_query_budget_exceeded`, with precise `fields`. Crossing
the result ceiling instead returns status `413` and the distinct code
`places_result_limit_exceeded`, identifying the target that crosses the aggregate cap
when applicable. Both return no place records and offer no pagination. Callers can
reduce radius or kinds, or split a long segment. The frontend maps only
`places_result_limit_exceeded` to the existing zoom-in message; other budget errors keep
their actionable structured error.

Invalid mode-specific fields, geometry, IDs, bounds, policy combinations, or kinds fail
with structured `400` errors. A successful zero-match query returns `200` with
`{"places": []}`.

The places surface is deliberately all-or-nothing: it is available only when the OSM
catalog loaded and the boat-hire CSV parsed successfully, so callers never interpret one
source's absence as no matches. A valid header-only or all-excluded boat-hire CSV counts
as loaded and yields no `boat_hire` places; it does not disable OSM results. Invalid or
missing boat-hire data remains a startup-fatal configuration error, as today. A missing
or invalid optional OSM catalog leaves routing
available but makes `POST /api/places` fail with status `503` and code
`places_unavailable`, with no partial results. `/api/health` replaces its public
`catalog_status` and `catalog_revision` fields with
`places_status: "available" | "unavailable"`, while retaining its existing broad health
and routing-artifact fields. `places_status` is available only when both sources loaded.
Preserve current top-level semantics: an unconfigured optional catalog reports healthy
with unavailable places; a configured catalog that fails to load reports degraded. The
catalog revision remains internal artifact metadata only.

The frontend deletes catalog revision state, request fields, and the 409 retry path. It
retains one health read for standing `places_status` UI: unavailable disables the layer
controls and shows the current unavailable notice, but it does not preflight each places
query. For parallel viewport policy groups, clear stale places before launching, then
use `Promise.allSettled`: merge every fulfilled group by structured `placeKey`; set one
zoom-in boolean when any group fails with `places_result_limit_exceeded`; collect the
first non-result-limit failure as the actionable error; and render fulfilled groups even
when another group hit the result cap. Remove matching-count state. A runtime `503`
updates the standing unavailable state.

## Migration

- Remove the old catalog endpoint path and its HTTP-specific models/types; do not leave
  a compatibility route. Change the FastAPI validation-error path match and structured
  codes from catalog-oriented to places-oriented at the same time.
- Remove the public and internal `segment` request fields, policy basis, spatial branch,
  TypeScript fields, and tests; `nearby` is their sole replacement.
- Migrate the current map client to `viewport` mode, delete its health/revision retry
  machinery, use provenance-aware merge keys and popovers, and map viewport `413`
  responses to the existing zoom-in state. This preserves current catalog-layer behavior
  but adds no boat-hire UI controls or nearby-query UI.
- Preserve `catalog_max_*`/`POUND_CATALOG_*` deployment configuration and add the
  bounded target setting. Update Docker/README endpoint, benchmark, segment-removal,
  result-limit, health/degraded-mode, and configuration documentation together.
- Keep `pound/catalog` build, artifact validation, and internal revision metadata
  intact.
- Keep `/api/route-pois` and the route planner untouched.

## Testing and acceptance

Add or update focused tests for:

1. shared boat-hire parsing: one validated CSV parse serves both overlay seed selection
   and place output; unknown record types fail startup, excluded rows short-circuit incomplete coordinates/URLs, blank
   optional public URLs remain valid, noncanonical company-base OSM URLs and invalid
   nonblank exposed URLs fail loudly, unexposed CSV columns remain ignored, and review
   rows continue to seed the overlay without becoming public providers;
2. source provenance and structured identities; `PLACE_KINDS` admits `boat_hire` only
   at the places boundary, while the OSM catalog allowlist/artifact validator remains
   unchanged; exact company-base OSM identities suppress their matching OSM result,
   review rows never become providers, coordinate-only coincidences remain separate,
   and multiple genuine providers at one base remain distinct;
3. nonempty target batches, Point-as-one-vertex and LineString nearby geometry,
   exact-radius inclusion, full-area/line geometry candidate selection, aggregate
   candidate-work/result accounting, text/kind filters,
   repeated cross-target matches, and deterministic ordering;
4. viewport behavior for both sources and preservation of route/waterway filtering;
5. explicit rewrites of current 200/`over_cap` source/API/store tests to the 413
   `places_result_limit_exceeded` contract, plus mode validation, empty kinds,
   target/vertex/work/result limits, 413 without API partial output, OSM-catalog 503 without partial output, and
   boat-hire configuration remaining startup-fatal;
6. removal of `/api/catalog-places`, migration to `/api/places`, validation-handler and
   health-field changes, deletion of revision retries, preservation of existing
   deployment environment keys, and explicit benchmark-builder/output test migration;
7. frontend provenance-aware merge keys and OSM popovers, boat-hire popover safety,
   one-shot health status without revision handshakes, result-limit-only zoom messaging,
   and removal of dead matching-count state.

Migrate `scripts/catalog_query_benchmark.py` and its tests to construct the shared
boat-hire records and `PlacesIndex`, then time `PlacesIndex.query(PlacesRequest)`—the
runtime public-query path, not source-level catalog operations or HTTP transport. Require
a boat-hire CSV argument. Keep fixed viewport cases plus representative point, line, and
multi-target nearby cases. Benchmark JSON replaces `matching_count`/`over_cap` with
`result_count` for successes or `outcome: "result_limit_exceeded"` for the intentional
limit exception, alongside candidate-work and timing; README uses the same outcome/result
column. Preserve the nationwide startup/index-load gates (<= 130 s in-process and <=
4,615,019 KiB peak RSS) and the query gate (p95 and max <= 50 ms for every fixed case).
If the required BNG geometry/tree
exceeds either startup gate, stop implementation and return for a user-approved redesign;
do not relax the gates, reduce correctness, or substitute representative-point lookup.
Tune/reject aggregate query work before relaxing query gates. Record the new measured
baseline in README.

Run focused Python and frontend tests first, then `uv run pytest`, `uv run ruff check .`,
the frontend typecheck, and the production frontend build.
