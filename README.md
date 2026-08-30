# Pound

Deterministic routing engine for UK inland waterways. Plain Python library, no
MCP / no LLM / no network at request time.

See `pound-engine-design.md` for the full design brief.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```

## Standalone boat-hire candidate review

Generate the ranked local review file, then serve it for human decisions:

```bash
uv sync --extra dev
uv run pound-boat-review generate \
  --catalog pound/artifacts/england-catalog.pkl \
  --graph pound/artifacts/england.pkl \
  --out pound/artifacts/boat-hire-review.json
uv run pound-boat-review serve \
  --review pound/artifacts/boat-hire-review.json
```

Generation keeps only named candidates within 250 m of any routing-eligible
edge in the graph, preserves decisions for retained identities, and omits the
rest from the active ignored JSON. The generated JSON is a local ignored
artifact. The reviewer opens at
`http://127.0.0.1:5000/`. Some websites block iframes; use the visible new-tab
fallback when that happens.

## Map prototype: local development

Install Python dependencies. Map development uses a full England artifact; the
network-dependent Oxford/Overpass path is only a legacy ingest scaffold and is
not the recommended way to start the application.

```bash
uv sync --extra dev
```

Point the application at an existing England artifact with an absolute path,
or build a current one from the England PBF as described under **Bulk ingest**.
The artifact must have been built with a version of Pound that writes
`artifact_revision`; the web application intentionally rejects older,
revisionless artifacts. Rebuild a revisionless artifact once rather than
patching its pickle metadata.

Start FastAPI from the repository root. `pound.web.app:app` reads its settings
when Uvicorn starts the application, so exporting or prefixing the environment
variables works without an application factory flag:

```bash
POUND_ARTIFACT_PATH=/absolute/path/to/pound/artifacts/england.pkl \
POUND_BOAT_HIRE_ENRICHMENT_PATH=/absolute/path/to/pound/data/boat-hire-enrichment.csv \
POUND_STATIC_DIR=web/dist \
uv run uvicorn pound.web.app:app --host 127.0.0.1 --port 8000 --reload
```

Confirm that the backend loaded the artifact and reports its routing status:

```bash
curl http://127.0.0.1:8000/api/health
```

### Places API

The unified places endpoint is `POST /api/places`. It is available only when
both the OSM catalog and the required curated boat-hire CSV loaded successfully.
Without a configured catalog, routing remains healthy while
`places_status` is `unavailable`; a configured catalog that is missing or
invalid makes health `degraded` and places requests return `503` with no partial
results. Successful responses contain only a `places` list: there is no public
catalog revision, day-number, segment-policy, matching-count, or over-cap field.

Viewport mode preserves map-layer filtering:

```bash
curl -X POST http://127.0.0.1:8000/api/places \
  -H 'content-type: application/json' \
  -d '{"mode":"viewport","kinds":["pub","marina"],"bounds":{"south":51.0,"west":-2.0,"north":52.0,"east":-1.0},"policy":{"basis":"none"}}'
```

Nearby mode accepts caller-named points or full LineString targets and batches
up to `POUND_PLACES_MAX_TARGETS` targets:

```bash
curl -X POST http://127.0.0.1:8000/api/places \
  -H 'content-type: application/json' \
  -d '{"mode":"nearby","kinds":["pub","boat_hire"],"radius_m":1000,"targets":[{"id":"stop","geometry":{"type":"Point","coordinates":[-1.0,51.0]}}]}'
```

OSM results retain structured element type/ID and normalized metadata. Public
boat-hire results come only from non-excluded `company_base` CSV rows and retain
provider/location identities plus validated source links; `review_positive` rows
are curation evidence, not public providers. An exact canonical OSM identity
suppresses its OSM result only when the matching hire row is emitted. Coordinates,
names, proximity, and other URLs are not deduplication evidence, so distinct
providers at one base remain distinct.

In another terminal, start Vite:

