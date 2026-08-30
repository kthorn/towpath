# Compact Routing Artifact and Build/Runtime Separation

**Status:** Approved design; pending refinement

## 1. Context

Pound currently builds and deploys one Python distribution containing OSM ingest, graph construction,
validation, routing, review tooling, and the FastAPI website. The production routing artifact contains
a fully noded NetworkX graph and graph-coupled POI attachment data. Runtime startup unpickles that
artifact, deeply revalidates it, and builds spatial indexes.

A probe against `pound/artifacts/england.pkl` measured:

| Signal | Current artifact |
|---|---:|
| Artifact size | 319,013,542 bytes |
| Graph nodes | 691,564 |
| Graph edges | 691,117 |
| Runtime POIs | 523,636 |
| Raw unpickle | 10.3 seconds |
| Graph validation | 4.0 seconds |
| POI parsing | 7.7 seconds |
| POI attachment validation | 22.6 seconds |
| Graph spatial-index construction | 44.4 seconds |
| POI spatial-index construction | 5.2 seconds |
| Peak RSS while loading and indexing | about 3.67 GiB |

The graph is detailed because `pound.graph.build.build_graph` retains every OSM node along a routable
way as a NetworkX node and emits every consecutive pair as an edge. Of the deployed graph's nodes,
682,271 have degree two. A conservative probe that preserved topology and every runtime edge-attribute
boundary found 665,042 contractible nodes. It produced a throwaway graph with 27,028 nodes and 26,581
edges. Simplifying the contracted edge geometry with a one-metre metric tolerance retained 526,440
coordinates. The graph-only pickle fell from 154 MB to 19 MB, and `GraphSpatialIndex` construction fell
from 44.4 seconds to 1.8 seconds on the same machine.

The current public route flow also exposes graph node UIDs. `/api/canal-candidates` finds graph nodes,
the browser ranks those points with Google land-transfer results, and `/api/canal-route` routes between
the selected node handles. Retaining dense graph nodes solely to provide candidate points prevents the
routing topology from being simplified.

## 2. Goals

1. Keep stored routing-edge geometry and route-response geometry within one metre of the accepted
   source geometry.
2. Separate routing topology from the density of selectable canal access points.
3. Route between selected projected positions anywhere along candidate-eligible polylines without
   mutating the shared graph.
4. Remove build-only graph attachments and deep validation from website startup.
5. Enforce a package and deployment boundary between offline build machinery and the website.
6. Preserve topology, route availability, boat restrictions, infrastructure costs, warnings, lock
   reporting, and deterministic results.
7. Measure artifact size, startup time, and peak memory before and after the change without making a
   fixed percentage improvement a release gate.

## 3. Non-goals

- Direct-coordinate HTTP routing. Public HTTP routing continues to require the candidate-selection
  workflow.
- Persisting or serializing a Shapely `STRtree`.
- Changing the 250-metre candidate sampling interval at runtime.
- Replacing trusted local pickle with a public or untrusted interchange format.
- Changing the land-transfer provider, ranking policy, boat cost model, or route-day allocation policy.
- Applying the one-metre routing bound to the separate whole-network overview overlay. Its existing
  response-size simplification remains presentation-only and is never used for snapping or routing.
- Correcting source topology or bridging genuine gaps in OSM data.
- Making the three Python distributions independently released products. They remain one repository and
  one coordinated workspace.

## 4. Workspace and package architecture

The repository becomes a root `uv` workspace containing three Python distributions and the existing
TypeScript frontend:

```text
packages/
  pound-core/
    pyproject.toml
    src/pound/
    tests/
  pound-build/
    pyproject.toml
    src/pound_build/
    tests/
  pound-web/
    pyproject.toml
    src/pound_web/
    tests/
web/
integration-tests/
pyproject.toml
uv.lock
```

The dependency direction is:

```text
pound-build ──> pound-core <── pound-web
```

`pound-core` must not import `pound_build` or `pound_web`. `pound-web` must not import `pound_build`.
The build package may depend on core's artifact models and routing semantics so the producer validates
exactly the contract the consumer uses.

