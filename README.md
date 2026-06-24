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

## Data attribution

OSM data is © OpenStreetMap contributors, licensed ODbL. Derived artifacts
inherit ODbL share-alike + attribution requirements.
