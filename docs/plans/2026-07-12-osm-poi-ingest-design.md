# OSM POI Ingest and Spatial Lookup Design

> **Status:** validated design
> **Builds on:** noded waterway graph, artifact revisions, and local map UI
> **Scope:** offline OSM POI ingestion and spatial lookup foundation; remote deployment deferred

## 1. Goal

Extend both OSM ingest paths so a freshly built routing artifact contains a deterministic,
validated collection of canal-relevant points. The same collection will later support route
amenities and practical canal-access scoring. This round does not add amenity UI, route-result
enrichment, or land routing.

The build must ingest tagged OSM nodes and tagged area ways/relations, normalize them through one
classification policy, retain only features close enough to navigable waterways, and attach each
retained feature to the waterway graph without changing graph topology.

## 2. Decisions

- Use one source-neutral POI model and one pure tag classifier for Overpass and bulk PBF input.
- Treat POIs as artifact data, never as routable NetworkX nodes.
- Import tagged nodes plus tagged area ways and multipolygon relations.
- Use Shapely for geometry/indexing and pyproj for WGS84/British National Grid transforms.
- Use a 250 m waterway corridor for canal services and pedestrian-access signals.
- Use a 1,000 m corridor for provisions and public transport.
- Do not import parking.
- Preserve pedestrian restriction signals, but do not build a pedestrian routing network.
- Keep route endpoints as existing graph-node UIDs. Mid-edge route starts are deferred.
- Replace the current artifact tuple with a structurally validated `GraphArtifact` containing
  `graph`, `pois`, and `metadata`.
- Do not add format-version fields. Invalid or stale artifacts fail loudly and must be rebuilt.
- Retain `artifact_revision`; it identifies a particular build and protects node handles.

## 3. Taxonomy and OSM Allowlist

Every retained record has a broad `category` and a stable `kind`.

| Category | Radius | Kinds and primary OSM tags |
|---|---:|---|
| `canal_service` | 250 m | `water_point`: `amenity=drinking_water` or `waterway=water_point`; `sanitary_disposal`: `amenity=sanitary_dump_station` or `waterway=sanitary_station`; `toilets`: `amenity=toilets`; `shower`: `amenity=shower`; `fuel`: `amenity=fuel` or `waterway=fuel`; `marina`: `leisure=marina`; `mooring`: `mooring=*` except explicit `no` |
| `provisions` | 1,000 m | `pub`, `cafe`, `restaurant` from `amenity=*`; `supermarket`, `convenience`, `bakery`, `greengrocer`, `butcher`, `deli`, `general` from `shop=*` |
| `transport` | 1,000 m | `rail_station`: `railway=station`; `rail_halt`: `railway=halt`; `bus_stop`: `highway=bus_stop`, `public_transport=platform`, or `public_transport=stop_position` with bus evidence; `taxi_rank`: `amenity=taxi` |
| `pedestrian_access` | 250 m | `entrance`: public/permissive `entrance=*`; `path_connection`: nearest canal-side point derived from `highway=footway/path/pedestrian`; `pedestrian_bridge`: eligible path with bridge evidence; `steps`: `highway=steps`; `gate`, `stile`, `kissing_gate`, `cycle_barrier`: matching `barrier=*` |

The classifier uses an explicit allowlist. Unknown `amenity`, `shop`, `railway`, `waterway`, or
`barrier` values are skipped and counted by source tag/value. Parking tags are ignored.

Selected operational properties are normalized from `access`, `foot`, `wheelchair`,
`opening_hours`, `fee`, `operator`, `brand`, `drinking_water`, and `toilets`. The normalized record
also preserves a filtered `source_tags` mapping containing these fields and the tag(s) responsible
for classification. It does not copy arbitrary OSM tags into the artifact.

## 4. Data Contracts

Add source-neutral models under `pound/ingest/ir.py`:

```python
class PoiCategory(StrEnum):
    CANAL_SERVICE = "canal_service"
    PROVISIONS = "provisions"
    TRANSPORT = "transport"
    PEDESTRIAN_ACCESS = "pedestrian_access"


class OsmElementType(StrEnum):
    NODE = "node"
    WAY = "way"
    RELATION = "relation"


class PoiCandidate(BaseModel):
    osm_type: OsmElementType
    osm_id: int
    category: PoiCategory
    kind: str
    name: str | None
    tags: dict[str, str]
    geometry_wkt: str
    geometry_source: Literal["point", "area", "derived_path"]


class PointOfInterest(BaseModel):
    osm_type: OsmElementType
    osm_id: int
    category: PoiCategory
    kind: str
    name: str | None
    lat: float
    lon: float
    source_tags: dict[str, str]
    geometry_source: Literal["point", "area", "derived_path"]
    nearest_waterway_distance_m: float = Field(ge=0)
    nearest_edge: tuple[int, int]
    nearest_node_uid: int
    projected_lat: float
    projected_lon: float
```

`WaterwayFeatures` gains `poi_candidates: list[PoiCandidate]`. Candidate geometry is build-time IR;
only `PointOfInterest` records enter the artifact. Identity is `(osm_type, osm_id, kind)`, allowing
one OSM feature to expose two genuinely different services while deterministically removing reader
or query duplicates.

`GraphArtifact` is a frozen dataclass with `graph: nx.Graph`, `pois: tuple[PointOfInterest, ...]`,
and `metadata: dict[str, object]`. `load_artifact()` returns this container rather than a tuple.

