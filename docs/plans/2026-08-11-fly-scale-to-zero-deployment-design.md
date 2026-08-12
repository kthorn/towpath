# Fly.io Scale-to-Zero Deployment Design

> **Status:** refined design
> **Scope:** publish the existing graph-only Towpath web application for a few US Pacific users

## Goal

Publish the current single-container FastAPI/Svelte application on Fly.io with the
lowest practical idle cost. The first request after idle may be slow; if it errors
or times out, scale-to-zero is rejected rather than masked. Correctness, low
ongoing cost, and a simple manual deploy matter more than instant startup or high
availability.

## Measured Constraints

The app is not a small web process despite its 290MB graph artifact:

- Loading `england.pkl` without the optional catalog took about 87 seconds locally.
- The Uvicorn process reached 4.65GB RSS and 4.87GB peak RSS at startup.
- Serving the complete canal-network overlay (a 2.58MB response) did not raise that
  peak.
- `POUND_CATALOG_PATH` is currently unset, so this deployment deliberately matches
  the existing graph-only behavior rather than adding the 79MB catalog artifact.

A Fly `shared-cpu-1x` Machine cannot hold this process: it is capped at 2GB. The
initial deployment therefore uses a `shared-cpu-4x` Machine with 8GB RAM. Eight GB
leaves room above the observed startup peak while real full-graph routing is
validated. It may be reduced only after real production-route checks show adequate
headroom.

## Decisions

- Deploy one Fly Machine in **`sjc`** (San Jose), selected for US Pacific users.
- Use Fly Proxy stop/start, with zero warm Machines. A request after several idle
  minutes starts the existing Machine; a slow but successful first response is
  acceptable.
- Publish a public, unauthenticated URL. “A few friends” describes expected use,
  not an access-control boundary; add authentication only if you want it private.
- Package the graph artifact into the immutable deployment image. Do not create a
  Fly Volume.
- Keep the graph artifact Git-ignored. Stage a local copy into the deployment
  worktree before each deploy; it is uploaded only through the Docker build context.
- Start with Fly's generated `https://<app>.fly.dev` hostname. Buy and attach a
  custom domain later.
- Deploy manually from the release worktree. Explicitly decline Fly's optional
  database, Redis, object storage, and GitHub workflow at launch. Do not add CI, a
  database, a volume, a second region, a spare HA Machine, or a metrics autoscaler.

## Packaging and Artifact Flow

```text
local generated england.pkl
        |
        | copy into ignored pound/artifacts/ in deployment worktree
        v
Fly remote Docker build
  |- Svelte production build
  |- FastAPI application
  `- /app/pound/artifacts/england.pkl
        |
        v
one stopped-or-started Fly Machine in sjc
        |
        v
