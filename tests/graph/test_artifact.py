import json
import pickle
from pathlib import Path
from uuid import UUID

import pound.graph.artifact as artifact_module
from pound.graph.artifact import load_artifact, save_artifact
from pound.graph.build import build_graph
from pound.ingest.overpass import parse
from tests.fixtures import oxford_fixture_path


def _graph():
    with open(oxford_fixture_path()) as f:
        return build_graph(parse(json.load(f)["elements"], None))


def test_artifact_round_trips(tmp_path: Path):
    g = _graph()
    meta = {
        "source": "overpass",
        "fetched_at": "2026-06-21T12:00:00Z",
        "built_at": "2026-06-22T10:00:00Z",
        "version": 1,
    }
    art = tmp_path / "graph.pkl"
    save_artifact(g, art, meta)
    loaded_g, loaded_meta = load_artifact(art)
    assert loaded_g.number_of_edges() == g.number_of_edges()
    assert loaded_meta["source"] == "overpass"
    assert loaded_meta["version"] == 1


def test_save_and_load_preserves_embedded_gazetteer(tmp_path: Path):
    g = _graph()
    g.graph["gazetteer"] = {"Oxford": (51.75, -1.26)}
    art = tmp_path / "g.pkl"
    save_artifact(g, art, {"source": "overpass", "fetched_at": "t", "version": 1})
    loaded_g, _ = load_artifact(art)
    assert loaded_g.graph["gazetteer"] == {"Oxford": (51.75, -1.26)}


def test_save_artifact_adds_revision_when_missing(tmp_path: Path):
    art = tmp_path / "g.pkl"

    save_artifact(_graph(), art, {"source": "overpass"})

    _, meta = load_artifact(art)
    UUID(meta["artifact_revision"])


def test_save_artifact_preserves_explicit_revision_without_generating_one(
    tmp_path: Path, monkeypatch
):
    art = tmp_path / "g.pkl"
    monkeypatch.setattr(
        artifact_module,
        "uuid4",
        lambda: (_ for _ in ()).throw(AssertionError("uuid4 should not be called")),
    )

    save_artifact(_graph(), art, {"source": "overpass", "artifact_revision": "revision-1"})

    _, meta = load_artifact(art)
    assert meta["artifact_revision"] == "revision-1"


def test_repeated_loads_return_same_persisted_revision(tmp_path: Path):
    art = tmp_path / "g.pkl"
    save_artifact(_graph(), art, {"source": "overpass"})

    _, first = load_artifact(art)
    _, second = load_artifact(art)

    UUID(first["artifact_revision"])
    assert second["artifact_revision"] == first["artifact_revision"]


def test_load_artifact_accepts_legacy_metadata_without_revision(tmp_path: Path):
    art = tmp_path / "legacy.pkl"
    graph = _graph()
    metadata = {"source": "overpass", "version": 1}
    with open(art, "wb") as f:
        pickle.dump({"graph": graph, "metadata": metadata}, f)

    loaded_graph, loaded_metadata = load_artifact(art)

    assert loaded_graph.number_of_edges() == graph.number_of_edges()
    assert loaded_metadata == metadata
    assert "artifact_revision" not in loaded_metadata
