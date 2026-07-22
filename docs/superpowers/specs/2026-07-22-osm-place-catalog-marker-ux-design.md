# OSM Place Catalog and Marker UX

## Status

Approved design for implementation planning.

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

Transport and pedestrian-access infrastructure are excluded. Google Maps is the
native surface for transport information.

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

Build a separate OSM place-catalog artifact and spatial index from the England
PBF. Keep the existing routing graph artifact focused on graph and route data;
the catalog must not make route planning depend on marker presentation.

A catalog record contains the OSM identity, stable kind/category, coordinates,
normalized user-facing metadata, and source provenance. The catalog loader builds
an immutable spatial index for bounded viewport, route, and locality queries.

The route map requests selected kinds, viewport bounds, and optional route/day
geometry. The backend performs the spatial index work and returns bounded results
with distance information. Future locality/chat clients can reuse the catalog
with a locality bounding box or equivalent place-resolution result.

The backend owns canonical kind validation, spatial indexing, bounds validation,
maximum radius/result limits, artifact validation, and efficient query execution.
The frontend owns kind grouping, default visibility, proximity policy selection,
and marker presentation. This keeps display policy easy to change without
allowing unbounded catalog downloads or duplicating spatial-query logic in every
client.

## Metadata contract

The frontend receives normalized, user-facing fields rather than arbitrary
`source_tags`. The inventory spike measures coverage by kind and determines the
final allowlist.

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

OSM object URLs can be derived from the stored element type and ID. External URLs
must be restricted to validated web links before being returned to the browser.
OSM attribution and provenance remain visible wherever OSM-derived data is shown.

## Query contract

The frontend queries the catalog primarily by `kind`. A request includes:

- selected kinds;
- viewport bounds;
- optional route/day geometry;
- optional frontend-selected proximity limit.

The response includes each record's normalized metadata plus:

- `waterway_distance_m`, when available;
- `distance_to_route_m`, when route geometry is supplied;
- the selected kind and source identity;
- bounded-result status when the request exceeds the server cap.

The frontend can therefore implement different policies for utilities and
destinations without requiring separate catalog artifacts. The backend validates
kinds and caps the allowable query/radius/result size. Empty kind selections do
not request catalog data.

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

Click opens one persistent info window containing available fields:

- name and kind;
- distance to route;
- distance to waterway;
- lock day where relevant;
- opening hours, accessibility, and fee information;
- OSM, website, Wikipedia, or other validated links.

Absent fields are omitted. Clicking elsewhere or pressing Escape closes the
window. Keyboard focus must reach links and controls normally. On touch devices,
tap opens the same info window because hover is unavailable.

## Lock marker placement

Lock chevrons are centered on the canal at the lock location. The route response
uses the source lock gate/chamber coordinate when available and validates or snaps
it to the route geometry. If no source coordinate is available, it uses the
lock-bearing edge midpoint and marks the record `approximate`.

The map adapter uses a center-centered marker anchor; the chevron must not behave
like a pin whose tip sits below the canal. The lock info window displays the lock
name, route day, and whether its position is approximate. The chevron remains
upright for consistent recognition rather than rotating with canal direction.

## Google enrichment spike

The OSM-only catalog and info windows are the first usable release. A separate
spike compares, for representative pubs and attractions:

1. generated Google Maps search links using name and coordinates;
2. on-demand Google Places Details lookup.

The spike records match accuracy, website availability, latency, billing/quotas,
mobile behavior, attribution/terms, and privacy implications. It must not scrape
consumer pages or persist Google-derived place data during ingest. A production
Google integration is added only after this evidence-based comparison.

## Delivery phases

### Phase 1: OSM metadata inventory

Scan relevant source objects and candidate attraction tags, measure field coverage
by kind, choose the normalized allowlist, and document exclusions, attribution,
and provenance requirements.

### Phase 2: Nationwide catalog

Build and load the separate England catalog artifact, ingest all approved kinds,
construct spatial indexes, and expose bounded kind-based API queries.

### Phase 3: Map UX

Add opt-in kind/group layers, distinct glyphs, hover tooltips, persistent info
windows, conditional OSM metadata links, and centered lock chevrons while
preserving existing route/day overlays.

### Phase 4: Google spike

Run the search-link versus on-demand Place Details comparison and record the
chosen follow-up, if any.

## Error handling

- Invalid or unknown kinds return the existing structured API error shape.
- Invalid bounds or excessive query radii are rejected.
- Over-cap results are a normal bounded-query state; the response does not send
  an arbitrary partial catalog.
- Catalog failures leave route planning and existing route overlays usable.
- A failed optional Google lookup never blocks OSM marker rendering.
- Missing or malformed OSM metadata is omitted rather than shown as placeholder
  content.
- Stale artifact revisions use the existing revision-mismatch behavior.

## Testing and acceptance

### Ingestion and catalog

- Metadata normalization preserves validated fields and omits excluded/noisy
  fields.
- Coverage reports identify final field availability by kind.
- Catalog artifacts reload successfully and retain OSM identity/provenance.
- Queries filter by kind and bounds and return bounded, deterministic results.
- Route and waterway distance calculations use the existing metric spatial
  helpers.

### Frontend

- Kind-layer selection sends only selected kinds and does not request empty
  selections.
- Marker replacement and cleanup do not leak stale overlays.
- Tooltips contain only lightweight name/kind content.
- Info windows persist on click, close correctly, and expose keyboard-accessible
  links.
- Touch interaction opens the same info window.
- Lock chevrons use center anchoring and display approximate fallback state.
- OSM metadata omissions and optional Google failures do not break the map.

Manual acceptance uses representative pubs, shops, marinas, and attractions near
a planned route, plus a locality-sized query. It verifies readable glyphs,
correct route/waterway distances, centered lock markers, useful OSM links, and
usable desktop/mobile interaction.