Fly Proxy HTTPS -> FastAPI / API + static SPA
```

The existing `.gitignore` entry for `pound/artifacts/` remains unchanged. This is
an **additive `.dockerignore` fragment**, not a replacement file: retain every
existing rule, delete only its blanket `pound/artifacts` line, then add:

```dockerignore
.env*
web/.env*
.pi-subagents
scripts/local
pound/artifacts/*
!pound/artifacts/england.pkl
```

The implementation deletes, rather than supplements, the existing
`pound/artifacts` ignore line; every other existing Docker ignore rule remains.
`england-catalog.pkl`, local agent artifacts, root and frontend `.env*` files,
local scripts, and other artifact files or directories below `pound/artifacts/`
remain out of the Docker context. The wheel target must also exclude generated
artifacts so `uv sync --no-editable` does not install a second 290MB copy inside
`.venv`:

```toml
[tool.hatch.build.targets.wheel]
packages = ["pound"]
exclude = ["pound/artifacts/**"]
```

The artifact remains at `/app/pound/artifacts/england.pkl` after `COPY pound/ pound/`;
the wheel exclusion only prevents redundant package data. Immediately after that
`COPY`, before `uv sync`, the Dockerfile must run:

```dockerfile
RUN test -f pound/artifacts/england.pkl
```

That makes a missing staging step fail the build rather than creating an image that
only fails on its first request. In the web-builder stage, replace `RUN npm run
build` with:

```dockerfile
RUN test -n "$VITE_GOOGLE_MAPS_API_KEY" \
    && test -n "$VITE_GOOGLE_MAP_ID" \
    && npm run build
```

The browser Maps key and production Map ID are required;
`VITE_TRANSFER_MODE` retains its existing application default. The container's
fixed runtime configuration is:

```toml
[env]
  POUND_ARTIFACT_PATH = "/app/pound/artifacts/england.pkl"
```

An artifact update is intentionally simple: copy the new local `england.pkl` into
the deployment worktree, confirm it is still ignored by Git, then record its
revision before deploying:

```bash
expected_revision="$(uv run python -c '
from pound.graph.artifact import load_artifact
print(load_artifact("pound/artifacts/england.pkl").metadata["artifact_revision"])
')"
printf 'Deploying artifact revision: %s\n' "$expected_revision"
```

Record this value with the artifact build/release notes before deployment; it is the
human approval point for choosing the graph. `/api/health` exposes the loaded
`artifact_revision`; its post-deploy value must equal `$expected_revision`.
Artifact-only redeploys must also use the Vite build-argument command below; the
Dockerfile deliberately fails a fresh shell that omits required browser config.

## Fly Configuration

Choose an available app name of the form `towpath-<unique-suffix>` and pass it
explicitly to `fly launch`; commit that account-allocated name in `fly.toml`.

```toml
app = "towpath-<unique-suffix>"
primary_region = "sjc"

[build]
dockerfile = "Dockerfile"

[deploy]
strategy = "rolling"
wait_timeout = "10m"

[env]
  POUND_ARTIFACT_PATH = "/app/pound/artifacts/england.pkl"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = "stop"
  auto_start_machines = true
  min_machines_running = 0

[[http_service.checks]]
  method = "GET"
  path = "/api/health"
  grace_period = "1m"
  interval = "15s"
  timeout = "10s"

[[vm]]
  cpu_kind = "shared"
  cpus = 4
  memory = "8gb"
```

Fly caps HTTP health-check grace at one minute. The measured 87-second local graph
load may therefore outlast grace, so early checks can fail while FastAPI finishes
startup. Service-check failures only withhold routing; they do not restart or stop
the Machine, and the 15-second probes recover once it is ready. The 10-minute deploy
wait and the real cold-start acceptance test—not grace alone—govern this design.

`fly launch --no-deploy --ha=false` and subsequent `fly deploy --ha=false` keep
the app to one provisioned Machine; autostop may only start or stop that Machine
and does not create more. The explicit rolling strategy replaces its only Machine
rather than using canary or blue/green capacity, so deploys have a cold-start
outage. That tradeoff is accepted for this low-traffic site. The committed
10-minute deploy wait gives every release enough time for image startup, health
checks, and graph loading.

Use Fly's remote builder because Docker is unavailable in the local WSL
environment. `--build-arg` values are visible in build metadata/history, so never
pass a server secret; the Maps key is intentionally public browser configuration.

## Cost Boundaries

Before launch, check Fly's current `sjc` pricing; budget **at least $55/month for
always-running compute**, plus rootfs, egress, and any allocated network resources.
This is not the expected cost for sporadic use. Stopped Machines are not charged
for CPU or RAM; Fly charges their root filesystem at $0.15 per GB per 30 days.

Fly does not provide billing alerts. Keep one Machine, no volume, and no
autoscaler, then review the Fly dashboard's month-to-date cost during the first
month. Google Maps Platform billing is separate and must have its own budget and
quota controls.

## Google Configuration and Domain

The Vite variables are build-time browser configuration, not runtime application
secrets:

- `VITE_GOOGLE_MAPS_API_KEY`
- `VITE_GOOGLE_MAP_ID`
- `VITE_TRANSFER_MODE`

Create a dedicated production browser key after Fly allocates the app hostname.
Restrict it by HTTP referrer to `https://<app>.fly.dev/*` and enable only the Maps
APIs already required by the UI. Export the three production Vite values in the
local shell and pass them explicitly:

```bash
fly deploy --ha=false \
  --build-arg "VITE_GOOGLE_MAPS_API_KEY=$VITE_GOOGLE_MAPS_API_KEY" \
  --build-arg "VITE_GOOGLE_MAP_ID=$VITE_GOOGLE_MAP_ID" \
  --build-arg "VITE_TRANSFER_MODE=$VITE_TRANSFER_MODE"
```

The key is necessarily visible in the built JavaScript, so its referrer restriction
and API limits are the protection.

Fly provides HTTPS for `<app>.fly.dev`. When a domain is purchased, attach it with
`fly certs add <domain>`, apply the DNS records Fly prints, verify certificate
issuance, then add the new hostname to the Maps key referrer allow-list. No custom
domain or dedicated IPv4 address is needed for the initial deployment.

## Failure Handling and Rollback

- An unstaged graph artifact fails the Docker build through the explicit file check.
- A missing or invalid graph artifact makes FastAPI exit at startup; `/api/health`
  never becomes ready, so Fly Proxy does not route the Machine as healthy.
- An OOM or unexpected exit is visible in Fly logs and Machine restart state. Keep
  8GB until real route requests prove a smaller size is safe.
- A bad release can roll back to the preceding immutable Fly image, which restores
  its matching application code and graph artifact together. A rolling update of
  the one Machine has a cold-start outage by design. There is no database, volume,
  migration, or mutable user data to repair.
- If the first post-idle request errors, times out, or the Fly Proxy does not hold
  it through the measured startup time, do not add a keepalive or retry layer. Set
  one warm Machine and re-evaluate its cost, or reconsider the host; this
  scale-to-zero design is then not acceptable as written.
- No silent fallback loads a different graph: the health response's
  `artifact_revision` is the deployment diagnostic.

## Deployment and Verification

1. From the isolated release worktree, install the test environment with
   `uv sync --extra dev --extra bulk`; the repository's unmarked catalog tests
   require the bulk `osmium` extra. Run Ruff, pytest, frontend type checks, unit
   tests, and the Vite production build.
2. Stage the intended local graph as `pound/artifacts/england.pkl` in the worktree.
   Confirm `git check-ignore` reports it ignored and `git status` does not stage it.
   Load and record `$expected_revision` with the command above, then record it with
   the artifact build/release notes.
3. Log into Fly, choose an available suffix, and create the unique app with
   `fly launch --no-deploy --ha=false --region sjc --name towpath-<unique-suffix> \
   --no-db --no-redis --no-object-storage --no-github-workflow \
   --dockerfile Dockerfile`. Preserve the repository Dockerfile; `fly launch` may
   create `fly.toml` but must not replace its existing multi-stage Docker build.
   Replace the generated config with the configuration above, run
   `fly config validate --strict`, and commit all tracked deployment files. Before
   deploying, require `test -z "$(git status --porcelain)"`; the ignored artifact
   is checked separately and must not excuse other uncommitted changes.
4. Create the restricted Maps browser key for the generated Fly hostname. Export
   the three Vite values and run the exact `fly deploy --ha=false --build-arg …`
   command above; the committed 10-minute wait timeout applies.
5. Request `https://<app>.fly.dev/api/health` first; this starts the Machine if it
   stopped. Then run `fly ssh console -C 'find /app -path
   "*/pound/artifacts/england.pkl" -type f -print'`; it must print only
   `/app/pound/artifacts/england.pkl`, not a second copy in `.venv`. Confirm the
   health response is `status: healthy` and its artifact revision equals
   `$expected_revision`. Separately request `http://<app>.fly.dev/api/health` and
   confirm a 3xx redirect to the HTTPS URL.
6. Run the README's Bletchley Park to Black Prince Holidays, Stoke Hammond manual
   browser acceptance check, including map, transfer, and canal overlays. Do not
   substitute `/api/health` for this check: it does not surface a canal-overlay
   geometry failure.
7. Verify `fly machines list` shows exactly one Machine. After several idle
   minutes, confirm it stops; then make exactly one request:

   ```bash
   curl --fail --show-error --silent --output /dev/null --max-time 300 \
     --write-out 'status=%{http_code} elapsed=%{time_total}s\n' \
     https://<app>.fly.dev/api/health
   ```

   Record its status and elapsed time. An error or timeout fails scale-to-zero
   acceptance even if a later retry succeeds; set one warm Machine or reconsider
   the host. Inspect logs and peak memory after a real route. Treat repeated restart
   or OOM events as a failed deployment.
8. Review the Fly month-to-date bill after initial use and the Google Maps billing
   dashboard before sharing more broadly.

## Deferred Work

- The optional catalog artifact and catalog endpoints
- Custom domain purchase and DNS
- GitHub Actions or any other CI deployment
- A volume-backed artifact update path
- More than one Machine, high availability, another region, or autoscaling
