# Boat-hire network overlay design

- **Date:** 2026-08-13
- **Status:** Approved design
- **Scope:** Resolve curated England hire-base coordinates, then restrict only the startup map overlay to graph components that contain a qualifying base.

## Goal

Show only the England routing-network connected components that contain at least one
curated non-excluded boat-hire base. The routing graph, candidate lookup, and route APIs
remain complete and unchanged. The editable enrichment CSV is the source of the
base seeds.

## Data contract

`pound/data/boat-hire-enrichment.csv` gains an `exclude` column. Its only allowed
CSV values are `true`, `false`, and blank:

- `true`: retain the base but exclude it from the current display, including Wales
  and Scotland until the production graph covers that geography.
- `false` or blank: include the base as an overlay seed.

Every non-excluded row qualifies regardless of `record_type` or `enrichment_status`.
Those fields remain provenance, not overlay eligibility. The existing
`(source_provider_id, location_id)` pair is the unique row identity, so different
providers may retain rows for the same physical base. Every non-excluded row must
have both finite WGS84 coordinates (latitude from -90 through 90; longitude from
-180 through 180) and one HTTPS location-evidence URL before deployment:

1. Prefer a reliable OSM match and record its URL and coordinates in `osm_url`.
2. If OSM has no reliable feature, accept an official provider-location page that
   confirms the base/address and record it in `evidence_url`.
3. Do not guess. Ambiguous or unsupported locations are reported for manual
   resolution and block deployment until resolved.

Excluded rows remain in the CSV but do not require coordinates, evidence, or graph
snapping and never seed the England overlay.

The web application receives the CSV via the required
`POUND_BOAT_HIRE_ENRICHMENT_PATH` setting. There is no repository-relative fallback.

## Startup overlay selection

At application startup, after loading the full, validated undirected graph:

1. Parse and validate the CSV.
2. For every non-excluded row, use the existing `GraphSpatialIndex.project_to_nearest_edge`
   to find the nearest routing-eligible edge.
3. Require the metric edge distance to be at most the inclusive 250 m threshold.
   A farther base is a startup error rather than a silently omitted seed.
4. Use `networkx.connected_components` on the undirected graph. Each snapped edge
   selects the component containing either endpoint.
5. Pass a node-induced subgraph containing all selected components to the existing
   `prepare_network_geometry` function. Filtering happens before geometry union,
   merge, and simplification so component identity is preserved until selection.

The full graph and full spatial indexes remain on application state for routes,
location candidates, POIs, and catalog requests. Only `network_lines` is filtered.
There is no client-side filtering and no API schema change.

## Failures and empty results

Missing CSV configuration, an unreadable/invalid CSV, an unsupported coverage
`exclude` value, a duplicate `(source_provider_id, location_id)`, missing or malformed
non-excluded coordinates, missing non-excluded location evidence, or a non-excluded
base farther than 250 m from a routing-eligible edge fails startup. Silent fallback
to the full overlay is never allowed.

If valid non-excluded data selects zero graph components, routing still starts normally,
but `/api/canal-network` reports the existing `503 network_unavailable` response.
The frontend keeps its existing nonfatal overlay-error behavior.

## Coordinate-resolution delivery gate

Before the overlay filter is deployed, resolve all currently missing non-excluded
coordinates through catalog/OSM matching and official-provider evidence. Live web
research may corroborate evidence but Google or map search results alone are not
proof. Stop and produce a compact unresolved list for manual decisions rather than
committing guessed locations.

## Testing

Add focused checks for:

- CSV schema and the exact allowed `exclude` values.
- Complete valid/evidenced coordinates for each non-excluded row; excluded rows are
  ignored by seed validation.
- Exact 250 m acceptance and just-over-threshold rejection.
- Two edge-bearing disconnected graph components where a base near one produces
  overlay geometry only for that component while the full graph still routes across
  its original component.
- Invalid seed data failing startup and valid zero-component selection returning the
  existing overlay 503 without breaking route endpoints.

Run targeted tests, the full Python suite, Ruff, lock validation, and diff checks.

## Non-goals

- No graph-artifact pruning or rebuild caused by CSV edits.
- No changes to route, candidate, POI, or catalog scope.
- No frontend contract, dynamic component toggle, live request-time enrichment
  lookup, or website fetching in the application.
- No Wales or Scotland overlay until a corresponding supported graph is deployed.
