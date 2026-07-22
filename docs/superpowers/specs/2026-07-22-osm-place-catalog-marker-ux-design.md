# OSM Place Catalog and Marker UX

## Status

Approved design for implementation planning; revised after codebase review.

## Goal

Improve route-map marker UX while establishing a reusable OpenStreetMap catalog of
user-facing places and visitor attractions. The catalog should support current
route discovery and future locality/chat queries such as finding interesting
things to do in Milton Keynes.

## Scope

The catalog ingests relevant user-facing OSM entities across England, not merely
those currently close to navigable waterways. The initial scope includes:

- hospitality: pubs, cafes, and restaurants;
- provisions: shops and food stores;
- boating and canal services: marinas, moorings, fuel, water, and sanitary
  facilities;
- visitor attractions: museums, galleries, historic sites, gardens, wildlife
  attractions, landmarks, and similar OSM-tagged destinations.

Transport and pedestrian-access infrastructure are excluded from the new catalog
and marker UX. Google Maps is the native surface for transport information.

The catalog is broad at ingest time and narrow at presentation/query time. The
frontend decides which kinds to request and which proximity policy to apply:

- canal utilities are normally exposed only near navigable waterways;
- destinations may be shown near a route or queried broadly by locality;
- visitor attractions use an approximately 2 km waterway proximity policy when
  displayed as route overlays.

The exact attraction kind allowlist and normalized metadata fields are selected
by the metadata inventory spike before production ingestion is finalized.

## Non-goals

- ingesting every OSM entity, arbitrary OSM tags, transport infrastructure, or
  pedestrian-access infrastructure;
- storing or ingesting Google Place Details during the OSM build;
- replacing Google Maps for transport navigation;
- a nationwide map UI in this iteration;
- a new chat interface in this iteration;
- vector tiles or an unbounded browser payload;
- persisting commercial provider ratings, reviews, photos, or other restricted
  provider content.

## Architecture

Build a separate OSM place-catalog artifact and spatial index from the original
England PBF. Do not reuse the filtered waterway PBF as the catalog source. Keep
the existing routing graph artifact focused on graph and route data; the catalog
must not make route planning depend on marker presentation.

A catalog record contains the OSM identity, stable kind/category, display
coordinate, normalized user-facing metadata, source provenance, and internal
normalized geometry sufficient for spatial distance queries. Point, linear-way,
and area/multipolygon records are supported. Area records use a representative
point for marker placement but retain normalized geometry for distance filtering.
Malformed or inactive/disused records are rejected according to the inventory
manifest rather than silently converted to points.

The catalog loader builds an immutable spatial index for bounded viewport, route,
and locality queries. Build and startup measurements are mandatory: Phase 1
establishes record counts and a memory/time/artifact-size budget; Phase 2 must
meet that budget before the catalog is considered production-ready. The design
does not assume that a second all-in-memory index will fit merely because the
existing routing artifact loads successfully.

### Compatibility and migration

The separate catalog is additive initially:

- the existing routing artifact, embedded graph-bound POIs, `PoiSpatialIndex`,
  and `/api/route-pois` remain available for existing route overlays;
- existing route lock/day geometry behavior remains unchanged except for the
  centered lock-marker UX described below;
- the new catalog endpoint powers the new user-facing destination/utility layers
  and their rich metadata;
- the new UI removes transport and pedestrian-access controls rather than
  reintroducing them through the catalog;
- shared kinds are rendered from one source at a time; the frontend must not
  request both legacy and catalog markers for the same layer.

A later cleanup may migrate or remove the legacy route-POI endpoint, but that is
not required for the first catalog release. This avoids changing the strict
routing artifact contract while the independent catalog is introduced.

The backend exposes independent `artifact_revision` and `catalog_revision`
values. Route requests continue to use the routing artifact revision. Catalog
requests use the catalog revision returned by health/capability metadata and
repeat it in catalog responses. A stale catalog revision returns the existing
structured revision-mismatch shape with `catalog_revision` as the field; rebuilding
either artifact does not invalidate the other.

## Metadata contract

The frontend receives normalized, user-facing fields rather than arbitrary
`source_tags`. The Phase 1 inventory produces a checked-in manifest containing
the exact final fields, validators, coverage by kind, and explicit exclusions.
The lists below are candidates for that manifest, not permission to expose every
raw tag.

Common candidate fields are:

- name and alternate name;
- kind/category;
- brand and operator;
- address, locality, and postcode;
- opening hours;
- access, fee, and wheelchair accessibility;
- phone and email;
- website and other validated external links;
- description where useful and reliable;
- Wikidata/Wikipedia references;
- direct OSM object link;
- source/check-date provenance.