```bash
cd web
npm ci
VITE_GOOGLE_MAPS_API_KEY='restricted-browser-key' \
VITE_GOOGLE_MAP_ID='project-map-id' \
VITE_TRANSFER_MODE='WALK' \
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to FastAPI on port 8000.
`VITE_TRANSFER_MODE` accepts `WALK`, `DRIVE`, `TRANSIT`, or `BICYCLE`. All
`VITE_*` values are embedded into the browser bundle at build time: they are
public client configuration, not runtime secrets. Never use a server secret as
the browser key.

Use the England artifact for routine local UI work, including the Bletchley Park
scenario below. Keep generated artifacts outside version control.

### Runtime settings and artifact compatibility

FastAPI supports these environment variables:

- `POUND_ARTIFACT_PATH` (required): graph artifact loaded once at startup.
- `POUND_BOAT_HIRE_ENRICHMENT_PATH` (required): curated CSV seeds the displayed
  boat-hire network overlay only; the graph, routing, candidates, POIs, and
  catalog remain complete.
- `POUND_STATIC_DIR` (default `web/dist`): production frontend files.
- `POUND_CANDIDATE_POOL_SIZE` (default `20`): geometric candidates considered.
- `POUND_GOOGLE_DESTINATION_LIMIT` (default `10`): candidates returned for the
  browser's Google route matrix request.
- `POUND_MINIMUM_CANDIDATE_SPACING_M` (default `250`): candidate separation.
- `POUND_CATALOG_PATH` (optional): independent OSM catalog artifact. If unset,
  routing still starts and `/api/health` reports `places_status: unavailable`.
- `POUND_CATALOG_MAX_KINDS` (default `16`), `POUND_CATALOG_MAX_RADIUS_M`
  (default `2000`), `POUND_CATALOG_MAX_VIEWPORT_SPAN_DEG` (default `10`),
  `POUND_CATALOG_MAX_ROUTE_VERTICES` (default `10000`), and
  `POUND_CATALOG_QUERY_WORK_BUDGET` (default `100000` candidate checks) bind
  both `/api/places` modes.
- `POUND_PLACES_MAX_TARGETS` (default `64`) bounds nearby target batches.

Candidate UIDs are valid only for their artifact revision. If the backend
reports `artifact_revision_mismatch`, ensure the rebuilt artifact is deployed,
then refresh or reselect both endpoints to load fresh candidates and re-plan.
The frontend needs rebuilding only when its code or `VITE_*` configuration
changes, not merely because the backend artifact revision changed. Rebuild an
artifact whenever its source data or graph-building rules change; do not copy
UIDs between artifacts.

If Maps or Places is unavailable, each endpoint also accepts latitude and
longitude. This non-map coordinate fallback still finds canal candidates and
plans a canal route; Google land-transfer overlays may remain unavailable.

### Google Maps safety and operations

Enable Maps JavaScript API and Routes API. Enable Places API (New) and its
Places library only when endpoint autocomplete is part of the deployment; the
catalog does not call the Places Web Service or Place Details. Restrict the browser key
to the exact local and production origins and restrict it to the APIs actually
used. Use a project map ID. Set conservative per-API quotas, billing budgets
and alerts, and monitor request/error dashboards before sharing a deployment.
Google map, autocomplete, and route-matrix requests are made by the browser and
may be billable.

**OSM place Google-link policy (URL-only MVP):** OSM markers expose an
external `Search on Google Maps` link built as a URL-encoded
`https://www.google.com/maps/search/?api=1&query=...` using the OSM name plus
address/locality, or the OSM name plus coordinates when locality is absent. It
needs no API key or Places quota. Do not add Place Details, Google-derived
names/addresses/phones/ratings/reviews/photos, Place IDs, response caches, or
bulk/background enrichment. Google's current terms prohibit displaying Places
content with or near a non-Google/OSM map; any API enrichment is blocked pending
Google support/legal review. The OSM-only marker and metadata remain the
fallback.

Pound's canal geometry is derived from OpenStreetMap. Preserve visible
“© OpenStreetMap contributors” attribution and comply with the ODbL when
displaying or distributing derived data; Google basemap attribution does not
replace it.

### Production container

Build-time Google values become public JavaScript configuration:

```bash
docker build -t pound-map \
  --build-arg VITE_GOOGLE_MAPS_API_KEY='restricted-production-browser-key' \
  --build-arg VITE_GOOGLE_MAP_ID='production-map-id' \
  --build-arg VITE_TRANSFER_MODE='WALK' .
```

The image includes the versioned curated boat-hire CSV and sets its required
`POUND_BOAT_HIRE_ENRICHMENT_PATH`. Rebuild the image to deploy CSV changes;
keep the routing artifact as a separate read-only mount:

```bash
docker run --rm -p 8000:8000 \
  -e POUND_ARTIFACT_PATH=/data/england.pkl \
  -v "$PWD/pound/artifacts/england.pkl:/data/england.pkl:ro" \
  pound-map
```

Open `http://127.0.0.1:8000`. Runtime environment variables cannot replace the
`VITE_*` values already built into the image; rebuild to change browser config.

### Manual Bletchley acceptance check

With a full England artifact, search the origin for **Bletchley Park** and the
destination for **Black Prince Holidays, Stoke Hammond**. Confirm that ranked
canal candidates appear at both ends, choose a non-recommended destination
candidate, plan the route, and check that both land-transfer lines and the canal
line appear. The summary must show transfer metrics and canal distance, locks,
cruising time, warnings, and day divisions where applicable. Verify proposed
access and navigation restrictions locally; a graph node is not a promise of a
safe mooring, pedestrian entrance, or vehicle drop-off.

### Canal network view

The map sends the live `Days` × `Hours per day` schedule and saved boat settings
to `POST /api/canal-network`. It shows active hire-base markers and one-way
reach from any base, defaulting to 7 × 6 hours and capping reach at 168 cruising
hours. This filters only the background display; routing, candidates, POIs, and
the catalog continue to use the full graph.

### Route overlays and POI layers

The map shows points of interest and route overlays when a route is planned.

- **POI layers** (pubs, water points, provisions, transport) are disabled by
  default. Toggle them via the layer control panel; each layer queries only POIs
  near the route and within the current viewport bounds.
- **Zoom-in indicator**: when a selected POI layer exceeds 1,000 matching
  features in the viewport a "zoom in to see markers" message appears. Zooming
  closer restores individual markers.
- **Lock markers**: locks on the planned route appear as overlay markers. Each
  lock shows its name (if available) and the day it falls on.
- **Day segments**: clicking a day in the plan summary highlights its route
  segment on the map and fits the viewport to that segment.
- **API endpoint**: the `/api/route-pois` endpoint serves POI data scoped to an
  `artifact_revision`. It accepts bounds, route geometry, POI kinds, and an
  optional day filter.

### Frontend tests

```bash
cd web
npm test -- --run
npm run check
npm run build
npm run test:smoke -- --list
```

Unit tests are offline. The Google browser smoke test is separate, opt-in, and
potentially billable; its exact prerequisites and command are in
`web/tests/smoke/README.md`.

## Prerequisites

- Shapely and pyproj are core dependencies used to normalize POI geometry,
  measure corridor distances in British National Grid coordinates, and build
  runtime spatial indexes. They are installed by `uv sync`.
- `osmium-tool` (system CLI) for `pound-ingest build england` — install via
  apt/brew/conda. The `pyosmium` Python package is separate and pulled by the
  `bulk` extra: `uv sync --extra bulk`. The base `uv sync` works without it.

## Legacy regional ingest scaffold (Oxford)

The Overpass reader is retained as **legacy scaffolding** for narrow ingest
experiments and network tests on the Oxford Canal. Do not use it to prepare the
map application's normal development artifact. The public Overpass endpoint may
rate-limit or reject this request (including HTTP 406); use the bulk England
build below for the application.

Fetch the Oxford extract and print the summarize() report (network required):

```bash
uv run pound-ingest oxford
# or, also writing the features IR:
uv run pound-ingest oxford --out pound/data/oxford_canal_waterways.json
```

### Build the legacy Oxford artifact

```bash
uv run pound-ingest build oxford --out pound/artifacts/oxford.pkl
```

Produces a small pickled NetworkX graph for ingest testing only. It does not
cover the England-wide product workflow.

Network tests are skipped by default; run them explicitly:

```bash
uv run pytest --run-network
```