### 4.1 `pound-core`

The existing `pound` import namespace moves to the core distribution to minimize churn. Core owns:

- the compact artifact contract and trusted loader;
- runtime graph, edge, POI, and projected-point models;
- route eligibility and traversal costs;
- partial-edge route planning and geometry assembly;
- graph, POI, and fixed candidate spatial indexes;
- runtime catalog models, catalog loading, and catalog queries;
- shared API-neutral response models used by the server and runtime CLIs;
- `pound-plan` and `pound-locate` diagnostic CLIs, adapted to core's projected-position primitives.

Core dependencies are limited to libraries required for artifact loading, routing, and geometry, such as
NetworkX, Pydantic, PyProj, and Shapely. It has no FastAPI, Flask, Requests, or Osmium dependency.

Every Python object embedded in a pickle has a durable module path owned by core. `WaterwayKind`,
`WayDimensions`, `AccessCaveat`, `OsmElementType`, catalog runtime models, and the compact runtime POI
record move to explicit `pound` model modules and are imported by the builder from there. Build-only
objects such as `WaterwayFeatures`, `WaterwayWay`, `WaterwayNode`, `PoiCandidate`, and ingest reports
live only under `pound_build` and must never appear in an artifact. No compatibility re-export from
`pound.ingest.ir` is retained because old routing artifacts are intentionally unsupported.

Pure helpers currently imported by runtime from build modules also move into core: haversine distance and
coordinate normalization from `pound.graph.build`, edge eligibility and line construction from
`pound.graph.pois`, lock-point projection from `pound.graph.locks`, and retained runtime POI-kind constants
from `pound.ingest.pois`. The package-boundary tests enforce this list as well as the general dependency
rule.

### 4.2 `pound-build`

The build distribution owns:

- OSM/Overpass/PBF readers and ingest intermediate models;
- navigability filtering and source normalization;
- detailed graph construction, lock and bridge attachment, and gazetteer construction;
- POI discovery and offline attachment;
- graph contraction and metric geometry simplification;
- complete graph, geometry, POI, and metadata validation;
- artifact and catalog writing;
- build profiling, diagnostics, comparison, and review tooling;
- `pound-ingest` and build/review command entry points.

Requests, Flask, and optional Osmium dependencies live here rather than in the production website
installation.

### 4.3 `pound-web`

The website distribution owns:

- FastAPI application construction and lifespan;
- HTTP request and response models;
- API handlers and error envelopes;
- runtime settings and deployment entry points;
- boat-hire, places, and network-overlay orchestration specific to the website.

It depends on `pound-core` for all artifact, routing, and spatial behavior. The existing TypeScript
`web/` package remains separate and consumes the HTTP API.

### 4.4 Deployment boundary

The production image installs only `pound-web` and its transitive `pound-core` dependency. Its Python
stage copies the root workspace metadata plus only `packages/pound-core` and `packages/pound-web`, then
runs a locked `uv sync --package pound-web --no-dev`. Validated runtime artifacts and curated runtime data
are staged under `/app/artifacts` and `/app/data`; they are copied separately and are not package source.
The image does not copy or install `pound-build`, source PBF data, build diagnostics, or review tooling.
A clean-image test must prove that `pound_build`, Requests, Flask, and Osmium cannot be imported.

## 5. Offline graph compaction

The detailed noded graph remains a transient build representation. It is necessary to recover shared
OSM junctions and attach source infrastructure correctly, but it is not the deployed routing model.
Compaction runs only after source attachment and before final validation and serialization.

### 5.1 Protected nodes and boundaries

A node is retained when any of the following applies:

- its degree is not two;
- it has a runtime name or discrete node-level infrastructure, including any non-empty node
  `movable_bridge_ids`;
- its two incident edges differ in any runtime-consumed attribute;
- it bounds a lock or movable-bridge edge;
- contracting it would create a self-loop or a second edge between the same endpoint pair in the
  simple `nx.Graph` representation.

