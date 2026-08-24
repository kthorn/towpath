# Public waterway access filter design

**Issue:** #12 — Model private, permissive, and permit-only waterway access
**Status:** Refined
**Scope:** Build a public-by-explicit-tag routing artifact. This deliberately replaces
Issue #12's proposed request-time authorization policy.

## Goal

Build and route only on waterways that are not explicitly private, permit-only,
or prohibited by OSM `boat` and `access` tags, while preserving route-visible
caveats for `discouraged` and unrecognised explicit values. The result must be
simple enough for the map, CLI, and API to share one artifact with no
per-request permission configuration.

This is **not** a legal determination of navigation rights. Missing OSM tags are
common and remain eligible; users must still verify local access and operational
restrictions.

## Decision summary

1. Private, permit-only, and explicitly prohibited waterways are excluded during
   ingest, before graph construction.
2. `discouraged` waterways remain routable and produce a warning when selected.
3. Missing tags remain silently eligible. Explicit non-standard values remain
   eligible but are inspectable and warned; they are not guessed into hard
   exclusions.
4. The artifact does not retain private/permit ways or expose an access-policy
   request setting. Supporting authorized private routes later requires a new
   scope and a rebuilt artifact.
5. Hire-base reachability is out of scope. This change produces a public graph;
   it neither selects components containing hire bases nor changes the web
   overlay.

## Evidence for the decision

A one-off scan of the local filtered England extract
`pound/data/england_waterways.osm.pbf` (mtime 2026-07-21) gives the expected
impact of this policy. These figures are decision evidence only, not a runtime
threshold or a checked-in fixture:

| Measurement | Current filter | Proposed public filter |
| --- | ---: | ---: |
| Retained `WaterwayFeatures.ways` | 23,173 | 23,031 |
| Graph edges | 695,510 | 691,117 |
| Connected components | 1,645 | 1,656 |
| Largest component nodes | 240,418 | 239,859 |

The proposed filter removes 142 retained ways (0.61%) and 4,393 graph edges
(0.63%). Of the classified routable ways, `access=private` appears 109 times
(79 survive the current boat-only filter); `access=permit` appears zero times.
A later source refresh must be measured again before changing this policy, but
there is no configurable threshold or automatic fallback in this change.

## Access policy

### Explicit exclusions

`pound.ingest.filters.is_navigable()` becomes the sole policy predicate used by
both infrastructure pruning and way filtering. It uses literal, case-sensitive
matching only:

```python
_NON_PUBLIC_BOAT = {"no", "unsuitable", "canoe", "private", "permit"}
_NON_PUBLIC_ACCESS = {"no", "private", "permit"}


def is_navigable(tags: dict[str, str] | None) -> bool:
    tags = tags or {}
    return (
        tags.get("boat") not in _NON_PUBLIC_BOAT
        and tags.get("access") not in _NON_PUBLIC_ACCESS
    )
```

Either tag is sufficient to exclude a way. Thus `access=private, boat=yes` and
`boat=permit, access=yes` are both excluded. Literal matching intentionally
keeps spelling mistakes and future vocabulary out of the deny list rather than
silently dropping a potentially usable waterway.

The existing exclusions remain unchanged: `boat=no`, `boat=unsuitable`, and
`boat=canoe` never enter the graph. The new exclusions are
`boat=private`, `boat=permit`, `access=no`, `access=private`, and
`access=permit`.

### Retained caveats

For each retained way, inspect both `boat` and `access` values:

| Source value | Build result | Selected-route result |
| --- | --- | --- |
| absent | retain | no caveat |
| `yes`, `permissive`, `designated` | retain | no caveat |
| `discouraged` | retain | `discouraged` caveat |
| any other non-empty value after exclusion checking, including `unknown` and `customers` | retain | `unknown` caveat with the original value |
| an explicit exclusion above | remove | cannot appear |

This applies equally to `boat=*` and `access=*`. It does not evaluate
conditional access, timetables, permissions, or legal ownership. A retained
`access=customers` therefore warns rather than receiving an invented meaning.

## Ingest and graph contract

### Existing pipeline order

Do not move filtering into either reader's parsing loop. Both existing flows
must retain their current order:

1. Read and classify waterways, dropping derelict features inline.
2. Run `prune_non_navigable_infra(features)` against the complete way set.
3. Run `filter_navigable_ways(features)` to remove non-public ways.
4. Build, annotate, validate, and serialize the graph.

