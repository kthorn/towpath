# Turnaround-aware hire-base reachability

## Context

The initial website map calls `POST /api/canal-network` to show the canal network reachable from
all active hire bases for a selected cruise duration and boat. The API divides the total travel
budget by two and `select_boat_hire_reachability()` returns every fully reached, boat-eligible edge.
This models the time needed to go out and return, but it assumes the boat can reverse at any reached
node. On a linear canal it can therefore display a terminal reach beyond the last place where the
boat can turn.

GitHub issue #55 owns this initial-overlay behavior. Issue #8 remains responsible for practical day
stops, and #17 remains responsible for later Canal & River Trust enrichment. This change lands on
`main` independently of the compact-routing-artifact work.

## Goal

Only display canal reaches from which a hire boat can make a feasible return trip. Before reversing,
the boat must reach one of:

- an OSM winding hole tagged `waterway=turning_point` that can accept the selected boat length;
- a canal junction with at least three boat-eligible navigable approaches; or
- a hire-base source node, which remains a valid boundary of the union produced for multiple bases.

The change must remain deterministic, request-time network-free, and must not mutate the loaded
routing graph.

## Non-goals

- CRT winding-hole ingestion; #17 will add this as another offline source.
- Mooring-aware day planning; #8 owns that selection.
- General cruising-ring discovery or budgeted loop routing; #18 owns ring routes.
- Partial-edge rendering or splitting a hire-base anchor edge at its projected coordinate.
- API response or frontend changes.

## Offline ingestion and graph representation

Add `TURNING_POINT` to `NodeKind`. The PBF tags filter retains
`n/waterway=turning_point`; the Overpass query adds the equivalent node selector so the Oxford
fixture-build path fetches the same evidence. Both readers classify these nodes through the existing
`classify_node()` path.

Every graph node carries two required attributes:

- `turning_point: bool`;
- `turning_max_length_m: float | None`.

Ordinary nodes use `False` and `None`. A matched OSM turning point uses `True`; its optional
`maxlength` is parsed through the existing dimension parser and stored as metres. Missing or
unparseable length evidence remains `None`, matching the project's existing treatment of missing or
unparseable waterway dimensions.

OSM turning points are expected to be nodes on a routable waterway. During graph construction, a
turning point attaches by shared OSM node identity or the graph's normalized coordinate identity.
Unmatched standalone points do not create routable graph geometry and are ignored, consistent with
other node infrastructure attachment. The existing non-navigable-infrastructure pruning also removes
turning points found only on access-restricted waterway ways. CRT points may require edge splitting
later under #17.

The strict artifact validator requires both attributes and validates their types and finite positive
length. Existing artifacts consequently fail with the existing actionable “rebuild the artifact”
error instead of silently degrading to junction-only behavior.

The future graph compactor must treat `turning_point=True` as discrete node infrastructure, retain the
node, and retain both fields. That compatibility is a requirement for the compact-artifact
implementation, not part of #55.

## Request-time selection

`select_boat_hire_reachability()` keeps its public signature and continues to apply boat dimensions,
lock cost, movable-bridge cost, and the half-trip cutoff.

The function performs these steps:

1. Build the source-node set from endpoints of boat-eligible hire-base anchor edges, as today.
2. Define boat-eligible edges with the existing `is_eligible()` helper.
3. Run bounded multi-source Dijkstra with the existing traversal-time weight.
4. Build a copied subgraph from fully reached, eligible edges, preserving the current no-partial-edge
   behavior.
5. Determine protected turnaround nodes, reading the required node attributes directly so malformed
   in-memory graphs fail rather than silently degrading:
   - source nodes;
   - explicit turning points whose maximum length is absent, whose selected boat length is absent, or
     whose maximum length is at least the selected boat length;
   - nodes whose degree in the full boat-eligible graph is at least three.
6. Repeatedly remove degree-zero or degree-one nodes that are not protected until no such node
   remains.
7. Return the pruned graph.

Junction degree is measured in the full boat-eligible graph, not the cutoff subgraph. A cutoff
boundary therefore cannot become a false junction, and an approach blocked by boat dimensions cannot
make a junction turnable.

Leaf pruning removes terminal reaches after their last eligible turnaround while retaining the paths
from sources to those turnarounds. It also preserves eligible cycles already present in the bounded
subgraph; validating the total duration of a complete cruising ring remains outside #55.

The returned graph is a copy because pruning mutates it. The application-wide graph is never changed.
If no anchor edge is eligible, `/api/canal-network` returns an empty `lines` list while retaining the
existing hire-base markers. Otherwise source protection retains an eligible anchor edge even when no
farther outbound reach qualifies.

## Error handling and compatibility

No new request validation or response fields are needed. Invalid boat dimensions continue to be
rejected by `CanalNetworkRequest`. Missing turning-length evidence permits the point, just as missing
edge dimension evidence currently permits traversal.

An artifact without the new required node fields raises `InvalidArtifactError` while loading; web
startup wraps it in `RuntimeError` while preserving the existing rebuild instruction. This is
intentional: silently treating an old artifact as having no winding holes would produce an incomplete
and misleading overlay.

## Testing

Focused tests cover:

- PBF-filter and Overpass-query inclusion plus `classify_node()` recognition of turning points;
- graph attachment and `maxlength` parsing;
- artifact rejection when either required field is absent and validation of invalid field values;
- pruning a linear canal back from the raw cutoff to its last winding hole;
- retaining a qualifying degree-three junction;
- ignoring a junction approach that is dimension-ineligible for the selected boat;
- rejecting a winding hole whose known maximum length is shorter than the selected boat;
- accepting unknown boat length or unknown winding-hole length;
- inclusion at the exact travel cutoff;
- the union from multiple hire bases;
- an empty line overlay with base markers when no anchor edge is boat-eligible; and
- no mutation of the loaded graph.

Existing boat-hire reachability tests that use terminal stubs must either mark their expected endpoint
as a valid turnaround or update the expected pruned edge set. In particular, the exact-cutoff and
movable-bridge-delay tests will mark their terminal node as a winding hole so they continue testing
their named behavior rather than leaf pruning.

Because the new node fields are required, every hand-built graph passed through artifact validation
or directly to reachability selection must add `turning_point=False` and
`turning_max_length_m=None` unless the fixture tests a turnaround. Artifact missing-field tests add a
case for each field. This includes shared web fixtures, graph-artifact fixtures, artifact-comparison
fixtures, and route-plan artifact fixtures; graphs produced by `build_graph()` receive the defaults
automatically.

Run the narrow ingest, graph, artifact, boat-hire, and network API tests first, followed by Ruff and the
full default suite with both development and bulk extras installed.