Runtime-consumed edge boundaries include OSM way identity, display name, waterway kind, boat
dimensions, tunnel state and restrictions, movable-bridge state and identity, lock count and points,
and access caveats. Preserving OSM way boundaries keeps existing warning and provenance semantics and
avoids inventing aggregate edge identities.

When two maximal chains would contract to the same endpoint pair, one chain may use the direct edge and
each additional chain retains one deterministic internal anchor. The compact artifact remains an
undirected, non-multi NetworkX graph.

### 5.2 Chain contraction

Each maximal unprotected degree-two chain becomes one edge. The edge geometry is assembled from the
source segments and stored in canonical low-UID to high-UID order. `length_m` is the sum of source
segment lengths and remains the routing and reporting authority. It is not recomputed from simplified
geometry.

Build-only node fields such as `osm_node_ids` are discarded after contraction. Runtime nodes retain only
coordinates, optional names, and runtime infrastructure state.

### 5.3 One-metre geometry bound

Geometry is transformed to British National Grid (`EPSG:27700`) and simplified with a one-metre
Douglas-Peucker tolerance. It is transformed back to WGS84 for storage. The build validates both the
source-to-result and result-to-source metric deviation and rejects any edge whose measured deviation
exceeds one metre, whose endpoints move, or whose result is empty or invalid.

Junction coordinates and protected infrastructure boundaries are edge endpoints and therefore cannot
be removed by line simplification. Routing costs continue to use summed source length, so visual
simplification does not shorten the journey model.

### 5.4 Discrete infrastructure

Locks and movable bridges carry discrete costs. Their edges remain bounded so no contraction smears a
discrete event across unrelated waterway geometry. Candidate generation excludes the interior of edges
with lock or movable-bridge costs. A projected public endpoint therefore cannot begin ambiguously on one
side of a discrete event while being charged for the other side. Such edges remain traversable as part
of an ordinary route.

Tunnel and access restrictions remain edge attributes and boundaries. A partial endpoint edge is
eligible only when the whole edge is eligible for the supplied boat constraints.

## 6. Runtime POI records

Offline POI attachment remains part of `pound-build`: it determines navigability, source-to-waterway
distance, acceptance, deduplication, and diagnostics before publication. The deployed POI record keeps
only fields used by website queries:

- OSM type and ID;
- category and kind;
- optional display name;
- display latitude and longitude.

It does not serialize `nearest_edge`, `nearest_node_uid`, projected attachment coordinates, source tags,
or other build diagnostics. Those values remain available in build reports when needed but are not part
of the runtime artifact.

The runtime POI model is an immutable compact core record rather than an ingest model. `PoiSpatialIndex`
indexes its display points and route-corridor queries retain their current public response behavior.

## 7. Artifact contract and loading

The artifact remains a trusted local pickle and receives the integer
`ROUTING_ARTIFACT_SCHEMA_VERSION = 1`. Old artifacts have no such field and fail loudly; there is no
dual-read path. Its logical sections are:

```text
{
  graph: compact undirected graph,
  pois: runtime POI records,
  metadata: {
    artifact_schema_version,
    artifact_revision,
    source provenance,
    build timestamp,
    validation summary
  }
}
```

The builder performs exhaustive validation immediately before writing. Routing and catalog publication
reuse the proven same-directory temporary file, flush, `fsync`, and `os.replace` pattern currently used
by `pound/review/store.py`; a failed build cannot replace the last valid artifact.

Core introduces a distinct immutable `RuntimeArtifact` container and trusted loader. It does not reuse
the current validating `GraphArtifact.__post_init__` path. Deep graph, POI, attachment, and metadata
validators move to `pound-build` and operate before serialization. After unpickling, the core loader
performs only constant-time compatibility checks:

- the top-level payload shape is recognized;
- `artifact_schema_version` exactly matches the runtime;
- `artifact_revision` is present and non-empty;
- the graph, POI collection, and metadata sections have the expected top-level container types.

It does not iterate through nodes, edges, geometry, or POIs. Missing, corrupt, or incompatible artifacts
fail website startup loudly. Pickle is never accepted from a request or other untrusted source. The
independent catalog artifact follows the same producer/consumer rule: `pound-build` validates it fully,
while core checks only its top-level shape, schema version, and revision at runtime.

