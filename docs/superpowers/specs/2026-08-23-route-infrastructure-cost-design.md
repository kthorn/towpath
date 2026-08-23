# Route infrastructure costs and tunnel restrictions design

**Issue:** #16 — Apply movable-bridge and tunnel constraints in route cost · **Status:** Refined and approved; implementation not started

## Goal

Make route choice and reported travel time account for movable bridges, while
making tunnel restrictions visible without pretending Pound can evaluate
navigation timetables. Preserve enough source data during bulk and Overpass
ingest to make both behaviours deterministic.

## Decisions

- The canonical movable-bridge delay is **5 minutes**.
- That value has one code owner: `route/cost.py`. UI, API, and CLI callers do
  not define a second default.
- A user may override the delay per route; `0` explicitly disables it.
- A bare `tunnel=yes` is routable and has neither a delay nor a warning.
- Tunnel directional, timed, conditional, and other unimplemented restriction
  tags keep a route usable but produce warnings.
- `access=no` excludes a waterway globally during ingest. The build must retain
  disconnected components left by that exclusion for connectivity validation;
  it must not delete them merely because they are disconnected.
- Pound will not add directed or timetable-aware routing in this issue.

## Source-tag policy

The bridge row applies to a retained routable waterway way or to a movable
bridge node that can be attached to such a way; unrelated bridge-tagged road
ways do not become routing events.

| Source tag | Build behaviour | Route behaviour |
| --- | --- | --- |
| `boat=no`, `boat=unsuitable`, `boat=canoe` | Existing navigability filter excludes it | Never selectable |
| `access=no` | Navigability filter excludes it globally | Never selectable |
| `bridge:movable=*` or `bridge=movable` | Create one movable-bridge event | Add configured delay once when crossed |
| `tunnel=yes` with no restriction tag | Preserve tunnel flag | No delay or warning |
| `oneway`, `oneway:boat` on a tunnel | Preserve tag/value evidence | Route remains selectable; emit warning |
| `opening_hours`, `*:conditional`, `restriction*`, or other access/direction restriction evidence on a tunnel | Preserve tag/value evidence | Route remains selectable; emit warning |

`is_navigable` rejects `access=no` even when a contradictory `boat=yes` is
present. `access=private`, `boat=private`, malformed values, and other values
that are not explicitly excluded retain the current eligible-by-default
behaviour. When such a value is restriction evidence on a tunnel, it is
surfaced as a warning rather than silently interpreted.

The supported OSM convention is `oneway:boat` for boat-specific direction;
conditional restrictions can use tags such as `oneway:conditional` and
`access:conditional`. Pound records these instead of evaluating them because
requests have no departure time.

## Ingest and graph contract

### Retention and filtering

1. Extend the existing `is_navigable` / `filter_navigable_ways` path to reject
   `access=no` in addition to the existing explicit non-navigable `boat` values.
   It remains ordered after infrastructure-node pruning, so pruning can see all
   prohibited ways before they disappear.
2. Extend both source paths to retain and classify movable bridge nodes tagged
   `bridge:movable=*` and `bridge=movable`. In particular, add both node forms
   to the bulk `osmium tags-filter` expression; Overpass must request both
   forms too. Waterway-way tags are already retained by the waterway filter.
3. Keep the current raw `WaterwayWay.tags` source material, but normalize only
   the routing facts needed by the artifact. Do not make request-time routing
   reread OSM data.

### Bridge and tunnel annotations

Graph construction initializes every node with an empty sorted
`movable_bridge_ids` tuple and every edge with empty sorted
`movable_bridge_ids` and `tunnel_restrictions` tuples. A tunnel restriction is
an `(osm_way_id, key, value)` triple.

Way-derived annotations are created inside `build_graph`, while each complete
`WaterwayWay` is still available, rather than in a post-build scan that could
lose a merged-away source way:

- Before assigning a bridge-tagged waterway event, a movable-bridge node wins
  when either its OSM ID occurs in the way's node references or its point
  projects within the existing 25 m source-attachment tolerance of the
  source-way geometry. The coordinate rule makes deduplication work on the
  Overpass `out geom` path, where way node references are normally absent.
- A bridge-tagged waterway without that matching node creates `way:<osm_id>` on
  the lower middle **emittable** source segment (index
  `(emittable_segment_count - 1) // 2` in source order). Duplicate/zero-length
  segments are excluded before choosing it; if none are emittable, no graph
  event is created because the way is not routable.
- Each `tunnel=yes` way adds its normalized restriction triples to every
  emitted segment. Edge creation and `_merge_edge` union and sort both
  annotation tuples, so tunnel evidence survives coincident-way merges.

Immediately after graph construction, movable-bridge nodes are attached:
exact OSM-ID or coordinate graph-node matches create `node:<osm_id>` on that
node. Otherwise choose a projected edge within 25 m by the deterministic key
`(distance_m, length_m, sorted_endpoint_uids)` and add the node event there.

`has_tunnel` remains the required tunnel gate. The existing
`has_movable_bridge` remains a source-way compatibility flag, but routing reads
only `movable_bridge_ids`. A bare tunnel has an empty
`tunnel_restrictions` tuple.

The build order is graph construction with way annotations, bridge-node
attachment, name/gazetteer annotation, lock attachment, POI attachment,
validation, then artifact serialization. Artifact validation checks that every
new field has the stated tuple shape, sorted/unique contents, nonempty bridge
identifiers, and finite/int source IDs. Older artifacts must fail validation
with the existing rebuild instruction rather than silently route without bridge
costs or tunnel warnings. Generated artifacts remain uncommitted.

