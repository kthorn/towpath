# Repository Guidelines

## Project Structure & Module Organization

`packages/pound-core/src/pound/` contains runtime Python code, `packages/pound-build/src/pound_build/` contains offline build tooling, and `packages/pound-web/src/pound_web/` contains the FastAPI application. Keep functionality within the existing domain modules: ingest handles OSM and Overpass input, graph builds and loads routing artifacts, route resolves locations and plans journeys, and validate checks graph integrity. Shared Pydantic models live in `packages/pound-core/src/pound/schemas.py`. Tests mirror each package under its `tests/` directory; reusable sample data belongs in package fixtures. Put developer utilities in `scripts/`, design notes in `docs/`, downloaded source data in `data/`, and generated graph files in `artifacts/`.

## Build, Test, and Development Commands

- `uv sync --extra dev` installs the package and development tools.
- `uv run pytest` runs the default test suite without live-network or bulk-ingest cases.
- `uv run pytest --run-network` includes tests that call the Overpass API.
- `uv sync --extra bulk && uv run pytest --run-bulk` installs `pyosmium` and enables bulk tests; `osmium-tool` must also be installed separately.
- `uv run ruff check .` checks formatting-independent style, imports, and common Python errors.
- `uv run pound-ingest build oxford --out artifacts/oxford.pkl` builds a small local artifact for manual testing.

## Coding Style & Naming Conventions

Target Python 3.12 and use four-space indentation. Ruff enforces a 100-character line limit plus `E`, `F`, `I`, `UP`, and `B` rules. Use `snake_case` for modules, functions, variables, and test names; use `PascalCase` for classes and Pydantic models. Add type annotations to public APIs and keep routing deterministic: network access belongs only in ingest code, never on the request-time path.

## Testing Guidelines

Use `pytest`. Name files `test_<subject>.py` and tests `test_<behavior>`. Place tests beside the corresponding domain subtree and use fixtures for compact, reproducible OSM inputs. Mark live API tests with `@pytest.mark.network` and pyosmium/osmium-dependent tests with `@pytest.mark.bulk`. Add regression tests for bug fixes and run the narrow test file before the full default suite.

## Commit & Pull Request Guidelines

Recent history follows Conventional Commit-style subjects such as `feat(route): ...`, `refactor(route): ...`, and `docs: ...`. Keep commits focused, imperative, and scoped when useful. Pull requests should explain the behavioral change, list verification commands, link relevant issues or design documents, and call out artifact or data-format changes. Include sample CLI output when changing user-facing commands; screenshots are only needed for visual changes.

## Design and Plan Lifecycle

When a design document or specification exists for a change, do not commit its separate
implementation plan. Treat implementation plans as disposable execution aids. Once the change is
implemented in a pull request, move the corresponding design/specification from `docs/plans/` to
`docs/completed/` in that same pull request. Do not commit temporary review transcripts; delete them
after their actionable feedback has been incorporated.

## Security & Data Practices

Do not commit downloaded PBF files, generated artifacts, credentials, or API tokens. Treat graph validation reports as authoritative and record confirmed topology corrections in `data/overrides.json` rather than patching generated output.
