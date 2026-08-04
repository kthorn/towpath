# OSM Attraction Catalog Query Completion

## Status

Approved design for implementation of GitHub issue #23.

## Goal

Complete the durable OSM visitor-attraction catalog contract without coupling the catalog artifact to ephemeral routing node handles or commercial-provider data.

## Scope

This change remains OSM-only. It completes the existing independent catalog and bounded query API with:

- explicit catalog schema-version validation;
- bounded text search over normalized names;
- public-geometry canal-segment proximity queries;
- deterministic distance and identity ordering;
- regression coverage for source geometry, 2 km boundaries, malformed records, query limits, and artifact compatibility.

The catalog remains broad at ingest time. The existing query-time waterway policy applies the configurable 2 km geometric proximity filter, matching the approved catalog architecture. OSM source identity, object links, source date, and attribution remain the durable provenance surface. Commercial provider fields and additional source adapters are out of scope.

Clustering/detail-card discovery (#26), route-leg/day presentation (#24), and live provider enrichment (#28) remain separate issues.

## Architecture

`CatalogArtifact` stays independent from the routing artifact. The catalog reader continues to normalize named, active OSM nodes, ways, and relations into normalized geometry. `CatalogSpatialIndex` performs request-scoped metric distance calculations using the loaded graph's existing `GraphSpatialIndex`; it does not persist graph node handles or add a second graph-coupled artifact.

Catalog revisions identify a particular artifact build. A separate integer `catalog_schema_version` (value `2` for this contract) identifies the serialized contract. The loader rejects artifacts with missing or incompatible schema versions so a stale catalog cannot be treated as current data. Existing catalog artifacts must be rebuilt after this change.

Segment queries accept bounded GeoJSON line geometry and use a new `segment` query policy. This gives callers a stable public geometry contract while avoiding a dependency on internal graph UIDs.

## Query contract

`CatalogPlacesRequest` gains:

- `text`: optional, bounded text normalized with Unicode `casefold`; matches the normalized primary name or alternate name by substring. Empty or whitespace-only text means no text filter;
- `segment_geometry`: optional bounded `GeoJSONLineString` used when policy basis is `segment`.

`CatalogQueryPolicyModel.basis` gains `segment`. Segment policy requires `segment_geometry` and a radius; non-segment policies reject segment geometry. The existing viewport, category, route, waterway, radius, geometry, work-budget, and response-cap validation remains in force.

`CatalogPlaceResponse` gains `distance_to_segment_m`, populated only for a segment query. Results are ordered by the active proximity distance when one exists, then by kind and OSM identity. Unbounded queries use kind and identity ordering. Over-cap requests preserve the existing sentinel response rather than returning an arbitrary partial result.

Invalid text, geometry, or policy combinations use the existing structured `invalid_catalog_query` response. No-waterway and no-segment matches return an empty result for bounded policies. Route planning remains available if the catalog is unavailable or an artifact fails schema validation.

## Artifact metadata and provenance

The artifact metadata contract adds `catalog_schema_version` and `attribution`, whose value is exactly `© OpenStreetMap contributors`. `catalog_revision` remains independent and build-specific. `source`, `fetched_at`, `built_at`, inventory summaries, build summaries, OSM element identities, and normalized OSM links remain available. Rejected inactive, unnamed, duplicate, and malformed records remain represented in build diagnostics; no uncertain commercial match is introduced.

## Testing

Tests will cover:

- catalog metadata schema version and attribution round trips;
- rejection of missing, wrong, or unsupported schema versions;
- text matching, casefolding, alternate names, empty text, and deterministic ordering;
- segment distance, exact radius boundaries, invalid/oversized geometry, and no-match behavior;
- existing waterway/route behavior and 1,000-record/work-budget caps;
- node, way, and relation fixture geometries, duplicate/unnamed/malformed records, OSM identity links, and absence of commercial fields;
- API serialization and structured validation errors;
- TypeScript request/response contract compatibility.

Verification uses the narrow catalog, schema, ingest, and web API suites, followed by the default Python and frontend test/lint/check commands.
