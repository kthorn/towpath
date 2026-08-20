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
