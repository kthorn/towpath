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

## Prerequisites

- `osmium-tool` (system CLI) for `pound-ingest build england` — install via
  apt/brew/conda. The `pyosmium` Python package is separate and pulled by the
  `bulk` extra: `uv sync --extra bulk`. The base `uv sync` works without it.

## Regional ingest (dev / scaffolding)

The Overpass reader is **scaffolding** for early development on a small dataset
(Oxford Canal). It is replaced by a pyosmium bulk reader over the Geofabrik GB
PBF in design step 6.

Fetch the Oxford extract and print the summarize() report (network required):

```bash
uv run pound-ingest oxford
# or, also writing the features IR:
uv run pound-ingest oxford --out pound/data/oxford_canal_waterways.json
```

### Build the graph artifact

```bash
uv run pound-ingest build oxford --out pound/artifacts/oxford.pkl
```

Produces a pickled NetworkX graph with provenance metadata, ready for
`plan_route` to load at request time.

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
node-to-node leg list.

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