## Routing and configuration

`route/cost.py` replaces `BRIDGE_MINUTES` with one canonical
`DEFAULT_MOVABLE_BRIDGE_DELAY_MIN = 5.0`. `time_min` accepts the resolved delay
and the number of crossed bridge events; it does not hide a second default in
schemas or callers.

The nullable `movable_bridge_delay_min` override flows through:

- `CanalConstraints` and `ResolvedConstraints`;
- the FastAPI route request and TypeScript route request type;
- the persisted boat-settings store and settings form; and
- `pound-plan --movable-bridge-delay-min`.

`plan_route_from_constraints` and the CLI's `_resolve_start_end` must forward
the field into the same resolved model as the API path. An omitted or blank
override means “use the route default.” Python request models use Pydantic
`FiniteFloat` plus `ge=0`; the CLI uses an argparse converter that rejects
non-finite values before model construction; and the settings form uses
`Number.isFinite`. The settings form allows zero while its existing
boat-dimension fields remain strictly greater than zero. A stored settings
record that predates this field deserializes it as `null` without discarding its
valid boat dimensions.

The planner resolves the delay once. For each directed traversal `u -> v`, its
transition-cost helper adds the event IDs on the traversed edge and on node
`v`, then feeds that bridge count and the resolved delay into `time_min`.
Dijkstra weighting, every leg's `est_minutes`, route totals, and day budgeting
call that same helper. The entry rule intentionally does not charge a bridge
at the starting node; it charges one at an arrived-at destination node. This
makes an intermediate node bridge cost exactly once and must be documented in
code to prevent a later double-count "fix." The shared helper prevents a new
path-selection/reporting divergence as bridge costs are enabled. No new public
bridge-count field is required in route results.

## Tunnel warnings

For `tunnel=yes` edges, the normalizer records restriction evidence from
`oneway` or `oneway:boat` unless its value is explicitly `no`; nonempty
`opening_hours`; `access` or `boat` values other than `yes`; any key ending in
`:conditional`; and `restriction` or `restriction:*` keys. It preserves raw
values rather than attempting to parse them. After selecting a path, the
planner collects those annotations, deduplicates them by source way/tag/value,
sorts them by `(osm_way_id, key, value)`, and emits the stable template
`tunnel way <id>: unmodeled restriction <key>=<JSON-quoted value>` through the
existing `RouteResult.warnings` list.

- Directional tags, including `oneway` and `oneway:boat`, warn but do not make
  an undirected route unavailable.
- Time-dependent, conditional, malformed, and unknown values warn but do not
  receive a guessed delay.
- A prohibited `access=no` way cannot reach this stage because ingest removed
  it.
- A tunnel without restriction evidence remains silent.

Restriction relations and non-`yes` tunnel values are not ingested as tunnel
rules in this issue. The existing CLI and trip-summary warning renderers are
reused; no parallel warning schema or UI subsystem is needed.

## Verification

### Python and ingest tests

- Extend navigability tests for global `access=no` exclusion while preserving
  the current handling of other access values.
- Prove the bulk tag filter and both readers retain node- and way-form movable
  bridge features.
- Cover bridge anchoring, one-event-per-physical-source behaviour, exact-node
  and 25 m geometry-based node/way deduplication (including the Overpass path),
  merged coincident ways retaining bridge/tunnel evidence, and required artifact
  field shape/order validation. Update strict graph/artifact fixtures that must
  carry the new required fields.
- Cover bare tunnels, directional/timed/conditional/unknown restriction
  warnings, and unavailable routes once `access=no` breaks the only path.
- Build competing fixture paths where the default five-minute bridge delay
  selects a longer bridge-free route, while a zero override selects the shorter
  bridged route.
- Assert legs, route totals, and day budgets use the same resolved cost as path
  selection, including an `A -> bridge-node B -> C` path that charges B exactly
  once and pins the start-exempt/destination-charged rule.

### API, CLI, and web tests

- Validate finite, non-negative API and CLI overrides, including zero, omitted
  values, and rejected non-finite CLI input.
- Verify the settings store persists an override, accepts zero, sends it
  with route requests, and treats legacy stored settings without the field as
  blank; blank settings send `null` and use the server default.
- Verify warnings reach the existing route response and summary display.

Run the narrow Python and web tests first, then the default suite, bulk suite
for the PBF retention coverage, and Ruff. No downloaded PBF or generated graph
artifact belongs in the change.

## Documentation

Update the engine design's cost-model section, CLI help/usage, README, and the
navigability-filter docstring to state the five-minute default, the zero-disable
override, global `access=no` filtering (which wins over `boat=yes`), and
warning-only tunnel restriction policy.

## Non-goals

- No departure-date/time input or opening-hours parser.
- No directed graph or enforcement of `oneway:boat`.
- No real-time bridge or tunnel operating data.
- No automatic deletion of disconnected canal components.
- No new generic infrastructure framework or request-time source-data lookup.

## References

- `docs/pound-engine-design.md` §§3.1 and 5.2
- OpenStreetMap Wiki: [Key:oneway:boat](https://wiki.openstreetmap.org/wiki/Key:oneway:boat)
  and [Conditional restrictions](https://wiki.openstreetmap.org/wiki/Conditional_restrictions)
