import json
from pathlib import Path

import networkx as nx

from pound.graph.artifact import load_artifact
from pound.ingest import cli
from pound.ingest.ir import (
    NodeKind,
    WaterwayFeatures,
    WaterwayKind,
    WaterwayNode,
    WaterwayWay,
    WayDimensions,
)
from pound.ingest.overpass import parse
from tests.fixtures import oxford_fixture_path


def _sample_features() -> WaterwayFeatures:
    return WaterwayFeatures(
        ways=[
            WaterwayWay(
                osm_id=1,
                kind=WaterwayKind.CANAL,
                name="Oxford Canal",
                tags={"waterway": "canal"},
                node_ids=[],
                geometry=[(51.75, -1.26)],
                dimensions=WayDimensions(max_beam_m=2.1),
            )
        ],
        nodes=[
            WaterwayNode(
                osm_id=10,
                lat=51.75,
                lon=-1.26,
                tags={"waterway": "lock_gate"},
                kind=NodeKind.LOCK_GATE,
            )
        ],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=(51.70, -1.35, 51.80, -1.20),
    )


def test_cli_prints_report_and_writes_out(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_oxford", lambda: _sample_features())
    out_path = tmp_path / "oxford.json"
    cli.main(["oxford", "--out", str(out_path)])

    captured = capsys.readouterr()
    try:
        report = json.loads(captured.out)
    except json.JSONDecodeError as e:
        raise AssertionError(f"CLI output is not valid JSON: {e}") from e
    assert report["way_count"] == 1
    assert report["ways_by_kind"] == {"canal": 1}

    written = WaterwayFeatures.model_validate_json(out_path.read_text())
    assert written.source == "overpass"
    assert len(written.ways) == 1


def test_cli_rejects_unknown_region(monkeypatch):
    monkeypatch.setattr(cli, "fetch_oxford", lambda: _sample_features())
    try:
        cli.main(["bogus"])
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("expected SystemExit for unknown region")


def test_build_subcommand_writes_artifact(tmp_path: Path, monkeypatch):
    try:
        raw = json.loads(Path(oxford_fixture_path()).read_text())
        features = parse(raw["elements"], None)
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(f"Failed to load Oxford fixture: {e}") from e
    monkeypatch.setattr(cli, "fetch_oxford", lambda: features)
    out = tmp_path / "oxford.pkl"
    rc = cli.main(["build", "oxford", "--out", str(out)])
    assert rc == 0
    assert out.exists()
    artifact = load_artifact(out)
    assert artifact.graph.number_of_edges() > 0
    assert "validation" in artifact.metadata
    assert artifact.metadata["poi_summary"]["retained"] == len(artifact.pois)
    assert "version" not in artifact.metadata


def test_build_profile_is_silent_by_default(tmp_path: Path, monkeypatch, capsys):
    raw = json.loads(Path(oxford_fixture_path()).read_text())
    monkeypatch.setattr(cli, "fetch_oxford", lambda: parse(raw["elements"], None))

    assert cli.main(["build", "oxford", "--out", str(tmp_path / "oxford.pkl")]) == 0

    assert "build_profile" not in capsys.readouterr().err


def test_build_profile_emits_completed_phases_as_json_lines(
    tmp_path: Path, monkeypatch, capsys
):
    raw = json.loads(Path(oxford_fixture_path()).read_text())
    monkeypatch.setattr(cli, "fetch_oxford", lambda: parse(raw["elements"], None))

    rc = cli.main(
        ["build", "oxford", "--out", str(tmp_path / "oxford.pkl"), "--profile"]
    )

    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert rc == 0
    assert [record["phase"] for record in records] == [
        "graph_build",
        "graph_annotation",
        "lock_attachment",
        "poi_attachment",
        "artifact_save",
    ]
    assert all(record["status"] == "completed" for record in records)
    assert all(record["elapsed_s"] >= 0 for record in records)
    assert all(record["peak_rss_bytes"] > 0 for record in records)


def test_build_england_missing_pbf_prints_url_and_exits(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("POUND_PBF_PATH", str(tmp_path / "missing.osm.pbf"))
    try:
        cli.main(["build", "england", "--out", str(tmp_path / "england.pkl")])
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("expected SystemExit for missing PBF")
    out = capsys.readouterr().out
    assert "geofabrik" in out.lower()
    assert "england" in out.lower()
    assert "1.5" in out  # expected size hint in GB


def test_build_england_writes_artifact_and_passes_gate(monkeypatch, tmp_path):
    # Fake the osmium+pyosmium path: read_england returns the Oxford fixture
    # parsed via the Overpass reader (shape-equivalent), so gates evaluate.
    try:
        raw = json.loads(Path(oxford_fixture_path()).read_text())
        fake_feats = parse(raw["elements"], None, osm_timestamp=raw["osm3s"]["timestamp_osm_base"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(f"Failed to load Oxford fixture: {e}") from e
    fake_feats = fake_feats.model_copy(update={"source": "geofabrik", "bbox": None})

    monkeypatch.setenv("POUND_PBF_PATH", str(tmp_path / "england.osm.pbf"))
    Path(tmp_path / "england.osm.pbf").write_bytes(b"")  # dummy so the guard passes
    monkeypatch.setattr(
        cli, "read_england", lambda pbf_path=None, *, profiler=None: fake_feats
    )
    out = tmp_path / "england.pkl"
    rc = cli.main(
        [
            "build",
            "england",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    assert out.exists()
    artifact = load_artifact(out)
    assert "validation" in artifact.metadata
    assert "gazetteer" in artifact.graph.graph
    assert "Oxford" in artifact.graph.graph["gazetteer"]


def test_build_attaches_pois_before_validation_and_saves_strict_signature(tmp_path, monkeypatch):
    events = []
    features = _sample_features()
    graph = nx.Graph()
    attached_graph = nx.Graph()
    poi_result = type(
        "Result",
        (),
        {
            "pois": (),
            "summary": {
                "duplicate_identities": 0,
                "empty_geometry": 0,
                "invalid_geometry": 0,
                "rejected_by_corridor": 0,
            },
        },
    )()
    monkeypatch.setattr(cli, "build_graph", lambda _features: graph)
    monkeypatch.setattr(cli, "attach_node_names", lambda *_args: None)
    monkeypatch.setattr(cli, "build_gazetteer", lambda _features: {})
    monkeypatch.setattr(cli, "attach_locks", lambda _graph, _features: (attached_graph, {}))
    monkeypatch.setattr(
        cli,
        "attach_pois",
        lambda actual_graph, candidates: events.append(("pois", actual_graph, candidates))
        or poi_result,
    )
    monkeypatch.setattr(
        cli,
        "validate_graph",
        lambda actual_graph, lock_report, poi_validation: events.append(
            ("validate", actual_graph, poi_validation)
        )
        or {"derelict_edges": 0, "self_loops": 0, "poi_duplicate_identities": 0},
    )
    monkeypatch.setattr(
        cli,
        "save_artifact",
        lambda actual_graph, pois, out, metadata: events.append(
            ("save", actual_graph, pois, out, metadata)
        ),
    )

    rc = cli._build_from_features(features, type("Args", (), {"out": tmp_path / "x.pkl"})())

    assert rc == 0
    assert [event[0] for event in events] == ["pois", "validate", "save"]
    assert events[0][1:] == (attached_graph, features.poi_candidates)
    assert events[2][1:4] == (attached_graph, (), tmp_path / "x.pkl")
    assert set(events[2][4]) == {
        "source",
        "fetched_at",
        "built_at",
        "validation",
        "poi_summary",
    }


def test_build_does_not_save_when_poi_identity_validation_is_fatal(tmp_path, monkeypatch):
    features = _sample_features()
    result = type(
        "Result",
        (),
        {
            "pois": (),
            "summary": {
                "duplicate_identities": 1,
                "empty_geometry": 0,
                "invalid_geometry": 0,
                "rejected_by_corridor": 0,
            },
        },
    )()
    monkeypatch.setattr(cli, "attach_pois", lambda *_args: result)
    saved = []
    monkeypatch.setattr(cli, "save_artifact", lambda *_args: saved.append(True))

    rc = cli._build_from_features(features, type("Args", (), {"out": tmp_path / "x.pkl"})())

    assert rc == 1
    assert saved == []