`prune_non_navigable_infra()` already calls `is_navigable()`. Extending that
shared predicate means an infra node whose incident ways are all private,
permit-only, or explicitly prohibited is pruned before the carrier ways are
removed. Place nodes continue to be retained. This applies to
`osm.read_england_waterways()`, `osm.read_england()`, and
`overpass.fetch_oxford()` without source-specific policy copies.

`pound.graph.pois._routing_eligible()` must also reuse `is_navigable()` rather
than maintain its separate boat-only deny set. Preserve its existing
`navigable` and `routing_eligible` guards; copy any edge `tags` mapping and let
direct edge-level `boat` or `access` values override it before calling the
shared predicate. This keeps POI attachment consistent for synthetic or
future graph inputs that retain access tags.

### Caveat evidence on edges

Add a small frozen `AccessCaveat` value in `pound.ingest.ir`:

```python
@dataclass(frozen=True, order=True)
class AccessCaveat:
    osm_way_id: int
    tag: Literal["boat", "access"]
    value: str
    kind: Literal["discouraged", "unknown"]
```

Add `access_caveats: tuple[AccessCaveat, ...]` to every newly created graph
edge. A pure helper in `pound.ingest.filters` creates sorted, deduplicated
caveats for one retained source way. It only emits the retained caveats from the
table above; normal public values produce an empty tuple.

`build_graph()` initializes each emitted edge from that helper. Its existing
`_merge_edge()` unions and sorts both sides' caveat tuples. This matters when
coincident OSM ways merge: the selected edge must not lose a caveat merely
because another source way is unremarkable. No general raw-tag store is added.

### Artifact compatibility

Add `access_caveats` to `pound.graph.artifact._EDGE_FIELDS` and validate that
it is a sorted tuple of unique, valid `AccessCaveat` values. In particular, each
record has a positive OSM way ID, a supported tag/key, a non-empty raw value,
and a matching caveat kind.

This required field intentionally makes older artifacts invalid under the
existing rebuild guidance. Pound must fail rather than route an old artifact
without the public-access filtering and caveat contract. Generated artifacts
remain uncommitted.

## Route result and warnings

The planner gains no access configuration and does no access filtering: it
receives a public-access graph and continues to apply only existing boat
dimension eligibility.

After `networkx.shortest_path()` returns, `_compute_route()` walks the selected
path and reads each edge's `access_caveats`. It must collect caveats at this
point, not inside the Dijkstra weight callback, so explored-but-unselected edges
never leak into the response. It must not modify graph edge data.

Add this response model in `pound.schemas`:

```python
class RouteAccessSegment(BaseModel):
    from_uid: int
    to_uid: int
    osm_way_id: int
    kind: Literal["discouraged", "unknown"]
    tag: Literal["boat", "access"]
    value: str
```

`from_uid` and `to_uid` are the canonical ascending graph-node pair, not route
travel direction. `RouteResult.access_segments` uses
`Field(default_factory=list)` so existing Python constructors remain valid, but
is always present in API responses. It is sorted by
`(from_uid, to_uid, osm_way_id, tag, value, kind)` and contains one record for
every selected graph-edge/caveat pair. Repeated source-way IDs are intentional
when a source way contributes more than one selected graph segment.

Keep `RouteResult.warnings` as the human-facing channel already rendered by the
CLI and web summary. Derive deterministic, grouped messages from
`access_segments`, sorted by caveat kind, tag, and raw value:

- `Route uses {n} segment(s) tagged {tag}=discouraged; verify local access.`
- `Route uses {n} segment(s) with unrecognized {tag}={json-quoted value}; verify local access.`

Existing dimension and day-budget warnings remain; access warnings are appended
in a stable order after the existing dimension warning and before the day-budget
warning. A graph with no caveats produces `access_segments=[]` and no new
warning.

`CanalConstraints`, `ResolvedConstraints`, the FastAPI request body, and CLI
options remain unchanged. The FastAPI response receives the new field through
its existing Pydantic response model. This is an additive shared-contract
change, so coordinate any external `RouteResult` consumer before deploying a
new artifact. Update TypeScript with a matching `RouteAccessSegment` interface
and `RouteResult.access_segments` field. The existing `TripSummary.svelte`
renders generic warnings already, so it needs no new control or presentation
component.

## Testing