## Bulk ingest (`build england`)

The full bulk path needs the Geofabrik England extract (manual download; the
CLI does not download 1.5 GB itself):

```bash
curl -L -o pound/data/england.osm.pbf \
  https://download.geofabrik.de/europe/united-kingdom/england-latest.osm.pbf
uv sync --extra bulk
uv run pound-ingest build england --out pound/artifacts/england.pkl
```

If the PBF is missing the build prints the URL and exits non-zero. The build
hard-fails on `derelict_edges>0`, `self_loops>0`, or
`tolerance_snaps_unresolved` above `--max-unresolved-snaps` (default `0`,
forcing manual curation via `pound/data/overrides.json` before a real England
artifact is trusted). Advisory keys (`edges_missing_dims`,
`ambiguous_place_names`, gazetteer discrepancy, and **component_count /
component_sizes**) are reported but never fail the build.

The build also attaches a deliberately bounded set of OSM points of interest:

- Canal services (`water_point`, sanitary disposal, fuel, marina, and mooring)
  and pedestrian access signals (entrances, paths, bridges, steps, and selected
  barriers) must be within 250 m of a navigable waterway edge.
- Provisions (selected food amenities and shops) and public transport (rail,
  bus, and taxi) must be within 1,000 m.

Boat water points are identified only by `waterway=water_point`. Generic
`amenity=drinking_water`, toilets, and showers are intentionally outside the
product scope and are not imported as POIs.

The CLI's `poi_summary` reports the retained total, counts by category and
kind, corridor rejections, malformed geometry, incomplete relations, unknown
tag values, and detailed skipped counts with capped examples. The same summary
is stored in artifact metadata.

POI support changes the strict artifact schema. Rebuild existing artifacts;
there is no legacy fallback or in-place migration. Pickle artifacts are trusted
local build products only: never load a pickle obtained from an untrusted
source.

**Tuning connectivity against real data:** start with a deliberately low
tolerance to *measure* how fragmented the network really is, then dial up:

```bash
uv run pound-ingest build england --out /tmp/eng.pkl --tolerance-m 1
# read component_count / component_sizes from the report:
#   thousands => most 'gaps' are real OSM-edit curation; add join overrides.
#   ~ a dozen  => the fragmentation is plausibly genuine (derelict arms,
#                separate basins); most 'gaps' are correct as-is.
```

The report is the authority, not the threshold — `--tolerance-m` is the
exploration dial; `pound/data/overrides.json` is where confirmed joins and
suppressed false snaps land.

Bulk tests are skipped by default; run them explicitly:

```bash
uv run pytest --run-bulk
```

### Separate OSM place catalog

The place catalog is an independent artifact built from the **original England
PBF**, not from the filtered waterway build and not from the routing graph
artifact. Build it only when catalog marker layers are needed:

```bash
catalog_tmp=$(mktemp -d)
trap 'rm -rf "$catalog_tmp"' EXIT
uv run pound-ingest catalog england \
  --pbf pound/data/england.osm.pbf \
  --out "$catalog_tmp/england-catalog.pkl" \
  --profile
```

Catalog artifacts use serialized contract version `2` and carry the exact
attribution value `© OpenStreetMap contributors`. Catalog revisions identify
individual builds and remain independent from routing artifact revisions.
Catalogs built with an older or missing schema version are rejected at startup
and must be rebuilt with `pound-ingest`; they are not migrated in place.

A successful real-England build produced **185,029 records**, an
**85,378,417-byte** artifact, in **200.49 s wall time**, with **2,534,084 KiB
peak RSS**. The explicit build gates are: exactly 185,029 records for the same
source/filter (a source refresh requires a new inventory review), artifact size
<= **100,000,000 bytes**, build wall time <= **300 s**, and build peak RSS <=
**3,000,000 KiB**. The real build baseline passes all four build gates. The
benchmark run rebuilt the catalog from `/home/kurtt/towpath/pound/data/england.osm.pbf`
into a temporary artifact; `/usr/bin/time` measured **211.32 s** wall time and
**2,527,792 KiB** peak RSS, also passing the build gates.

