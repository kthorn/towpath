# GitHub Actions CI Design

**Status:** Refined

## Goal

Add minimal GitHub Actions CI that validates coordinated Python, Node, and dependency updates on pull requests and after merges to `main`.

## Scope

Add one workflow at `.github/workflows/ci.yml`. It will run two independent jobs:

- Python 3.14 tests and linting.
- Node.js 24 web checks, unit tests, and production build.

The same change updates the Docker web-builder image from Node.js 22 to Node.js 24, resolving issue #66, adds GitHub Actions to Dependabot's existing update configuration, and extends `tests/test_container_config.py` to enforce matching CI and Docker runtime pins. The workflow will not build the Docker image, run live-network tests, deploy, publish artifacts, or maintain a runtime-version matrix. Runtime versions are intentionally pinned in both CI and `Dockerfile`; future runtime migrations must update them together. The `requires-python >=3.12` compatibility floor and Ruff's Python 3.12 syntax target remain unchanged because they are broader source-compatibility policy, not deployment runtime pins.

## Triggers and permissions

The workflow runs for every pull request and every push to `main`. It declares `contents: read` as its only permission. Its concurrency group combines the workflow name and Git ref; `cancel-in-progress` is true only for pull requests, so every merged commit retains a completed `main` result. Each job has a 15-minute timeout.

The workflow uses `actions/checkout`, `actions/setup-python`, `astral-sh/setup-uv`, and `actions/setup-node`. All actions are pinned to full commit SHAs with release-version comments. setup-uv explicitly sets `enable-cache: true`; setup-node sets `cache: npm` and `cache-dependency-path: web/package-lock.json`. `.github/dependabot.yml` gains a `github-actions` ecosystem entry with the repository's existing weekly schedule and cooldown policy so these SHA pins receive updates.

## Python job

The Python job runs from the repository root on `ubuntu-latest`. `actions/setup-python` selects Python 3.14, and `UV_PYTHON=3.14` makes uv enforce the same interpreter. The job installs the required system executable with `sudo apt-get update && sudo apt-get install -y osmium-tool`, verifies `osmium` is on `PATH`, then runs:

```console
uv sync --locked --extra dev --extra bulk
UV_NO_SYNC=1 uv run pytest --run-bulk
UV_NO_SYNC=1 uv run ruff check .
```

`--locked` rejects project/lockfile drift during installation; `UV_NO_SYNC=1` implies frozen operation and prevents either `uv run` command from changing the environment or lockfile. The network suite remains excluded. Installing the bulk extra makes the current unmarked osmium-dependent tests pass, while `--run-bulk` additionally enables the marked fixture-scale bulk tests. Issue #65 tracks restoring the documented dev-only default suite.

## Web job

The web job runs on `ubuntu-latest` with Node.js 24. From `web/`, it runs:

```console
npm ci
npm run check
npm test -- --run
npm run build
```

No Vite environment placeholders are set: the application config already supplies safe build defaults, and job-level `VITE_` values would alter unit-test behavior. Browser-based Playwright smoke and navigation tests remain out of scope because they exercise browser installation and integration behavior rather than the runtime/dependency compatibility gate requested here; their TypeScript files are therefore not checked by this workflow.

## Version consistency

The workflow spells its setup inputs exactly as `node-version: "24"` and `python-version: "3.14"`, and sets `UV_PYTHON: "3.14"`. `tests/test_container_config.py` uses the repository's existing exact-substring style to assert those strings alongside `node:24-alpine` and `python:3.14-slim` in `Dockerfile`. The workflow and test change together, making coordinated runtime migrations an enforced repository contract rather than documentation only.

## Failure behavior

Each command fails its job immediately. The Python and web jobs run independently so both results remain visible when one fails. No fallback runtime or dependency installation path is allowed. The 15-minute job timeout bounds an unexpected hang, including failures in the existing process-spawning development-script tests.

## Acceptance criteria

- CI runs on pull requests and pushes to `main`; only superseded pull-request runs are cancelled.
- Python 3.14 is explicitly selected by setup-python and uv, installs locked `dev` and `bulk` dependencies, passes the bulk-enabled non-network test suite, and passes Ruff without an implicit uv sync.
- Node.js 24 is used consistently by CI and the Docker web-builder; it installs the committed lockfile, passes Svelte checks and Vitest, and produces a Vite build.
- Automated configuration tests fail if either CI runtime pin diverges from its Dockerfile base.
- Workflow permissions are read-only and actions are pinned to full SHAs.
- Dependabot maintains the workflow's action pins.
- No Docker image, deployment, live-network request, or Playwright browser suite runs in CI.
- During implementation, this design moves from `docs/plans/` to `docs/completed/` in the same pull request.