Kind-specific candidates are:

- food/hospitality: cuisine, dietary options, outdoor seating, takeaway,
  reservations, and real ale;
- shops: stock/category hints, payment options, and delivery;
- marinas/services: mooring type, capacity, fuel/service capabilities, and
  booking/contact details;
- attractions: tourism/historic classification, heritage status, admission or
  fee, facilities, opening hours, and image/media links.

Mapper notes, `fixme` fields, stale-history tags, arbitrary third-party content,
and uncontrolled raw tags are not exposed directly. Existing scope decisions
excluding generic toilet and shower POIs remain in force unless separately
revised.

External URL validation permits only `http` and `https` schemes, rejects
credentials and malformed/overlong values, and canonicalizes Wikipedia/Wikidata
references into known safe links. The frontend creates links as DOM elements,
uses safe external-link attributes, and never injects URL or description strings
as HTML. OSM object URLs can be derived from the stored element type and ID. OSM
attribution and provenance remain visible wherever OSM-derived data is shown.

## Catalog query contract

Add a new `POST /api/catalog-places` endpoint separate from `/api/route-pois`.
The frontend queries
it primarily by `kind`. A request includes:

- `catalog_revision`;
- selected kinds, with a server-validated maximum count;
- viewport bounds with a server-validated maximum span;
- optional full route geometry;
- optional selected-day geometry and day number;
- an optional proximity policy selected by the frontend.

A proximity policy has an explicit basis and radius:

- `route` measures against the full route, or the selected-day geometry when one
  is supplied;
- `waterway` measures against the navigable-waterway index;
- no proximity basis is used for locality queries without route geometry.

The frontend issues separate requests when groups need different policies; a
single mixed request never applies one radius ambiguously to utilities and
destinations. Utilities normally use a waterway policy. Route destinations and
route attractions normally use a route policy, with attractions allowing about
2 km. Locality queries use viewport bounds without a waterway requirement.

If a waterway distance is unavailable, a waterway-bounded request does not match
the record; the response may still include the record for an unbounded locality
query. The response includes each record's normalized metadata plus:

- `waterway_distance_m`, when computed;
- `distance_to_full_route_m`, when full route geometry is supplied;
- `distance_to_selected_geometry_m`, when selected-day geometry is supplied;
- the selected kind and source identity;
- bounded-result status when the request exceeds the server cap.

The backend validates kinds, bounds, revision, geometry shape, radius, and query
budgets. Hard budgets include the maximum kind count, viewport span, radius,
route/day vertex count, and a 1,000-record response cap. Over-cap queries return
no arbitrary partial set and use the existing sentinel/status pattern. Empty kind
selections do not request catalog data. The backend may reject a request that
would exceed its configured work budget even when the response cap is small.

## Marker UX

### Marker styling

Use group-level colors with kind-specific glyphs:

- attractions: purple;
- hospitality: amber;
- shops: green;
- canal utilities: blue;
- locks: a neutral chevron.

Avoid a unique color for every OSM kind. Accessible labels and tooltips state the
exact kind.

### Hover

Hover shows only a lightweight tooltip containing the place name and kind. It
does not make API calls, display links, or change persistent selection state.

### Click

The map adapter owns one shared info window for POIs and locks. Marker listeners,
content, focus behavior, and the window are cleaned up when markers are replaced
or the map is destroyed.

Click opens a persistent info window containing available fields:

- name and kind;
- distance to route;
- distance to waterway;
- lock day where relevant;
- opening hours, accessibility, and fee information;
- OSM, website, Wikipedia, or other validated links.

Absent fields are omitted. Escape or an explicit close control closes the window.
A marker click stops propagation to the map-background endpoint-selection handler.
When an info window is open, the first background click closes it and is consumed;
subsequent background clicks retain the existing endpoint-selection behavior.
Keyboard focus must reach links and controls normally. On touch devices, tap
opens the same info window because hover is unavailable.

## Lock marker placement

Lock chevrons are centered on the canal at the lock location. The route response
uses the source lock gate/chamber coordinate when available and projects it onto
the attached route edge. A source point within 25 m of that edge is considered
source-confirmed and is emitted with `approximate=false` after projection. A
source point farther than 25 m, malformed source data, or a missing source point
uses the lock-bearing edge midpoint and emits `approximate=true`.

The map adapter uses a center-centered marker anchor; the chevron must not behave
like a pin whose tip sits below the canal. The lock info window displays the lock
name, route day, and whether its position is approximate. The chevron remains
upright for consistent recognition rather than rotating with canal direction.

## Google enrichment spike

The OSM-only catalog and info windows are the first usable release. A separate
spike compares, for representative pubs and attractions:

1. generated Google Maps search links using name and coordinates;
2. an explicit Google text/nearby search matching step followed by on-demand Place
   Details with a narrow field mask.

The spike records match thresholds, ambiguous/no-match behavior, website
availability, latency, billing/quotas, mobile behavior, attribution/terms,
privacy implications, and the execution surface. It must not scrape consumer
pages or persist Google-derived place data during ingest. Any temporary match
logging is minimized and discarded. A production Google integration is added
only after this evidence-based comparison.

## Runtime degradation

The catalog path is an optional independent web setting. If the catalog is
missing or invalid, the application remains able to load the routing artifact and
serve route planning; health reports `catalog_status: unavailable`, and catalog
requests return a structured 503 `catalog_unavailable` error. The frontend hides
or disables catalog layers while leaving route planning, locks, and day overlays
usable. There is no silent fallback from the catalog endpoint to legacy POIs.

If the routing artifact is unavailable, existing startup failure behavior remains
unchanged. Catalog and routing revisions/status are reported independently by
health/capability metadata.

## Delivery phases

### Phase 1: OSM metadata and taxonomy inventory

Scan the original England PBF for relevant user-facing and candidate attraction
tags. Produce the exact kind manifest, metadata validators, geometry policy,
coverage counts by kind, duplicate/inactive handling, URL policy, OSM attribution
requirements, and measured catalog build/index resource budget.

### Phase 2: Nationwide catalog

Add a dedicated source reader, catalog record model, geometry normalizer,
artifact validator, build command, independent revision, and spatial indexes.
Do not reuse graph-bound `PointOfInterest`, graph attachment fields, or the
filtered waterway PBF. Add API tests for independent revisions, degraded startup,
kind queries, mixed-policy separation, locality queries, route/day distances,
and hard query budgets.

### Phase 3: Map UX

Add opt-in kind/group layers backed by the catalog endpoint, distinct glyphs,
hover tooltips, one adapter-owned persistent info window, conditional OSM
metadata links, background-click arbitration, and centered lock chevrons while
preserving existing route/day overlays.

### Phase 4: Google spike

Run the search-link versus matched on-demand Place Details comparison and record
the chosen follow-up, if any.

## Error handling

- Invalid or unknown kinds return the existing structured API error shape.
- Invalid bounds, revisions, geometry, or excessive query budgets are rejected.
- Over-cap results are a normal bounded-query state; the response does not send
  an arbitrary partial catalog.
- Catalog failures leave route planning and existing route overlays usable.
- A failed optional Google lookup never blocks OSM marker rendering; Google
  failure behavior belongs to the follow-up design rather than this release's
  acceptance criteria.
- Missing or malformed OSM metadata is omitted rather than shown as placeholder
  content.
- Stale routing and catalog revisions use independent structured mismatch errors.

## Testing and acceptance

### Ingestion and catalog

- Metadata normalization preserves validated fields and omits excluded/noisy
  fields.
- The inventory manifest identifies final field availability by kind.
- Node, linear-way, area-way, multipolygon, malformed-geometry, duplicate,
  inactive/disused, and representative-point cases are covered.
- Catalog artifacts reload successfully and retain OSM identity/provenance.
- Routing and catalog artifacts can be rebuilt independently and report separate
  revisions.
- Missing/corrupt catalogs leave routing startup and health behavior explicit.
- Queries filter by kind and bounds and return bounded, deterministic results.
- Mixed kinds use separate explicit policies; route, selected-day, waterway, and
  locality distance semantics are tested at exact boundaries.
- Maximum bounds, kind count, radius, geometry vertices, response cap, query
  latency, startup time, artifact size, and build memory are measured against the
  Phase 1 budget.
- Route and waterway distance calculations use the existing metric spatial
  helpers.
- URL scheme rejection, field-length limits, safe link construction, and safe
  rendering are tested.

### Frontend

- Kind-layer selection sends only selected kinds and does not request empty
  selections.
- Marker replacement and cleanup do not leak stale overlays or listeners.
- Tooltips contain only lightweight name/kind content.
- One shared info window switches correctly between POIs and locks, persists on
  click, closes via Escape/explicit close/background-click arbitration, and
  exposes keyboard-accessible links.
- Marker clicks do not trigger endpoint selection; normal background clicks still
  select endpoints after the consumed close click.
- Touch interaction opens the same info window.
- Lock chevrons use center anchoring, source projection tolerance, and approximate
  fallback state.
- OSM metadata omissions do not break the map.

Manual acceptance uses representative pubs, shops, marinas, and attractions near
a planned route, plus a locality-sized query. It verifies readable glyphs,
correct route/waterway distances, centered lock markers, useful OSM links, and
usable desktop/mobile interaction.
