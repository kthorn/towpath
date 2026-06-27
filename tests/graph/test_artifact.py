import json
from pathlib import Path

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
