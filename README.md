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

Network tests are skipped by default; run them explicitly:

```bash
uv run pytest --run-network
```

## Bulk ingest (`build england`)

The full bulk path needs the Geofabrik England extract (manual download; the
CLI does not download 1.5 GB itself):

```bash
curl -L -o pound/data/england.osm.pbf \
  https://download.geofabrik.de/europe/great-britain/england-latest.osm.pbf
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

## Data attribution

OSM data is © OpenStreetMap contributors, licensed ODbL. Derived artifacts
inherit ODbL share-alike + attribution requirements.
