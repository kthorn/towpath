import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_container_configuration_stages_only_runtime_packages_and_data():
    dockerfile = (ROOT / "Dockerfile").read_text()
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    smoke_readme = (ROOT / "web" / "tests" / "smoke" / "README.md").read_text()
    dockerignore = (ROOT / ".dockerignore").read_text().splitlines()

    assert "FROM node:24-alpine AS web-builder" in dockerfile
    assert "FROM python:3.14-slim AS runtime" in dockerfile
    assert 'node-version: "24"' in workflow
    assert 'python-version: "3.14"' in workflow
    assert 'UV_PYTHON: "3.14"' in workflow
    gitignore = (ROOT / ".gitignore").read_text().splitlines()
    wheel = tomllib.loads((ROOT / "packages" / "pound-core" / "pyproject.toml").read_text())[
        "tool"
    ]["hatch"]["build"]["targets"]["wheel"]

    assert "COPY packages/pound-core/ packages/pound-core/" in dockerfile
    assert "COPY packages/pound-web/ packages/pound-web/" in dockerfile
    assert "COPY packages/pound-build" not in dockerfile
    assert "COPY pound/ pound/" not in dockerfile
    assert "pound.web.app" not in dockerfile
    assert "/app/pound/artifacts" not in dockerfile
    assert "RUN uv sync --package pound-web --no-dev --frozen" in dockerfile
    assert "COPY artifacts/ /app/artifacts/" in dockerfile
    assert "COPY data/ /app/data/" in dockerfile
    assert "RUN test -f /app/artifacts/england.pkl" in dockerfile
    assert (
        'RUN test -n "$VITE_GOOGLE_MAPS_API_KEY" \\\n'
        '    && test -n "$VITE_GOOGLE_MAP_ID" \\\n'
        "    && npm run build"
    ) in dockerfile
    assert "artifacts/*" in dockerignore
    assert "!artifacts/england.pkl" in dockerignore
    data_rules = [rule for rule in dockerignore if rule.lstrip("!").startswith("data")]
    assert data_rules == ["data/*", "!data/boat-hire-enrichment.csv"]
    assert "pound/artifacts" not in dockerignore
    assert "pound/data" not in dockerignore
    assert (
        'ENV PATH="/app/.venv/bin:${PATH}" \\\n'
        "    POUND_ARTIFACT_PATH=/app/artifacts/england.pkl \\\n"
        "    POUND_STATIC_DIR=/app/web/dist \\\n"
        "    POUND_BOAT_HIRE_ENRICHMENT_PATH=/app/data/boat-hire-enrichment.csv"
    ) in dockerfile
    assert 'CMD ["uvicorn", "pound_web.app:app"' in dockerfile
    assert "pound.web.app" not in smoke_readme
    assert "/app/pound/artifacts" not in smoke_readme
    assert "POUND_ARTIFACT_PATH='artifacts/england.pkl'" in smoke_readme
    assert "POUND_BOAT_HIRE_ENRICHMENT_PATH='data/boat-hire-enrichment.csv'" in smoke_readme
    assert "artifacts/" in gitignore
    assert "data/*" in gitignore
    assert ".env*" in dockerignore
    assert "web/.env*" in dockerignore
    assert ".pi-subagents" in dockerignore
    assert ".pi/subagents" in dockerignore
    assert "scripts/local" in dockerignore
    assert ".pi/subagents/" in gitignore
    assert wheel["packages"] == ["src/pound"]


def test_fly_configuration_keeps_the_single_machine_warm():
    fly = tomllib.loads((ROOT / "fly.toml").read_text())

    assert set(fly) == {"app", "primary_region", "build", "deploy", "env", "http_service", "vm"}
    assert re.fullmatch(r"towpath-[a-z0-9-]+", fly["app"])
    assert fly["primary_region"] == "sjc"
    assert fly["build"] == {"dockerfile": "Dockerfile"}
    assert fly["deploy"] == {"strategy": "rolling", "wait_timeout": "10m"}
    assert fly["env"] == {"POUND_ARTIFACT_PATH": "/app/artifacts/england.pkl"}
    assert fly["http_service"] == {
        "internal_port": 8000,
        "force_https": True,
        "auto_stop_machines": "stop",
        "auto_start_machines": True,
        "min_machines_running": 1,
        "checks": [
            {
                "method": "GET",
                "path": "/api/health",
                "grace_period": "1m",
                "interval": "15s",
                "timeout": "10s",
            }
        ],
    }
    assert fly["vm"] == [{"cpu_kind": "shared", "cpus": 4, "memory": "8gb"}]
