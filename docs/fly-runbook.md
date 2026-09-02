# Fly Redeployment Runbook

This runbook operates the existing Towpath deployment. For the rationale
behind its one warm Machine, see
[`2026-08-11-fly-warm-machine-deployment-design.md`](completed/2026-08-11-fly-warm-machine-deployment-design.md).

## Live deployment

| Setting | Value |
| --- | --- |
| App | `towpath-4772e4a8` |
| Public domain | `https://towpath-4772e4a8.fly.dev` |
| Region | `sjc` |
| Machine | one `shared-cpu-4x` / 8 GB Machine |
| Warm minimum | `min_machines_running = 1` |

Use the `fly.dev` hostname, not Fly's shared IPv4 address. There is no custom domain.

```bash
APP=towpath-4772e4a8
DOMAIN=https://towpath-4772e4a8.fly.dev
ARTIFACT=artifacts/great-britain.pkl
CATALOG_ARTIFACT=artifacts/great-britain-catalog.pkl
```

Run commands from the repository root in a clean, isolated deployment worktree.

## Before every deployment

Authenticate, use a clean tracked checkout, and validate the configuration that will
be deployed:

```bash
fly auth whoami
test -z "$(git status --porcelain)"
fly config validate --strict --app "$APP"
```

For every release, record its `ImageRef`, `EXPECTED_REVISION`, and
`FLY_CONFIG_COMMIT` together in the release notes. Configuration-only releases and
rollbacks need that record to verify both the selected immutable image and the
matching `fly.toml`.

## Full source redeploy (code or tracked data)

Use this path after changing application code, frontend code, dependency files, or
tracked runtime files below `packages/` or `data/`. Stage the selected graph at
`$ARTIFACT` and catalog at `$CATALOG_ARTIFACT` first; if either is absent, use the
corresponding artifact-redeploy procedure below. Source-only checks and inputs are
required here, not for configuration-only releases:

```bash
uv sync --all-packages --extra bulk
uv run pytest
uv run ruff check .
(cd web && npm ci && npm run check && npm test -- --run)
test -f "$ARTIFACT"
test -f "$CATALOG_ARTIFACT"
git check-ignore -q "$ARTIFACT"
git check-ignore -q "$CATALOG_ARTIFACT"
EXPECTED_REVISION="$(uv run --package pound-core python -c '
from pathlib import Path
from pound.artifact import load_artifact
from pound.catalog.artifact import load_catalog
load_catalog(Path("artifacts/great-britain-catalog.pkl"))
print(load_artifact("artifacts/great-britain.pkl").metadata["artifact_revision"])
')"
printf 'Deploying artifact revision: %s\n' "$EXPECTED_REVISION"
: "${VITE_GOOGLE_MAPS_API_KEY:?set the restricted browser key}"
: "${VITE_GOOGLE_MAP_ID:?set the production map ID}"
: "${VITE_TRANSFER_MODE:?set the transfer mode}"
fly deploy --app "$APP" --ha=false \
  --build-arg "VITE_GOOGLE_MAPS_API_KEY=$VITE_GOOGLE_MAPS_API_KEY" \
  --build-arg "VITE_GOOGLE_MAP_ID=$VITE_GOOGLE_MAP_ID" \
  --build-arg "VITE_TRANSFER_MODE=$VITE_TRANSFER_MODE"
```

