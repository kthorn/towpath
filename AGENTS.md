# Repository Guidelines

## Project Structure & Module Organization

`pound/` contains the Python package. Keep functionality within the existing domain modules: `ingest/` handles OSM and Overpass input, `graph/` builds and loads routing artifacts, `route/` resolves locations and plans journeys, and `validate/` checks graph integrity. Shared Pydantic models live in `pound/schemas.py`. Tests mirror this layout under `tests/`; reusable sample data belongs in `tests/fixtures/`. Put developer utilities in `scripts/`, design notes in `docs/`, downloaded source data in `pound/data/`, and generated graph files in `pound/artifacts/`.

## Build, Test, and Development Commands

- `uv sync --extra dev` installs the package and development tools.
- `uv run pytest` runs the default test suite without live-network or bulk-ingest cases.
- `uv run pytest --run-network` includes tests that call the Overpass API.
- `uv sync --extra bulk && uv run pytest --run-bulk` installs `pyosmium` and enables bulk tests; `osmium-tool` must also be installed separately.
- `uv run ruff check .` checks formatting-independent style, imports, and common Python errors.
- `uv run pound-ingest build oxford --out pound/artifacts/oxford.pkl` builds a small local artifact for manual testing.

## Native Codex Delegation

Use native Codex sub-agents for independent, bounded exploration, mechanical work, or implementation
that can be verified cheaply. Native sub-agents inherit the current session's model; they do not
select or enforce a separate Luna/Sol profile. Keep architectural decisions, integration, conflict
resolution, and final verification with the primary agent.

Run at most three sub-agents concurrently. Give each worker a precise scope and output contract. For
write tasks, assign non-overlapping files; all native workers share the same workspace, so concurrent
edits to one file are unsafe. Prefer read-only exploration when no edit is required. Do not launch
nested `codex exec` subprocesses solely for model routing, because they cross a separate network and
permissions boundary.

## Coding Style & Naming Conventions

Target Python 3.12 and use four-space indentation. Ruff enforces a 100-character line limit plus `E`, `F`, `I`, `UP`, and `B` rules. Use `snake_case` for modules, functions, variables, and test names; use `PascalCase` for classes and Pydantic models. Add type annotations to public APIs and keep routing deterministic: network access belongs only in ingest code, never on the request-time path.

## Testing Guidelines

Use `pytest`. Name files `test_<subject>.py` and tests `test_<behavior>`. Place tests beside the corresponding domain subtree and use fixtures for compact, reproducible OSM inputs. Mark live API tests with `@pytest.mark.network` and pyosmium/osmium-dependent tests with `@pytest.mark.bulk`. Add regression tests for bug fixes and run the narrow test file before the full default suite.

## Commit & Pull Request Guidelines

Recent history follows Conventional Commit-style subjects such as `feat(route): ...`, `refactor(route): ...`, and `docs: ...`. Keep commits focused, imperative, and scoped when useful. Pull requests should explain the behavioral change, list verification commands, link relevant issues or design documents, and call out artifact or data-format changes. Include sample CLI output when changing user-facing commands; screenshots are only needed for visual changes.

## Security & Data Practices

Do not commit downloaded PBF files, generated artifacts, credentials, or API tokens. Treat graph validation reports as authoritative and record confirmed topology corrections in `pound/data/overrides.json` rather than patching generated output.
