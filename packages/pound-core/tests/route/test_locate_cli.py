from pathlib import Path

import pytest
from pound.artifact import load_artifact
from pound.route import locate_cli

from tests.fixtures import routing_test_graph, write_runtime_artifact


def _build_oxford_artifact(out: Path) -> Path:
    graph, gazetteer = routing_test_graph()
    return write_runtime_artifact(
        graph,
        (),
        out,
        {
            "artifact_revision": "locate-cli-test",
            "source": "fixture",
            "fetched_at": "2026-06-21T12:00:00Z",
            "built_at": "t",
            "validation": {},
            "poi_summary": {},
        },
        gazetteer=gazetteer,
    )


def test_pound_locate_prints_nearest_uid_and_distance(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    # Click exactly on a known node (read from the built graph) -> distance 0.
    graph = load_artifact(Path(art)).graph
    known_uid = next(iter(graph.nodes))
    lat = graph.nodes[known_uid]["lat"]
    lon = graph.nodes[known_uid]["lon"]
    rc = locate_cli.main(["--lat", str(lat), "--lon", str(lon), "--artifact", str(art)])
    assert rc == 0
    parts = capsys.readouterr().out.strip().split()
    assert int(parts[0]) == known_uid  # nearest uid
    assert float(parts[-1]) == 0.0  # exact click -> 0 distance


def test_pound_locate_includes_node_name_when_present(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    # Click near the Oxford place node's gazetteer coord via resolve_place.
    from pound.route.resolve import resolve_place

    graph = load_artifact(Path(art)).graph
    oxford_uid = resolve_place("Oxford", graph)
    lat = graph.nodes[oxford_uid]["lat"]
    lon = graph.nodes[oxford_uid]["lon"]
    rc = locate_cli.main(["--lat", str(lat), "--lon", str(lon), "--artifact", str(art)])
    assert rc == 0
    out = capsys.readouterr().out.strip().split()
    # <uid>  <name-or-dash>  <distance>; Oxford node has a name attached.
    assert len(out) == 3
    assert out[1] == "Oxford"


def test_pound_locate_max_distance_exceeded_exits_nonzero(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    graph = load_artifact(Path(art)).graph
    known_uid = next(iter(graph.nodes))
    lat = graph.nodes[known_uid]["lat"]
    lon = graph.nodes[known_uid]["lon"]
    # Click 0.001 degrees off (~70-100 m); --max-distance-m 50 -> exceeds.
    rc = locate_cli.main(
        [
            "--lat",
            str(lat + 0.001),
            "--lon",
            str(lon + 0.001),
            "--max-distance-m",
            "50",
            "--artifact",
            str(art),
        ]
    )
    assert rc != 0
    err = capsys.readouterr().err.lower()
    assert "exceeds" in err or "farther" in err or "away" in err


def test_pound_locate_missing_artifact_exits_nonzero(tmp_path, capsys):
    rc = locate_cli.main(
        ["--lat", "51.75", "--lon", "-1.26", "--artifact", str(tmp_path / "nope.pkl")]
    )
    assert rc != 0
    assert "not found" in capsys.readouterr().err.lower()


def test_pound_locate_missing_lat_raises_systemexit(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    with pytest.raises(SystemExit):
        locate_cli.main(["--lon", "-1.26", "--artifact", str(art)])  # missing --lat