After it succeeds, list releases and record the newest complete `ImageRef` with
`$EXPECTED_REVISION` and the config commit, then follow
[Verify a deployment](#verify-a-deployment):

```bash
fly releases --app "$APP" --image
FLY_CONFIG_COMMIT="$(git rev-parse HEAD)"
printf 'Record config commit: %s\n' "$FLY_CONFIG_COMMIT"
```

A rolling deployment of the only Machine has a startup outage while the graph loads.

## Graph-artifact redeploy

Use this path after rebuilding the routing graph. Copy the selected generated graph
into the ignored artifact location, then use the full source procedure:

```bash
: "${NEW_ARTIFACT:?set the generated great-britain.pkl path}"
mkdir -p "$(dirname "$ARTIFACT")"
cp "$NEW_ARTIFACT" "$ARTIFACT"
test -f "$ARTIFACT"
git check-ignore -q "$ARTIFACT"
EXPECTED_REVISION="$(uv run --package pound-core python -c '
from pound.artifact import load_artifact
print(load_artifact("artifacts/great-britain.pkl").metadata["artifact_revision"])
')"
printf 'Deploying artifact revision: %s\n' "$EXPECTED_REVISION"
```

Run the full source deploy, then record its `ImageRef`, `$EXPECTED_REVISION`, and
`FLY_CONFIG_COMMIT="$(git rev-parse HEAD)"`. Never commit the staged graph artifact.

## Catalog-artifact redeploy

Use this path after rebuilding the place catalog. Copy the selected generated catalog
into the ignored artifact location, validate it with the runtime loader, then use the
full source procedure:

```bash
: "${NEW_CATALOG_ARTIFACT:?set the generated great-britain-catalog.pkl path}"
mkdir -p "$(dirname "$CATALOG_ARTIFACT")"
cp "$NEW_CATALOG_ARTIFACT" "$CATALOG_ARTIFACT"
git check-ignore -q "$CATALOG_ARTIFACT"
uv run --package pound-core python -c '
from pathlib import Path
from pound.catalog.artifact import load_catalog
load_catalog(Path("artifacts/great-britain-catalog.pkl"))
'
```

Never commit the staged catalog artifact.

## Configuration-only redeploy

For a `fly.toml`-only change, reuse the current image rather than rebuilding browser
assets. First identify the completed image you want to keep and find its recorded
artifact revision:

```bash
fly releases --app "$APP" --image
read -r -p "ImageRef: " IMAGE_REF
read -r -p "Recorded artifact revision: " EXPECTED_REVISION
fly deploy --app "$APP" --ha=false --image "$IMAGE_REF" --now
FLY_CONFIG_COMMIT="$(git rev-parse HEAD)"
printf 'Record config commit: %s\n' "$FLY_CONFIG_COMMIT"
```

This path does not need the artifact or Vite variables. Do not use an image without
a recorded revision: it cannot meet the revision-verification requirement. If the
selected Machine was already stopped, `min_machines_running = 1` prevents a later
autostop below one but does not proactively start it; use the recovery step in
[Verify a deployment](#verify-a-deployment).

## Roll back

List releases, select the prior known-good `ImageRef`, artifact revision, and
`fly.toml` commit, then deploy the image with that exact configuration:

```bash
fly releases --app "$APP" --image
read -r -p "Known-good ImageRef: " IMAGE_REF
read -r -p "Recorded artifact revision: " EXPECTED_REVISION
read -r -p "Known-good fly.toml commit: " FLY_CONFIG_COMMIT
rollback_config="$(mktemp)"
trap 'rm -f "$rollback_config"' EXIT
git show "$FLY_CONFIG_COMMIT:fly.toml" > "$rollback_config"
fly config validate --strict --app "$APP" --config "$rollback_config"
fly deploy --app "$APP" --config "$rollback_config" --ha=false --image "$IMAGE_REF" --now
```

Do not roll back without the complete release record. Follow the shared verification
procedure after the deployment.

## Verify a deployment

Validate the committed configuration and inspect the only Machine:

```bash
fly config validate --strict --app "$APP"
fly machines list --app "$APP"
```

There must be exactly one `sjc` `shared-cpu-4x:8192MB` Machine, in `started` state
with a passing check. If it is stopped, get its ID from the listing and start it once:

```bash
read -r -p "Stopped Machine ID: " MACHINE_ID
fly machine start "$MACHINE_ID" --app "$APP"
fly machines list --app "$APP"
```

Make one no-retry public health request and require the recorded revision for every
release path:

```bash
response_file="$(mktemp)"
trap 'rm -f "$response_file"' EXIT
curl --fail --show-error --silent --output "$response_file" --max-time 300 \
  "$DOMAIN/api/health"
EXPECTED_REVISION="$EXPECTED_REVISION" uv run python - "$response_file" <<'PY'
import json
import os
import sys

with open(sys.argv[1]) as response_file:
    health = json.load(response_file)

assert health["status"] == "healthy", health
assert health["artifact_revision"] == os.environ["EXPECTED_REVISION"], health
print("health={} artifact_revision={}".format(health["status"], health["artifact_revision"]))
PY
```

After several idle minutes, run `fly machines list --app "$APP"` again: the same
one Machine must still be started and passing. Do not add a keepalive, retry loop,
or early health response.

## Safety notes

- Keep `min_machines_running = 1`; the 8 GB Machine cannot use Fly suspend, and
  ordinary stop/start did not meet the accepted readiness contract.
- Keep `--ha=false`: this deployment intentionally has one Machine, no volume, no
  database, and no autoscaler.
- Do not use the shared IPv4 as an endpoint. The canonical public address is
  `https://towpath-4772e4a8.fly.dev`.
- Do not commit `artifacts/great-britain.pkl`, `artifacts/great-britain-catalog.pkl`, browser
  configuration values, or credentials.
- This runbook does not add CI, a custom domain, a second region, or scale-to-zero.
