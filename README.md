# Towpath

Canal-trip planning for UK inland waterways, powered by the deterministic Pound routing
engine. The web app supports point-to-point and out-and-back journeys, hire bases,
nearby places, and optional historical temperature overlays.

## Local development

Requires Python 3.12+, `uv`, and Node/npm for the frontend. Install dependencies:

```bash
uv sync
cd web
npm ci
cd ..
```

Use current Great Britain graph and catalog artifacts. If you need to build them, see
[bulk ingest](docs/development.md#bulk-ingest-build-great-britain).
Generated artifacts and downloaded data stay out of git.

Start the backend from the repository root:

```bash
POUND_ARTIFACT_PATH="$PWD/artifacts/great-britain.pkl" \
POUND_CATALOG_PATH="$PWD/artifacts/great-britain-catalog.pkl" \
POUND_BOAT_HIRE_ENRICHMENT_PATH="$PWD/data/boat-hire-enrichment.csv" \
uv run uvicorn pound_web.app:app --host 127.0.0.1 --port 8000 --reload
```

In another terminal, start the frontend:

```bash
cd web
VITE_GOOGLE_MAPS_API_KEY='restricted-browser-key' \
VITE_GOOGLE_MAP_ID='project-map-id' \
npm run dev
```

Open <http://127.0.0.1:5173>. Vite proxies `/api` to the backend;
<http://127.0.0.1:8000/api/health> reports artifact and service status.
`VITE_*` values are public browser configuration. See
[Google Maps setup](docs/development.md#google-maps-safety-and-operations) for API
requirements and key restrictions. With local settings in `.env.sh`,
`scripts/dev.sh` starts both servers.

## Checks

```bash
uv run pytest
uv run ruff check .
cd web
npm test -- --run
npm run check
npm run build
```

Live-network, bulk-ingest, and browser smoke tests are opt-in. See the
[development reference](docs/development.md) and
[browser smoke guide](web/tests/smoke/README.md).

## Optional agent

The [Pi agent package](packages/towpath-agent/README.md) provides a bounded runtime
and a live GPT 5.6 Luna tool-call smoke test. It uses an OpenAI API key stored in
AWS Secrets Manager. The conversational website integration is still to come;
Pound routing itself remains deterministic and makes no model calls.

## Reference

- [Development and API reference](docs/development.md): runtime settings, artifact builds,
  places, routing CLI, boat-hire review, and temperature data.
- [Deployment runbook](docs/fly-runbook.md): production builds and operations.
- [Pound engine design](docs/pound-engine-design.md).
- [Out-and-back journeys](docs/completed/2026-09-05-turnaround-out-and-back-design.md).
- [Agent runtime design](docs/completed/2026-09-05-pi-agent-runtime-design.md).

Canal geometry and OSM places require **© OpenStreetMap contributors** attribution
and compliance with the ODbL. See [data attribution](docs/development.md#data-attribution).