A fresh nationwide startup/index-load measurement used the validated
**176,977-record** England catalog and the deployed England routing artifact
(**691,564 nodes**, **691,117 edges**, and **523,636 POIs**), with actual
`GraphSpatialIndex` plus `CatalogSpatialIndex` construction and the curated
boat-hire seed load. The benchmark reported **98,426.135 ms** (**98.426 s**)
of in-process startup/index-load time. `/usr/bin/time` reported **103.46 s**
wall time, **97.71 s** user time, **6.24 s** system time, and **4,220,848 KiB**
maximum RSS. The hard startup gates remain <= **130 s measured inside the
process** and <= **4,615,019 KiB** peak RSS; this run passes both. Startup is a
one-time cost on the measured host, not a per-query cost.

Run the reproducible nationwide places benchmark with the required curated
CSV (keep output outside version control):

```bash
benchmark_json=$(mktemp)
time_log=$(mktemp)
trap 'rm -f "$benchmark_json" "$time_log"' EXIT
/usr/bin/time -v uv run python scripts/catalog_query_benchmark.py \
  --catalog-artifact /home/kurtt/towpath/pound/artifacts/england-catalog.pkl \
  --routing-artifact /home/kurtt/towpath/pound/artifacts/england.pkl \
  --boat-hire-enrichment pound/data/boat-hire-enrichment.csv \
  --warmups 2 --iterations 5 >"$benchmark_json" 2>"$time_log"
```

The benchmark loads both artifacts, parses the production boat-hire CSV once,
builds `GraphSpatialIndex`, `CatalogSpatialIndex`, and `PlacesIndex`, warms
every request, and times only `PlacesIndex.query(request, stats=stats)`. Its
fixed cases cover locality/no-policy, route+day, waterway, the densest
predefined viewport within the **100,000-candidate** work budget, and nearby
point, line, and multi-target requests. The current England run produced:

| Case | Viewport/target | Candidate work | Outcome / result count | p50 ms | p95 ms | Max ms |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| densest predefined | London | 34,565 | result_limit_exceeded / — | 43.805 | 60.062 | 62.411 |
| locality/no-policy | Oxford | 1,227 | result_limit_exceeded / — | 23.573 | 24.770 | 24.893 |
| nearby-line | LineString | 91 | ok / 42 | 0.963 | 1.254 | 1.311 |
| nearby-multi-target | Point + LineString | 108 | ok / 47 | 1.085 | 1.738 | 1.823 |
| nearby-point | Point | 17 | ok / 5 | 0.103 | 0.106 | 0.107 |
| route+day | Milton Keynes | 736 | ok / 73 | 12.692 | 14.527 | 14.822 |
| waterway | Milton Keynes | 736 | ok / 39 | 2.207 | 3.388 | 3.394 |

`candidate_work` comes from the `PlacesQueryStats` instance populated by the
same query that produced each row. `result_limit_exceeded` is the complete
result-ceiling outcome; it does not return a partial result count. The fixed
p50/p95/max values are a host-specific observed regression baseline, not a
product SLA or hard latency gate. Record them for comparisons and rerun the
benchmark on a deployment host before drawing performance conclusions. The
hard acceptance gates remain startup/RSS plus bounded candidate-work and
complete-result behavior. The benchmark process reported **4,220,848 KiB** RSS;
RSS and query timing are host-specific. Its JSON is sorted and records
candidate work, outcome/result count, p50, p95, max, and RSS.

Keep the output outside version control and do not commit the PBF, catalog
artifact, profiler output, or temporary Google spike data. The independently
built catalog and routing artifacts may be deployed separately; no OSM catalog
revision is exposed by the places request or successful response.

Configure the optional catalog alongside the routing artifact when starting
FastAPI:

```bash
POUND_ARTIFACT_PATH=/absolute/path/to/pound/artifacts/england.pkl \
POUND_BOAT_HIRE_ENRICHMENT_PATH=/absolute/path/to/pound/data/boat-hire-enrichment.csv \
POUND_CATALOG_PATH=/absolute/path/to/england-catalog.pkl \
POUND_STATIC_DIR=web/dist \
uv run uvicorn pound.web.app:app --host 127.0.0.1 --port 8000
```