Use hermetic synthetic OSM inputs and graphs. Do not make a test depend on the
ignored England PBF or generated artifact.

1. **Filter and pruning tests**
   - Extend `tests/ingest/test_filters.py` for every denied `boat` and `access`
     value, including contradicting `boat=yes` / `access=yes` combinations.
   - Retain and test missing, `yes`, `permissive`, `designated`, and both
     `boat=discouraged` and `access=discouraged`; warn for explicit `unknown`,
     `access=customers`, and malformed values.
   - Extend `tests/ingest/test_prune.py` to prove a non-place infra node with
     only newly non-public incident ways is dropped, while a mixed/public
     incident node remains.
   - Cover both existing reader entry points with fixture inputs so shared
     predicate wiring, not just the pure helper, is protected.

2. **Graph and artifact tests**
   - Add graph-build cases proving a retained caveat is attached to every
     emitted segment and that a merged edge keeps the sorted union of evidence.
   - Extend `tests/graph/test_pois.py` so `_routing_eligible()` rejects
     edge-level or nested `boat`/`access` exclusions through the shared
     predicate while retaining its existing explicit eligibility guards.
   - Update all strict graph/artifact fixtures to include an empty
     `access_caveats` tuple where appropriate.
   - Prove invalid/missing/unsorted/duplicate caveat data fails artifact
     validation with the existing rebuild instruction.

3. **Route, API, and frontend-contract tests**
   - Build a small competing-path fixture in which private/permit/access-no
     ways are removed before route planning and the surviving public path is
     selected.
   - Prove `discouraged` and explicit unknown/malformed values appear only for
     selected edges in `access_segments` and generate stable warnings.
   - Snapshot edge caveats before and after planning to prove route planning
     does not mutate the shared graph.
   - Verify `/api/canal-route` serializes `access_segments`.
   - Extend `tests/test_schemas.py` to pin the empty default and update any
     exact response-shape assertions, including `tests/web/test_concurrency.py`.
   - Update TypeScript fixtures and tests with `access_segments: []`; retain the
     existing generic warning rendering coverage instead of adding a second UI
     warning subsystem.

Run the narrow Python and web tests first, then `uv run pytest`,
`uv run pytest --run-bulk`, and `uv run ruff check .` with the required bulk
extra installed.

## Rollout

Build a fresh England artifact before deploying this change; an older artifact
must fail validation. Record the resulting removed-way, edge, and component
deltas in Issue #12 before replacing the production artifact. If a refreshed
source shows a materially different impact, pause for a product decision rather
than adding an automatic private-route fallback.

## Documentation and issue hygiene

- Update `README.md` to describe the public-by-explicit-tag graph and its legal
  caveat. Do not claim that a route proves navigation permission.
- Add `boat` and `access` rows to the §3.1 tags table and update the §5.2
  eligibility prose in `docs/pound-engine-design.md`.
- Do not rewrite `docs/completed/2026-06-28-boatability-filter-and-phase3-perf-design.md`:
  it correctly records the previous, narrower build decision.
- Update the pending Issue #16 design to treat this public filter as a
  prerequisite: remove its `is_navigable`/`access=no` implementation work,
  replace its statement that private/permit values remain eligible by default,
  and retain this spec's `access_caveats` alongside—not instead of—its future
  bridge and tunnel edge fields.
- Coordinate tunnel warnings in that #16 design. A tunnel normalizer must not
  emit a second tunnel-restriction warning for a `discouraged` or `unknown`
  `boat`/`access` value already represented in `access_segments`; it may retain
  its existing tunnel warning for other surviving non-`yes` values. The shared
  stable warning order is dimensions, access caveats, tunnel restrictions, then
  day-budget warnings.
- Update Issue #12's body/acceptance criteria to describe the public artifact,
  caveat evidence, response records, and rebuild requirement—not request-time
  opt-ins or private/permit route warnings.

## Non-goals

- No authorized-private or permit-only routing, permission checkboxes, or
  request-scoped access policy.
- No hire-base component selection, overlay filtering, or changes to the web
  network endpoint.
- No directed routing, time-aware access evaluation, conditional-tag parser,
  or legal-rights inference.
- No persistent access-policy settings, new dependency, artifact migration, or
  generated-data commit.

A future private-route feature starts from fresh source data and a rebuilt
artifact; it must not be smuggled into this public-network filter.
