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


def _features_with_pois():
    raw = json.loads(Path(oxford_fixture_path()).read_text())
    features = parse(raw["elements"], None, osm_timestamp=raw["osm3s"]["timestamp_osm_base"])
    poi_raw = json.loads(Path("tests/fixtures/poi_overpass_sample.json").read_text())
    poi_features = parse(poi_raw["elements"], None)
    return features.model_copy(
        update={
            "poi_candidates": poi_features.poi_candidates,
            "poi_ingest_report": poi_features.poi_ingest_report,
        }
    )


def test_build_oxford_artifact_has_connected_graph_and_gazetteer(tmp_path, monkeypatch):
    try:
        feats = _features_with_pois()
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(f"Failed to load Oxford fixture: {e}") from e
    monkeypatch.setattr(cli, "fetch_oxford", lambda: feats)
    out = tmp_path / "oxford.pkl"
    rc = cli.main(["build", "oxford", "--out", str(out)])
    assert rc == 0
    assert out.exists()
    artifact = load_artifact(out)

    assert artifact.metadata["artifact_revision"]
    v = artifact.metadata["validation"]
    assert v["derelict_edges"] == 0
    assert v["self_loops"] == 0
    assert "gazetteer" in artifact.graph.graph
    assert "Oxford" in artifact.graph.graph["gazetteer"]
    assert "Hayfield" in artifact.graph.graph["gazetteer"]
    assert v["named_nodes_in_graph"] >= 2  # Oxford + Hayfield named on nodes
    assert v["place_nodes_in_gazetteer"] >= 3  # Oxford, Hayfield, Marston
    identities = {(poi.osm_id, poi.kind) for poi in artifact.pois}
    assert (2001, "water_point") in identities
    assert not {"toilets", "shower", "drinking_water"} & {poi.kind for poi in artifact.pois}
    assert all("toilets" not in poi.source_tags for poi in artifact.pois)
    summary = artifact.metadata["poi_summary"]
    assert summary["by_category"]["canal_service"] >= 1
    assert summary["by_kind"]["water_point"] == 1