## 5. Geometry and Data Flow

```text
OSM PBF / Overpass JSON
  -> tag prefilter
  -> waterway IR + raw POI geometry
  -> shared classification and tag normalization
  -> Shapely geometry repair/representative point
  -> navigable-edge STRtree
  -> exact corridor filter and graph attachment
  -> GraphArtifact(graph, pois, metadata)
  -> startup node/edge spatial indexes
```

Bulk ingest uses pyosmium area assembly for closed ways and multipolygon relations. Overpass parsing
accepts node coordinates, way geometry, and relation-member geometry. Both paths construct Shapely
points, lines, or polygons and pass them through the same normalization function. Invalid geometry
gets one `make_valid()` attempt; empty or still-unusable geometry is skipped and reported.

Area distance is measured from full geometry. Its displayed coordinate comes from
`representative_point()`, which lies inside the repaired polygon. A path-derived access feature uses
the closest point on the path to the navigable waterway. For every candidate, an STRtree finds
nearby navigable edge `LineString`s; exact distance is calculated in British National Grid
(EPSG:27700) through an always-XY pyproj transformer, not in longitude/latitude degrees. The winning edge
is selected by `(distance, min_uid, max_uid)`. The nearest endpoint UID then uses `(distance, uid)`.

The stored projected coordinate is the closest point on the winning waterway edge. It is informative
attachment data only; current route APIs continue to accept graph-node UIDs.

## 6. Runtime Spatial Lookup

Introduce an immutable `GraphSpatialIndex` built once when an artifact is loaded. It owns:

- an STRtree of graph-node points for nearest candidate UIDs;
- an STRtree of navigable edge lines for projected canal points and later access scoring;
- deterministic mappings from returned geometries to graph UIDs/edge keys.

`nearest_coord_candidates()` accepts the node index and uses it to obtain the requested nearest
nodes. It preserves the current output contract, haversine distances, display-name behavior, and
`(distance, uid)` ordering. Tests compare indexed results with exhaustive search over fixture and
randomized graphs. `resolve_coord()` may reuse the same node-index primitive so the repository does
not maintain two nearest-node implementations.

Do not route from the closest point on an edge. Correct mid-edge routing requires request-scoped
virtual nodes or edge splitting and a separate design.

## 7. Artifact Validation and Failure Handling

The serialized pickle must contain exactly `graph`, `pois`, and `metadata`. Loading validates:

- `graph` is an undirected NetworkX graph with the required node and edge attributes;
- `pois` is a list/tuple and every item parses as `PointOfInterest`;
- metadata contains `artifact_revision`, `source`, `fetched_at`, `built_at`, `validation`, and
  `poi_summary`;
- POI identities are unique and coordinates are finite and within WGS84 bounds;
- attachment UIDs and edges exist;
- stored distances are nonnegative and do not exceed the category threshold;
- projected points are consistent with the attached edge within a documented numeric tolerance.

Any structural error raises `InvalidArtifactError` with field-level details and a rebuild instruction.
There is no legacy fallback or migration. Pickles remain trusted local build products and must never
be loaded from untrusted sources.

Build-fatal errors include duplicate normalized identities after deduplication, invalid graph
references, and inconsistent computed distances. Individual malformed OSM geometries, incomplete
relations, and unknown tag values are skipped with counters and representative examples. The CLI
prints POI totals by category/kind plus skipped/rejected counts. The metadata records the same
summary so external review and later diagnostics can inspect the artifact provenance.

## 8. Testing and Acceptance Criteria

Default tests remain offline. Add fixtures that cover every kind, nodes and areas, a concave polygon,
a multipolygon relation, duplicate source elements, threshold boundaries, private access, steps,
barriers, malformed geometry, and unknown values.

Acceptance criteria:

1. Overpass and pyosmium fixtures normalize equivalent OSM features to equivalent candidates.
2. All allowlisted kinds are classified; unknown kinds and parking are excluded and reported.
3. Area representative points lie inside valid polygons, while corridor distance uses full geometry.
4. Canal-service and pedestrian-access records are retained through 250 m; provisions and transport
   are retained through 1,000 m; records beyond the boundary are excluded.
5. Every stored POI has deterministic identity, nearest edge/node, projected canal coordinate, and
   source provenance.
6. A new artifact passes strict structural validation; stale artifacts fail with rebuild guidance.
7. Indexed nearest-node candidates exactly match exhaustive results and do not mutate the graph.
8. Default tests and Ruff pass; bulk tests pass with the bulk extra and osmium-tool installed.
9. An opt-in England build reports category counts and completes without quadratic POI-edge scans.

## 9. Deferred Work

- UI markers, filters, amenity panels, and route-result enrichment
- POI-aware canal access scoring and candidate ranking
- virtual nodes and arbitrary mid-edge routing
- complete pedestrian routing and accessibility claims
- opening-hours evaluation or live availability
- CRT, hire-company, or other non-OSM sources
- remote deployment and production infrastructure

## 10. Baseline Note

On 2026-07-12, the isolated planning worktree collected 307 tests. All tests executed through 79%
passed with expected skips; the run then stopped producing output in the web subset and was manually
interrupted. The Snap-installed `uv` could not run because `snap-confine` lacked `cap_dac_override`,
so the repository virtual environment was used. Implementation should rerun focused web tests first
and use `superpowers:systematic-debugging` if the stall reproduces.
