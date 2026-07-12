import pickle
from pathlib import Path
from unittest.mock import patch

import networkx as nx
import pytest
from fastapi.testclient import TestClient

from pound.graph.artifact import load_artifact, save_artifact
from pound.web.app import create_app
from pound.web.config import WebSettings


def _settings(artifact_path: Path, static_dir: Path) -> WebSettings:
    return WebSettings(artifact_path=artifact_path, static_dir=static_dir)


def _write_blob(path: Path, blob: object) -> None:
    with path.open("wb") as artifact_file:
        pickle.dump(blob, artifact_file)


def test_settings_from_env_requires_artifact_path(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("POUND_ARTIFACT_PATH", raising=False)

    with pytest.raises(RuntimeError, match="POUND_ARTIFACT_PATH"):
        WebSettings.from_env()


def test_settings_from_env_reads_paths_and_tuning(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("POUND_ARTIFACT_PATH", "/tmp/graph.pkl")
    monkeypatch.setenv("POUND_STATIC_DIR", "/tmp/client")
    monkeypatch.setenv("POUND_CANDIDATE_POOL_SIZE", "30")
    monkeypatch.setenv("POUND_GOOGLE_DESTINATION_LIMIT", "12")
    monkeypatch.setenv("POUND_MINIMUM_CANDIDATE_SPACING_M", "125.5")

    settings = WebSettings.from_env()

    assert settings == WebSettings(
        artifact_path=Path("/tmp/graph.pkl"),
        static_dir=Path("/tmp/client"),
        candidate_pool_size=30,
        google_destination_limit=12,
        minimum_candidate_spacing_m=125.5,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidate_pool_size", 0),
        ("google_destination_limit", -1),
        ("minimum_candidate_spacing_m", -0.1),
    ],
)
def test_settings_reject_invalid_tuning(field: str, value: int | float, tmp_path: Path):
    values = {"artifact_path": tmp_path / "graph.pkl", "static_dir": tmp_path / "static"}
    values[field] = value

    with pytest.raises(ValueError, match=field):
        WebSettings(**values)


def test_startup_reports_missing_artifact_path(tmp_path: Path):
    artifact = tmp_path / "missing.pkl"
    app = create_app(_settings(artifact, tmp_path / "missing-static"))

    with pytest.raises(RuntimeError, match=str(artifact)) as exc_info:
        with TestClient(app):
            pass

    assert isinstance(exc_info.value.__cause__, FileNotFoundError)


def test_startup_reports_invalid_pickle(tmp_path: Path):
    artifact = tmp_path / "invalid.pkl"
    artifact.write_text("not a pickle")
    app = create_app(_settings(artifact, tmp_path / "missing-static"))

    with pytest.raises(RuntimeError, match=str(artifact)) as exc_info:
        with TestClient(app):
            pass

    assert exc_info.value.__cause__ is not None


def test_startup_reports_malformed_artifact_wrapper(tmp_path: Path):
    artifact = tmp_path / "malformed.pkl"
    _write_blob(artifact, ["not", "an", "artifact", "mapping"])
    app = create_app(_settings(artifact, tmp_path / "missing-static"))

    with pytest.raises(RuntimeError) as exc_info:
        with TestClient(app):
            pass

    assert str(artifact) in str(exc_info.value)
    assert "load" in str(exc_info.value).lower()
    assert isinstance(exc_info.value.__cause__, TypeError)


@pytest.mark.parametrize(
    ("blob", "missing"),
    [
        ({"metadata": {"artifact_revision": "rev"}}, "graph"),
        ({"graph": nx.Graph()}, "metadata"),
    ],
)
def test_startup_rejects_incomplete_artifact(
    tmp_path: Path, blob: dict[str, object], missing: str
):
    artifact = tmp_path / "incomplete.pkl"
    _write_blob(artifact, blob)
    app = create_app(_settings(artifact, tmp_path / "missing-static"))

    with pytest.raises(RuntimeError, match=rf"{artifact}.*{missing}"):
        with TestClient(app):
            pass


@pytest.mark.parametrize("revision", [None, ""])
def test_startup_rejects_missing_or_falsey_revision(tmp_path: Path, revision: str | None):
    artifact = tmp_path / "revisionless.pkl"
    _write_blob(artifact, {"graph": nx.Graph(), "metadata": {"artifact_revision": revision}})
    app = create_app(_settings(artifact, tmp_path / "missing-static"))

    with pytest.raises(RuntimeError, match=rf"{artifact}.*artifact_revision"):
        with TestClient(app):
            pass


def test_startup_attaches_artifact_state_and_loads_once(tmp_path: Path):
    artifact = tmp_path / "graph.pkl"
    graph = nx.Graph()
    graph.add_node(7)
    save_artifact(graph, artifact, {"artifact_revision": "revision-7", "source": "test"})
    settings = _settings(artifact, tmp_path / "missing-static")
    app = create_app(settings)

    with patch("pound.web.app.load_artifact", wraps=load_artifact) as load:
        with TestClient(app) as client:
            assert app.state.graph.nodes == graph.nodes
            assert app.state.metadata["source"] == "test"
            assert app.state.artifact_revision == "revision-7"
            assert app.state.settings is settings
            assert client.get("/api/health").json() == {
                "status": "healthy",
                "artifact_revision": "revision-7",
            }
            client.get("/api/health")

    load.assert_called_once_with(artifact)
