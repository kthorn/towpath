# Fly Redeployment Runbook Design

> **Status:** approved for drafting
> **Scope:** operate the existing graph-only Fly deployment without changing its hosting model

## Goal

Provide one concise operator runbook for redeploying Towpath at
`https://towpath-4772e4a8.fly.dev` after code, tracked data, graph-artifact, or
configuration changes.

## Design

Create `docs/fly-runbook.md` as the operational source of truth. It will use the
existing `fly.toml` app name and preserve one warm `sjc` `shared-cpu-4x` / 8GB
Machine with `min_machines_running = 1`.

The runbook will distinguish these release paths:

1. **Full source redeploy** for code or tracked-data changes. It requires the
   ignored `pound/artifacts/england.pkl` plus the three Vite build variables, then
   uses `fly deploy --ha=false`.
2. **Artifact redeploy** for a new graph. It stages the ignored graph artifact,
   records its revision, and follows the same full source deploy path.
3. **Configuration-only redeploy** for `fly.toml` changes. It reuses the current
   Fly image so no browser configuration needs to be supplied.
4. **Rollback** by selecting a prior image and deploying it with the current
   configuration.

Every path ends with one shared verification procedure: strict local config
validation, exactly one started/passing `sjc` Machine with the documented size and
minimum, and one no-retry HTTPS health response whose artifact revision matches the
intended graph.

## Security and Scope Boundaries

- Never put Google build values, credentials, or the ignored graph artifact in Git.
- Treat the generated `fly.dev` hostname as canonical; do not document the shared
  IPv4 address as an endpoint.
- Do not add a custom domain, CI deployment, volume, database, additional Machine,
  autoscaling, retry layer, or scale-to-zero behavior.
- Keep the completed Fly deployment design as historical rationale; the new file is
  an operator procedure, not a second design document.
