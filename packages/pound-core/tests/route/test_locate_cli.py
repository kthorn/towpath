from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]
from pound.artifact import load_artifact
from pound.route import locate_cli

from tests.fixtures import routing_test_graph, write_runtime_artifact


def _build_oxford_artifact(out: Path) -> Path:
    graph, gazetteer = routing_test_graph()
    graph.graph.pop("gazetteer", None)
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


def test_pound_locate_prints_canonical_edge_fraction_and_distance(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    graph = load_artifact(Path(art)).graph
    known_uid = next(iter(graph.nodes))
    lat = graph.nodes[known_uid]["lat"]
    lon = graph.nodes[known_uid]["lon"]

    rc = locate_cli.main(["--lat", str(lat), "--lon", str(lon), "--artifact", str(art)])

    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert "edge=(1, 2)" in out
    assert "fraction=0.000000000000" in out
    assert "distance_m=0.0" in out


def test_pound_locate_projects_midpoint_fraction(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    graph = load_artifact(Path(art)).graph
    first, second = graph.nodes[1], graph.nodes[2]
    lat = (first["lat"] + second["lat"]) / 2
    lon = (first["lon"] + second["lon"]) / 2

    rc = locate_cli.main(["--lat", str(lat), "--lon", str(lon), "--artifact", str(art)])

    assert rc == 0
    parts = capsys.readouterr().out.strip().split()
    assert parts[0] == "edge=(1,"
    assert parts[1] == "2)"
    assert float(parts[2].split("=", 1)[1]) == pytest.approx(0.5, abs=3e-6)


def test_pound_locate_max_distance_exceeded_exits_nonzero(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    graph = load_artifact(Path(art)).graph
    known_uid = next(iter(graph.nodes))
    lat = graph.nodes[known_uid]["lat"]
    lon = graph.nodes[known_uid]["lon"]
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
    assert "exceeds" in capsys.readouterr().err.lower()


def test_pound_locate_missing_artifact_exits_nonzero(tmp_path, capsys):
    rc = locate_cli.main(
        ["--lat", "51.75", "--lon", "-1.26", "--artifact", str(tmp_path / "nope.pkl")]
    )
    assert rc != 0
    assert "not found" in capsys.readouterr().err.lower()


def test_pound_locate_missing_lat_raises_systemexit(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    with pytest.raises(SystemExit):
        locate_cli.main(["--lon", "-1.26", "--artifact", str(art)])
