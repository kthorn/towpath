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
POUND_STATIC_DIR=web/dist \
uv run uvicorn pound.web.app:app --host 127.0.0.1 --port 8000 --reload
```

Confirm that the backend loaded the artifact and reports its revision:

```bash
curl http://127.0.0.1:8000/api/health
```

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
- `POUND_STATIC_DIR` (default `web/dist`): production frontend files.
- `POUND_CANDIDATE_POOL_SIZE` (default `20`): geometric candidates considered.
- `POUND_GOOGLE_DESTINATION_LIMIT` (default `10`): candidates returned for the
  browser's Google route matrix request.
- `POUND_MINIMUM_CANDIDATE_SPACING_M` (default `250`): candidate separation.

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

Enable Maps JavaScript API, Places API, and Routes API. Restrict the browser key
by HTTP referrer to the exact local and production origins and restrict it to
those APIs. Use a project map ID. Set conservative per-API quotas, billing
budgets and alerts, and monitor request/error dashboards before sharing a
deployment. Google requests are made by the browser and may be billable.

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

Run the single FastAPI/frontend image with the artifact mounted read-only:

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

## Planning a route (`pound-plan`)

Minimal, eyeballing-only surface over the loaded artifact:

```bash
uv run pound-plan Oxford Banbury --days 3
# override the artifact:
uv run pound-plan Oxford Banbury --days 3 --artifact pound/artifacts/england.pkl
# boat constraints:
uv run pound-plan Oxford Banbury --days 3 --boat-beam 2.0 --boat-draft 0.8
```

`--days` is optional: omit it and the day count is inferred from `--hours-per-day`
(you get as many days as the route needs, no cap). Default output is the route
header + totals + per-day summary + warnings; add `--verbose` for the
node-to-node leg list, or `--locks` to fold a per-day lock count into the day
summary (how many locks each day's cruise works through).

Unknown / ambiguous place names and un-routable constraints produce a clear
error, not a traceback. A REST API will eventually supersede this CLI for
product use; it is deliberately a test harness, not a planner.

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

OSM data is © OpenStreetMap contributors, licensed ODbL. Derived artifacts
inherit ODbL share-alike + attribution requirements.
