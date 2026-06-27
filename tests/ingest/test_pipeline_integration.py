"""PR1 integration gate (design OQ-D5): pound-ingest build oxford -> artifact.

No real PBF, no pyosmium, no osmium-tool needed. Asserts the production pipeline
code (build -> locks -> validate -> save) over the real built artifact path.
"""

import json
from pathlib import Path

from pound.graph.artifact import load_artifact
from pound.ingest import cli
from pound.ingest.overpass import parse
from tests.fixtures import oxford_fixture_path


def test_build_oxford_artifact_has_connected_graph_and_gazetteer(tmp_path, monkeypatch):
    raw = json.loads(Path(oxford_fixture_path()).read_text())
    feats = parse(raw["elements"], None, osm_timestamp=raw["osm3s"]["timestamp_osm_base"])
    monkeypatch.setattr(cli, "fetch_oxford", lambda: feats)
    out = tmp_path / "oxford.pkl"
    rc = cli.main(["build", "oxford", "--out", str(out), "--max-unresolved-snaps", "0"])
    assert rc == 0
    assert out.exists()
    g, meta = load_artifact(out)

    v = meta["validation"]
    assert v["derelict_edges"] == 0
    assert v["self_loops"] == 0
    assert len(v["tolerance_snaps_unresolved"]) == 0  # pendant resolved by override
    assert v["tolerance_snaps_used"]  # at least the resolved pendant
    assert "gazetteer" in g.graph
    assert "Oxford" in g.graph["gazetteer"]
    assert "Hayfield" in g.graph["gazetteer"]
    assert v["named_nodes_in_graph"] >= 2  # Oxford + Hayfield named on nodes
    assert v["place_nodes_in_gazetteer"] >= 3  # Oxford, Hayfield, Marston


def test_build_oxford_gate_fails_when_pendant_left_unresolved(tmp_path, monkeypatch):
    raw = json.loads(Path(oxford_fixture_path()).read_text())
    feats = parse(raw["elements"], None, osm_timestamp=raw["osm3s"]["timestamp_osm_base"])
    monkeypatch.setattr(cli, "fetch_oxford", lambda: feats)
    out = tmp_path / "oxford.pkl"
    # absent overrides => the pendant snap is built but unresolved => gate fires.
    rc = cli.main(
        [
            "build",
            "oxford",
            "--out",
            str(out),
            "--max-unresolved-snaps",
            "0",
            "--overrides",
            str(tmp_path / "absent.json"),
        ]
    )
    assert rc != 0
    assert not out.exists()