## 8. Runtime spatial indexes and fixed candidates

At website startup, core derives all process-local indexes from the compact artifact:

1. metric edge polylines and an edge `STRtree`;
2. compact graph-node points where required by diagnostics;
3. runtime POI points and their `STRtree`;
4. fixed candidate samples and their `STRtree`.

Candidate samples are derived rather than persisted. Every candidate-eligible edge contributes its
endpoints and interior positions at 250-metre intervals measured along its metric polyline from the
canonical low-UID endpoint. Shared endpoint samples are deterministically deduplicated. The fixed
250-metre interval replaces and removes the current `minimum_candidate_spacing_m` field and
`POUND_MINIMUM_CANDIDATE_SPACING_M` environment variable. The existing cross-branch greedy spacing pass
still applies after the exact projection and fixed samples are combined.

The candidate index stores lightweight records containing only an edge key, normalized fraction, and
coordinate. It does not duplicate graph edge attributes or geometry. The index is immutable and shared
across requests.

## 9. Projected-point handles and candidate API

A projected canal point is represented by a stateless handle:

```text
CanalPointHandle:
  edge: [low_uid, high_uid]   # canonical order, low_uid < high_uid
  fraction: float             # finite, inclusive range 0.0 through 1.0
```

The artifact revision remains a top-level field in candidate responses and route requests rather than
being repeated inside every handle. A candidate response includes a stable candidate ID for browser
selection, the structured handle, projected coordinate, straight-line distance, and display name. The
ID is deterministically formatted as `"{low_uid}:{high_uid}:{fraction:.12f}"`; it is stable for the same
artifact and candidate across process restarts. It is presentation identity only and is never parsed or
trusted by the server, which routes from the structured handle.

`POST /api/canal-candidates` keeps its current location input and workflow:

1. project the input onto the nearest candidate-eligible edge and include that exact projected point;
2. query nearby fixed samples to fill the bounded candidate pool;
3. deduplicate and enforce the existing 250-metre spacing rule across branches;
4. return candidates with the current artifact revision.

The browser continues to request Google land-transfer results for the returned coordinates, rank the
candidates, permit user selection or fallback confirmation, and retain the selected structured handle.
No server-side candidate session is introduced.

The server re-derives a selected coordinate from the artifact edge and fraction. It never trusts the
coordinate echoed by a browser.

## 10. Partial-edge routing

`POST /api/canal-route` replaces `start_uid` and `end_uid` with `start` and `end`
`CanalPointHandle` objects. Direct raw-coordinate routing is not exposed over HTTP. Core exposes one
planning primitive, `plan_projected_route`, whose constraints carry those handles; the UID-based
`ResolvedConstraints`, `plan_route`, and `plan_canal_route` entry paths are removed rather than retained
as a second routing model.

For each request, core:

1. validates the artifact revision, canonical edge keys, edge existence, and finite fractions;
2. confirms that both endpoint edges are candidate-eligible and satisfy the boat constraints;
3. derives each projected coordinate from the stored polyline;
4. evaluates routes from the start position through either endpoint of its edge and from either endpoint
   of the destination edge to the destination position;
5. also evaluates the direct partial segment when both points occupy the same edge;
6. chooses the minimum eligible total cost using a deterministic key of total cost, chosen endpoint
   IDs, and graph path;
7. assembles partial endpoint geometry and full intermediate edge geometry without mutating the graph.

Evaluating the four endpoint combinations is preferred over adding temporary graph nodes or copying the
shared graph. At Pound's request volume it is simpler than a custom seeded Dijkstra and keeps NetworkX's
existing shortest-path behavior. A same-edge direct candidate is necessary because every endpoint-pair
route would otherwise leave and re-enter that edge. Direct and leave/re-enter alternatives are both
costed because a real network shortcut can make either cheaper. Identical start and end handles return a
successful zero-distance route with no legs, days, locks, or warnings and a valid two-coordinate
`[point, point]` LineString.

