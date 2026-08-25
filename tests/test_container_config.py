import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_container_configuration_stages_only_the_deployment_artifact():
    dockerfile = (ROOT / "Dockerfile").read_text()
    dockerignore = (ROOT / ".dockerignore").read_text().splitlines()
    gitignore = (ROOT / ".gitignore").read_text().splitlines()
    wheel = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["hatch"]["build"][
        "targets"
    ]["wheel"]

    assert (
        "COPY pound/ pound/\n"
        "RUN test -f pound/artifacts/england.pkl\n"
        "RUN uv sync --locked --no-dev --no-editable"
    ) in dockerfile
    assert (
        'RUN test -n "$VITE_GOOGLE_MAPS_API_KEY" \\\n'
        '    && test -n "$VITE_GOOGLE_MAP_ID" \\\n'
        "    && npm run build"
    ) in dockerfile
    assert "pound/artifacts" not in dockerignore
    assert "pound/artifacts/*" in dockerignore
    data_rules = [rule for rule in dockerignore if rule.lstrip("!").startswith("pound/data")]
    assert data_rules == ["pound/data/*", "!pound/data/boat-hire-enrichment.csv"]
    assert (
        'ENV PATH="/app/.venv/bin:${PATH}" \\\n'
        "    POUND_STATIC_DIR=/app/web/dist \\\n"
        "    POUND_BOAT_HIRE_ENRICHMENT_PATH=/app/pound/data/boat-hire-enrichment.csv"
    ) in dockerfile
    assert "!pound/artifacts/england.pkl" in dockerignore
    assert ".env*" in dockerignore
    assert "web/.env*" in dockerignore
    assert ".pi-subagents" in dockerignore
    assert ".pi/subagents" in dockerignore
    assert "scripts/local" in dockerignore
    assert ".pi/subagents/" in gitignore
    assert wheel["packages"] == ["pound"]
    assert wheel["exclude"] == ["pound/artifacts/**"]


def test_fly_configuration_keeps_the_single_machine_warm():
    fly = tomllib.loads((ROOT / "fly.toml").read_text())

    assert set(fly) == {"app", "primary_region", "build", "deploy", "env", "http_service", "vm"}
    assert re.fullmatch(r"towpath-[a-z0-9-]+", fly["app"])
    assert fly["primary_region"] == "sjc"
    assert fly["build"] == {"dockerfile": "Dockerfile"}
    assert fly["deploy"] == {"strategy": "rolling", "wait_timeout": "10m"}
    assert fly["env"] == {"POUND_ARTIFACT_PATH": "/app/pound/artifacts/england.pkl"}
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
