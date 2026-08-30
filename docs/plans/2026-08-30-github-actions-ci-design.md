# GitHub Actions CI Design

**Status:** Draft

## Goal

Add minimal GitHub Actions CI that validates coordinated Python, Node, and dependency updates on pull requests and after merges to `main`.

## Scope

Add one workflow at `.github/workflows/ci.yml`. It will run two independent jobs:

- Python 3.14 tests and linting.
- Node.js 24 web checks, unit tests, and production build.

The workflow will not build the Docker image, run live-network tests, deploy, publish artifacts, or maintain a runtime-version matrix. Runtime versions are intentionally pinned in CI and will be updated alongside `Dockerfile` during future coordinated migrations.

## Triggers and permissions

The workflow runs for every pull request and every push to `main`. It declares `contents: read` as its only permission and uses concurrency cancellation so a newer run supersedes an older run for the same branch or pull request.

All third-party GitHub Actions are pinned to full commit SHAs with release-version comments.

## Python job

The Python job runs on `ubuntu-latest` with Python 3.14 and the repository's locked dependencies. It installs `osmium-tool`, synchronizes the `dev` and `bulk` extras, then runs:

```console
uv run pytest --run-bulk
uv run ruff check .
```

The network suite remains excluded. Including bulk dependencies keeps this initial CI workflow green while issue #65 tracks restoring the documented dev-only default suite.

## Web job

The web job runs on `ubuntu-latest` with Node.js 24. From `web/`, it runs:

```console
npm ci
npm run check
npm test -- --run
npm run build
```

The build receives non-secret placeholder values for the required Vite Google Maps variables. Browser-based Playwright smoke and navigation tests remain out of scope because they exercise browser installation and integration behavior rather than the runtime/dependency compatibility gate requested here.

## Failure behavior

Each command fails its job immediately. The Python and web jobs run independently so both results remain visible when one fails. No fallback runtime or dependency installation path is allowed.

## Acceptance criteria

- CI runs on pull requests and pushes to `main`.
- Python 3.14 installs locked `dev` and `bulk` dependencies, passes the bulk-enabled non-network test suite, and passes Ruff.
- Node.js 24 installs the committed lockfile, passes Svelte checks and Vitest, and produces a Vite build.
- Workflow permissions are read-only and actions are pinned to full SHAs.
- No Docker image, deployment, live-network request, or Playwright browser suite runs in CI.
