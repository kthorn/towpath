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
    assert "!pound/artifacts/england.pkl" in dockerignore
    assert ".env*" in dockerignore
    assert "web/.env*" in dockerignore
    assert ".pi-subagents" in dockerignore
    assert ".pi/subagents" in dockerignore
    assert "scripts/local" in dockerignore
    assert ".pi/subagents/" in gitignore
    assert wheel["packages"] == ["pound"]
    assert wheel["exclude"] == ["pound/artifacts/**"]


def test_fly_configuration_matches_the_single_machine_scale_to_zero_contract():
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
        "min_machines_running": 0,
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
