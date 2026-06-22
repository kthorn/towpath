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

## Data attribution

OSM data is © OpenStreetMap contributors, licensed ODbL. Derived artifacts
inherit ODbL share-alike + attribution requirements.