Endpoint fractions are measured along simplified metric geometry. Partial cruising distance and time
are the corresponding fraction of authoritative source `length_m`. Because endpoint edges contain no
discrete lock or movable-bridge cost, proportional partial cost cannot apply half of a discrete event.
Full intermediate edges continue to use the existing cost function unchanged.

Route geometry slices endpoint polylines at the selected fractions, orients every segment in traversal
order, removes duplicate joins, and emits the existing GeoJSON coordinate order. Partial endpoint legs
participate in totals and day allocation. Access, tunnel, and unknown-dimension warnings include a
partially traversed endpoint edge; lock and movable-bridge reporting continues over traversed discrete
infrastructure edges.

Because graph UIDs are no longer meaningful route locations, public `RouteAccessSegment` records drop
`from_uid` and `to_uid`. They retain OSM way identity and caveat kind/tag/value, which are the fields used
to produce warnings; duplicate caveats encountered on one route are deterministically deduplicated.

The planner is a coordinated rewrite, not an adapter around a UID path. `_compute_route` first produces
an internal traversal containing an optional start partial edge, ordered full edges, and an optional end
partial edge. Leg construction, `_path_geometry`, `_access_segments`, `_tunnel_warnings`, `_route_locks`,
`_day_path_ranges`, and `_chunk_days` consume that traversal so partial legs participate consistently in
geometry, totals, warnings, and day allocation.

The graph and all spatial indexes remain immutable after startup and are shared by concurrent requests.

### 10.1 Boat-hire reachability and network overlay

Boat-hire bases also become projected handles on candidate-eligible edges. The existing behavior that
seeds both endpoints of a snapped edge at zero cost is removed because it grants free travel across a
potentially long compact edge.

Core provides a bounded multi-source reachability operation that accepts projected sources. For each
base it seeds the two edge endpoints with their proportional partial-edge traversal costs, then runs one
Dijkstra over the compact graph. The base edge contributes only the geometry reachable from the
projection within the cutoff; it is clipped when neither endpoint is reachable rather than exposing the
whole edge for free. Other overlay edges retain the current conservative rule that both endpoints must
be within the cutoff. Multiple bases contribute the union of their reached geometry. Boat constraints
and movable-bridge delay use the same core cost functions as route planning.

`BoatHireAnchor`, `snap_boat_hire_bases`, `select_boat_hire_reachability`, and `/api/canal-network` migrate
to this projected-source behavior. Tests compare compact and detailed fixtures so contraction cannot
silently expand or erase a base's displayed reachable network.

## 11. Errors

- Missing, unreadable, corrupt, or incompatible artifact: website startup failure.
- Candidate or route artifact revision mismatch: HTTP 409 `artifact_revision_mismatch`.
- Noncanonical edge, absent edge, nonfinite fraction, or fraction outside `[0, 1]`: HTTP 400 with the
  corresponding start/end field.
- Endpoint edge unavailable under supplied boat constraints: HTTP 422 `route_unavailable`.
- No eligible graph path: HTTP 422 `route_unavailable`.
- No candidate-eligible edge in a nonempty production artifact: startup failure, because serving an empty
  candidate workflow would indicate a bad build rather than a request error.

Build validation errors identify the source way or compact edge and prevent artifact publication.
There is no silent fallback to the detailed graph, an old artifact schema, node-handle routing, or
runtime deep validation.

## 12. Migration

This change intentionally breaks the artifact and route API contracts.

- Existing artifacts must be rebuilt; the loader does not support both graph schemas.
- Frontend `selectedUid: number` state becomes `selectedCandidateId: string` plus the selected
  `CanalPointHandle`; comparisons and map selection use the deterministic ID format from Section 9.
- Route requests replace `start_uid` and `end_uid` with `start` and `end` handles.
- Candidate map rendering and Google transfer ranking continue to consume returned coordinates.
- Runtime diagnostic CLIs migrate to the single `plan_projected_route` core API; this does not add
  raw-coordinate HTTP routing.
