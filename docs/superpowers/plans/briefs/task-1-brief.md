## Task 1: Scaffold the project (git, pyproject, layout, config)

**Files:**

- Create: `/home/kurtt/pound/.gitignore`
- Create: `/home/kurtt/pound/pyproject.toml`
- Create: `/home/kurtt/pound/README.md`
- Create: `/home/kurtt/pound/pound/__init__.py`
- Create: `/home/kurtt/pound/pound/ingest/__init__.py`
- Create: `/home/kurtt/pound/pound/data/.gitkeep`
- Create: `/home/kurtt/pound/tests/__init__.py`
- Create: `/home/kurtt/pound/tests/conftest.py`
- Create: `/home/kurtt/pound/tests/ingest/__init__.py`
- Test: `tests/test_smoke.py`

**Interfaces:**

- Consumes: nothing
- Produces: an importable `pound` package, a runnable pytest suite with `--run-network` support, ruff config

- [ ] **Step 1: Initialize git**

```bash
cd /home/kurtt/pound
git init
git config user.name "Kurt Thorn"
git config user.email "$(git config --global user.email || echo 'kurtt@example.com')"
```

- [ ] **Step 2: Write `.gitignore`**

Create `/home/kurtt/pound/.gitignore`:

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
.eggs/
build/
dist/

# venvs
.venv/
venv/

# test / coverage
.pytest_cache/
.coverage
htmlcov/

# Large data extracts — never commit the full GB build (design §10)
pound/data/*
!pound/data/.gitkeep

# editor
.vscode/
.idea/
```

- [ ] **Step 3: Write `pyproject.toml`**

Create `/home/kurtt/pound/pyproject.toml`:

```toml
[project]
name = "pound"
version = "0.1.0"
description = "Pound — deterministic routing engine for UK inland waterways"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.11",
    "requests>=2.31",   # offline ingest ONLY; never on the request-time path
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-cov>=5",
    "ruff>=0.6",
]

[project.scripts]
pound-ingest = "pound.ingest.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["pound"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "network: tests that hit the live Overpass API (deselect by default; use --run-network)",
]
addopts = "-ra"
```

- [ ] **Step 4: Write package `__init__.py` files**

Create `/home/kurtt/pound/pound/__init__.py`:

```python
"""Pound — deterministic routing engine for UK inland waterways."""
```

Create `/home/kurtt/pound/pound/ingest/__init__.py`:

```python
"""Offline ingest: turn OSM extracts into a filtered WaterwayFeatures IR."""
```

Create `/home/kurtt/pound/tests/__init__.py` and `/home/kurtt/pound/tests/ingest/__init__.py` as empty files.

Create `/home/kurtt/pound/pound/data/.gitkeep` as an empty file.

- [ ] **Step 5: Write `tests/conftest.py` (network marker handling)**

Create `/home/kurtt/pound/tests/conftest.py`:

```python
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="run tests marked @pytest.mark.network (live Overpass fetch)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-network"):
        return
    skip_network = pytest.mark.skip(reason="network test: pass --run-network to run")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_network)
```

- [ ] **Step 6: Write `README.md`**

Create `/home/kurtt/pound/README.md`:

```markdown
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

```

- [ ] **Step 7: Write the failing smoke test**

Create `/home/kurtt/pound/tests/test_smoke.py`:

```python
def test_package_imports():
    import pound

    assert pound.__doc__


def test_ingest_subpackage_imports():
    from pound import ingest

    assert ingest.__doc__
```

- [ ] **Step 8: Set up the env and run the test**

```bash
cd /home/kurtt/pound
uv sync --extra dev
uv run pytest -q
```

Expected: 2 passed.

- [ ] **Step 9: Lint**

```bash
uv run ruff check .
```

Expected: no errors.

- [ ] **Step 10: Commit**

```bash
cd /home/kurtt/pound
git add -A
git commit -m "chore: scaffold pound package, pyproject, pytest+network marker, ruff"
```

---

