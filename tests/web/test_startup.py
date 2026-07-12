import pickle
from pathlib import Path
from unittest.mock import patch

import networkx as nx
import pytest
from fastapi.testclient import TestClient

from pound.graph.artifact import InvalidArtifactError, load_artifact, save_artifact
from pound.graph.spatial import GraphSpatialIndex
from pound.web.app import _load_web_artifact, create_app
from pound.web.config import WebSettings
from tests.web.conftest import artifact_metadata


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

    with pytest.raises(RuntimeError, match=str(artifact)) as exc_info:
        _load_web_artifact(_settings(artifact, tmp_path / "missing-static"))

    assert isinstance(exc_info.value.__cause__, InvalidArtifactError)
    assert isinstance(exc_info.value.__cause__.__cause__, FileNotFoundError)


def test_startup_reports_invalid_pickle(tmp_path: Path):
    artifact = tmp_path / "invalid.pkl"
    artifact.write_text("not a pickle")

    with pytest.raises(RuntimeError, match=str(artifact)) as exc_info:
        _load_web_artifact(_settings(artifact, tmp_path / "missing-static"))

    assert exc_info.value.__cause__ is not None


def test_startup_reports_malformed_artifact_wrapper(tmp_path: Path):
    artifact = tmp_path / "malformed.pkl"
    _write_blob(artifact, ["not", "an", "artifact", "mapping"])

    with pytest.raises(RuntimeError) as exc_info:
        _load_web_artifact(_settings(artifact, tmp_path / "missing-static"))

    assert str(artifact) in str(exc_info.value)
    assert "load" in str(exc_info.value).lower()
    assert "rebuild" in str(exc_info.value).lower()
    assert isinstance(exc_info.value.__cause__, InvalidArtifactError)


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

    with pytest.raises(RuntimeError, match=rf"{artifact}.*{missing}.*[Rr]ebuild"):
        _load_web_artifact(_settings(artifact, tmp_path / "missing-static"))


@pytest.mark.parametrize("revision", [None, ""])
def test_startup_rejects_missing_or_falsey_revision(tmp_path: Path, revision: str | None):
    artifact = tmp_path / "revisionless.pkl"
    metadata = artifact_metadata("temporary")
    metadata["artifact_revision"] = revision
    _write_blob(artifact, {"graph": nx.Graph(), "pois": [], "metadata": metadata})

    with pytest.raises(RuntimeError, match=rf"{artifact}.*artifact_revision.*[Rr]ebuild"):
        _load_web_artifact(_settings(artifact, tmp_path / "missing-static"))


def test_startup_attaches_artifact_state_and_loads_once(tmp_path: Path):
    artifact = tmp_path / "graph.pkl"
    graph = nx.Graph(marker={"stable": True})
    save_artifact(graph, [], artifact, artifact_metadata("revision-7"))
    settings = _settings(artifact, tmp_path / "missing-static")
    app = create_app(settings)

    with (
        patch("pound.web.app.load_artifact", wraps=load_artifact) as load,
        patch("pound.web.app.GraphSpatialIndex", wraps=GraphSpatialIndex) as build_index,
    ):
        with TestClient(app) as client:
            assert app.state.graph.nodes == graph.nodes
            assert app.state.artifact.graph is app.state.graph
            assert app.state.artifact.pois == ()
            assert app.state.pois is app.state.artifact.pois
            assert app.state.metadata["source"] == "test"
            assert app.state.metadata is app.state.artifact.metadata
            assert app.state.artifact_revision == "revision-7"
            assert app.state.settings is settings
            assert isinstance(app.state.spatial_index, GraphSpatialIndex)
            assert client.get("/api/health").json() == {
                "status": "healthy",
                "artifact_revision": "revision-7",
            }
            client.get("/api/health")

    load.assert_called_once_with(artifact)
    build_index.assert_called_once_with(app.state.graph)


def test_startup_does_not_mutate_loaded_artifact_fields(tmp_path: Path):
    artifact_path = tmp_path / "graph.pkl"
    graph = nx.Graph(marker={"stable": True})
    metadata = artifact_metadata("revision-immutable")
    save_artifact(graph, [], artifact_path, metadata)
    loaded = load_artifact(artifact_path)

    with patch("pound.web.app.load_artifact", return_value=loaded):
        with TestClient(create_app(_settings(artifact_path, tmp_path / "static"))):
            pass

    assert loaded.graph.graph == {"marker": {"stable": True}}
    assert loaded.metadata == metadata
    assert loaded.pois == ()