- Build and review imports move from `pound.ingest`, build-oriented `pound.graph` modules, and
  `pound.review` into `pound_build`.
- FastAPI imports move from `pound.web` into `pound_web`.
- The deployment command becomes `uvicorn pound_web.app:app`.
- The Docker build installs only the core and website workspace members, copies runtime files to
  `/app/artifacts` and `/app/data`, and updates environment defaults to those paths.

The package move is performed in one coordinated migration. Temporary compatibility modules are not
retained because there is one repository, one deployment, and no independently versioned external
Python consumer.

## 13. Verification

### 13.1 Build and geometry tests

Small deterministic fixtures prove:

- straight and curved degree-two chains contract;
- junctions, dead ends, names, edge-attribute changes, locks, bridges, tunnels, and access changes remain
  boundaries;
- alternate chains between the same endpoints remain distinct in the simple graph;
- contracted source lengths and route costs are preserved;
- simplification keeps endpoints fixed and measured deviation at or below one metre;
- a deviation violation or invalid simplified geometry fails the build;
- build-only OSM identities and POI attachments are absent from the serialized runtime payload;
- failed validation leaves an existing artifact untouched.

### 13.2 Candidate tests

Tests prove:

- fixed samples are produced at 250-metre intervals and deterministically deduplicated at junctions;
- the exact nearest eligible projection is included even when it is between fixed samples;
- discrete-infrastructure edge interiors are not candidates;
- candidate pool and Google destination ceilings remain bounded;
- handles use canonical edge order and fractions consistent with returned coordinates;
- repeated startup over one artifact produces identical candidate records and exact deterministic IDs.

### 13.3 Routing tests

Tests cover:

- same-edge direct and leave/re-enter routes in both directions;
- identical handles return the specified zero-distance response;
- routes using each of the four start/end endpoint combinations;
- fractions exactly zero and one;
- geometry slicing and orientation on curved edges;
- partial source length, cruising time, totals, and day allocation;
- boat restrictions on endpoint and intermediate edges;
- lock, bridge, tunnel, unknown-dimension, and access behavior;
- deterministic tie-breaking;
- stale, malformed, noncanonical, and absent handles;
- no mutation of graph or indexes across sequential and concurrent requests;
- projected boat-hire sources pay partial-edge costs and produce bounded, clipped source-edge overlays.

### 13.4 Package-boundary and integration tests

- Each workspace member installs and tests independently.
- Static import checks reject core-to-build, core-to-web, and web-to-build dependencies.
- A clean production-image test confirms `pound_build`, Requests, Flask, and Osmium are unavailable.
- End-to-end browser/API tests cover candidate discovery, Google ranking, selection, route submission,
  stale revisions, and map rendering.
- Existing representative routes are compared before and after compaction for availability, restrictions,
  total source distance, infrastructure counts, and geometry bounds. Node paths and leg counts are not
  expected to match because contraction deliberately changes graph segmentation.

### 13.5 England benchmark

A repeatable benchmark records, on the same machine and artifact source:

- artifact and graph-section byte sizes;
- unpickle and compatibility-check time;
- graph, candidate, and POI index-build time;
- total website startup time;
- peak RSS;
- graph node, edge, and retained geometry-coordinate counts;
- candidate sample count;
- route parity results.

These measurements are reported evidence, not hard percentage gates. Any material regression is
investigated before release, but the design does not require a fixed 75% reduction.

## 14. Accepted decisions

- Maximum canal-course deviation is one metre, interpreted as metric lateral geometry deviation rather
  than area.
- Public routes begin and end at selected projected polyline positions, not graph node handles.
- Candidate discovery remains separate from route planning because the browser ranks multiple canal
  access points using land-transfer results and user confirmation.
- Direct-coordinate HTTP routing is out of scope.
- Candidate samples are derived at startup, fixed at 250-metre spacing, and not serialized.
- Runtime trusts a version-compatible local artifact and does not repeat exhaustive build validation.
- Runtime POIs do not retain graph attachment fields.
- Build, core routing, and website server become separate workspace distributions with a hard production
  dependency boundary.