Catalog records are OSM-derived. Keep the visible linked
“© OpenStreetMap contributors” attribution in every catalog view and comply
with ODbL share-alike and attribution requirements when distributing derived
catalog data. Catalog metadata contains no Google enrichment; the only Google
action is the URL-only external search link described above.

## Planning a route (`pound-plan`)

Minimal, eyeballing-only surface over the loaded artifact:

```bash
uv run pound-plan Oxford Banbury --days 3
# override the artifact:
uv run pound-plan Oxford Banbury --days 3 --artifact pound/artifacts/england.pkl
# boat constraints:
uv run pound-plan Oxford Banbury --days 3 --boat-beam 2.0 --boat-draft 0.8
# disable movable-bridge delay for a what-if route comparison:
uv run pound-plan Oxford Banbury --days 3 --movable-bridge-delay-min 0
```

`--days` is optional: omit it and the day count is inferred from `--hours-per-day`
(you get as many days as the route needs, no cap). Default output is the route
header + totals + per-day summary + warnings; add `--verbose` for the
node-to-node leg list, or `--locks` to fold a per-day lock count into the day
summary (how many locks each day's cruise works through).

Movable bridges add the backend five-minute delay per bridge unless
`--movable-bridge-delay-min` overrides it (any non-negative minutes; `0`
disables the delay entirely). Omit the flag and the five-minute default
applies. The browser route form persists only that optional override — blank
uses the same backend default. Route warnings list tunnel restrictions Pound
does **not** evaluate — direction (`oneway` / `oneway:boat`), opening hours,
conditional tags, and `access`/`boat` restrictions — plus any unknown-dimension
segments. `access=no` waterways are excluded from the network at build time;
the resulting disconnected component is reported by build validation rather
than deleted.

Unknown / ambiguous place names and un-routable constraints produce a clear
error, not a traceback. A REST API will eventually supersede this CLI for
product use; it is deliberately a test harness, not a planner.

### Public waterway access

Built routing artifacts exclude waterways explicitly tagged
`boat=no|unsuitable|canoe|private|permit` or
`access=no|private|permit`. Missing OSM access tags remain routable; selected
`discouraged` or unrecognised explicit values appear as route warnings and
access-segment evidence. This is not proof of a legal navigation right—verify
local rules, permits, operating restrictions, and safe access before travel.
Rebuild the artifact after upgrading Pound; older artifacts deliberately fail
validation.

### Routing by uid

`pound-plan` accepts a graph node **uid** (the integer `pound-locate` prints,
below) as well as a place name for `start` and `end` — auto-detected by shape
(all-digits → uid, else → name), and mixable:

```bash
uv run pound-plan Oxford Hayfield --days 1            # names (as above)
uv run pound-plan 0 1 --days 1                        # uids
uv run pound-plan 0 Hayfield --days 1                  # mixed uid + name
```

A uid not in the loaded graph exits nonzero with `uid N is not a node in the
graph` — clear error, not a traceback.

## Locating the nearest canal node (`pound-locate`)

Resolve a coordinate to the nearest canal-network node uid + distance:

```bash
uv run pound-locate --lat 51.75 --lon -1.26
# override the artifact:
uv run pound-locate --lat 51.75 --lon -1.26 --artifact pound/artifacts/england.pkl
# fail if the nearest canal is farther than N metres (for scripting):
uv run pound-locate --lat 51.75 --lon -1.26 --max-distance-m 200
```

Prints `<uid>  <name|->  <distance_m>` (one line). `name` is the matched
node's `name` if it has one, else `-`. Closes the loop with `pound-plan`:
`pound-locate` finds the uid a map click snaps to, then `pound-plan` routes
from it. A future map-click UI uses the same `resolve_coord` function this CLI
wraps.

## Data attribution

OSM data is © OpenStreetMap contributors, licensed ODbL. The routing graph and
separate place catalog are derived artifacts and inherit ODbL share-alike and
attribution requirements. Google Maps attribution does not replace OSM
attribution. Google Places content is not stored or displayed in the catalog;
see the URL-only policy under **Google Maps safety and operations**.
