from copy import deepcopy

import networkx as nx
from pound.artifact import RuntimeArtifact
from pound.models import WayDimensions
from pound_build.artifact import prepare_artifact, write_artifact
from pound_build.ingest.ir import PointOfInterest

from scripts.compare_build_artifacts import compare_artifacts, main


def _graph() -> nx.Graph:
    graph = nx.Graph()
    graph.add_node(
        2,
        lat=51.7520,
        lon=-1.2560,
        osm_node_ids={"102", "101"},
        movable_bridge_ids=(),
        turning_point=False,
        turning_max_length_m=None,
    )
    graph.add_node(
        1,
        lat=51.7520,
        lon=-1.2577,
        osm_node_ids={"100"},
        movable_bridge_ids=(),
        turning_point=False,
        turning_max_length_m=None,
    )
    graph.add_edge(
        2,
        1,
        osm_way_id=200,
        name="Oxford Canal",
        kind="canal",
        length_m=117.0,
        dimensions=WayDimensions(),
        has_tunnel=False,
        has_movable_bridge=False,
        locks=0,
        geometry=[(51.7520, -1.2560), (51.7520, -1.2577)],
        movable_bridge_ids=(),
        tunnel_restrictions=(),
        access_caveats=(),
    )
    return graph


def _poi(**overrides) -> PointOfInterest:
    values = {
        "osm_type": "node",
        "osm_id": 300,
        "category": "canal_service",
        "kind": "water_point",
        "name": "Tap",
        "lat": 51.7520,
        "lon": -1.2568,
        "source_tags": {"amenity": "drinking_water"},
        "geometry_source": "point",
        "nearest_waterway_distance_m": 0.0,
        "nearest_edge": (1, 2),
        "nearest_node_uid": 2,
        "projected_lat": 51.7520,
        "projected_lon": -1.2568,
    }
    values.update(overrides)
    return PointOfInterest.model_validate(values)


def _metadata(**overrides) -> dict:
    values = {
        "artifact_revision": "revision-before",
        "source": "fixture",
        "fetched_at": "2026-07-12T00:00:00Z",
        "built_at": "2026-07-12T01:00:00Z",
        "validation": {"components": {2, 1}},
        "poi_summary": {"retained": 1, "by_kind": {"water_point": 1}},
    }
    values.update(overrides)
    return values


def _artifact(
    *, graph: nx.Graph | None = None, pois: tuple[PointOfInterest, ...] | None = None, **metadata
) -> RuntimeArtifact:
    return prepare_artifact(graph or _graph(), pois or (_poi(),), {}, _metadata(**metadata))


def _write(artifact: RuntimeArtifact, path) -> None:
    write_artifact(artifact, path)


def test_compare_artifacts_ignores_only_revision_and_build_time():
    assert (
        compare_artifacts(
            _artifact(), _artifact(artifact_revision="revision-after", built_at="later")
        )
        == []
    )


def test_compare_artifacts_reports_changed_edge_and_poi():
    before = _artifact()
    graph = deepcopy(before.graph)
    graph.edges[1, 2]["name"] = "Changed Canal"
    after = _artifact(graph=graph, pois=(_poi(name="Changed Tap"),))

    mismatches = compare_artifacts(before, after)

    assert any("edges" in mismatch for mismatch in mismatches)
    assert any("pois" in mismatch for mismatch in mismatches)


def test_comparison_cli_is_silent_for_parity(tmp_path, capsys):
    artifact = _artifact()
    _write(artifact, tmp_path / "before.pkl")
    _write(_artifact(artifact_revision="revision-after", built_at="later"), tmp_path / "after.pkl")

    assert main([str(tmp_path / "before.pkl"), str(tmp_path / "after.pkl")]) == 0
    assert capsys.readouterr().err == ""


def test_comparison_cli_reports_mismatches_to_stderr(tmp_path, capsys):
    before = _artifact()
    graph = deepcopy(before.graph)
    graph.edges[1, 2]["name"] = "Changed Canal"
    _write(before, tmp_path / "before.pkl")
    _write(_artifact(graph=graph), tmp_path / "after.pkl")

    assert main([str(tmp_path / "before.pkl"), str(tmp_path / "after.pkl")]) == 1
    assert "graph edges differ" in capsys.readouterr().err
