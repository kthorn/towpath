import json
import subprocess
import weakref
from pathlib import Path
from typing import Any, cast

import networkx as nx
import pytest  # pyright: ignore[reportMissingImports]
from fixtures import oxford_fixture_path
from pound.artifact import load_artifact  # pyright: ignore[reportMissingImports]
from pound.catalog.artifact import load_catalog  # pyright: ignore[reportMissingImports]
from pound.models import WaterwayKind, WayDimensions  # pyright: ignore[reportMissingImports]
from pound_build.ingest import cli
from pound_build.ingest.ir import (
    NodeKind,
    WaterwayFeatures,
    WaterwayNode,
    WaterwayWay,
)
from pound_build.ingest.overpass import parse


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


def test_build_profile_emits_completed_phases_as_json_lines(tmp_path: Path, monkeypatch, capsys):
    raw = json.loads(Path(oxford_fixture_path()).read_text())
    monkeypatch.setattr(cli, "fetch_oxford", lambda: parse(raw["elements"], None))

    rc = cli.main(["build", "oxford", "--out", str(tmp_path / "oxford.pkl"), "--profile"])

    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert rc == 0
    assert [record["phase"] for record in records] == [
        "graph_build",
        "graph_annotation",
        "lock_attachment",
        "poi_attachment",
        "artifact_validation",
        "artifact_serialization",
    ]
    assert all(record["status"] == "completed" for record in records)
    assert all(record["elapsed_s"] >= 0 for record in records)
    assert all(record["peak_rss_bytes"] > 0 for record in records)


def test_catalog_england_writes_independent_artifact_and_json_summary(tmp_path, capsys):
    out = tmp_path / "catalog.pkl"
    assert (
        cli.main(
            [
                "catalog",
                "england",
                "--pbf",
                str(Path("packages/pound-core/tests/fixtures/tiny_bulk.osm")),
                "--out",
                str(out),
            ]
        )
        == 0
    )

    summary = json.loads(capsys.readouterr().out)
    assert summary["catalog_count"] == 7
    assert summary["output_bytes"] == out.stat().st_size
    artifact = load_catalog(out)
    assert artifact.metadata["source"].endswith("tiny_bulk.osm")
    assert artifact.metadata["build_summary"]["emitted"] == 7
    assert artifact.metadata["build_summary"]["inactive"] == 1
    assert artifact.metadata["build_summary"]["malformed"] == 0
    assert artifact.metadata["build_summary"]["duplicate"] == 0
    assert artifact.metadata["build_summary"]["excluded_by_reason"]["transport"] == 2
    assert set(artifact.metadata) == {
        "attribution",
        "build_summary",
        "built_at",
        "catalog_revision",
        "catalog_schema_version",
        "fetched_at",
        "inventory_summary",
        "source",
    }
    assert artifact.metadata["catalog_schema_version"] == 3
    assert artifact.metadata["attribution"] == "© OpenStreetMap contributors"


def test_catalog_england_filters_pbf_in_unique_temp_file_without_mutating_source(
    tmp_path, monkeypatch
):
    source = tmp_path / "england.osm.pbf"
    source.write_bytes(b"original")
    out = tmp_path / "catalog.pkl"
    commands = []
    read_paths = []

    def fake_run(command, *, check):
        assert check is True
        commands.append(command)
        filtered = Path(command[command.index("-o") + 1])
        filtered.write_bytes(b"filtered")

    real_read_catalog = cli.read_catalog

    def fake_read_catalog(path, **kwargs):
        read_paths.append(Path(path))
        return real_read_catalog(Path("packages/pound-core/tests/fixtures/tiny_bulk.osm"), **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(cli, "read_catalog", fake_read_catalog)

    assert cli.main(["catalog", "england", "--pbf", str(source), "--out", str(out)]) == 0

    assert source.read_bytes() == b"original"
    assert len(commands) == 1
    assert commands[0][:2] == ["osmium", "tags-filter"]
    assert str(source) in commands[0]
    assert "-R" not in commands[0]
    assert read_paths and read_paths[0] != source
    assert not read_paths[0].exists()


def test_catalog_england_cleans_temp_filter_on_failure(tmp_path, monkeypatch):
    source = tmp_path / "england.osm.pbf"
    source.write_bytes(b"original")
    filtered_paths = []

    def fake_run(command, *, check):
        assert check is True
        filtered = Path(command[command.index("-o") + 1])
        filtered_paths.append(filtered)
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(subprocess.CalledProcessError):
        cli.main(
            [
                "catalog",
                "england",
                "--pbf",
                str(source),
                "--out",
                str(tmp_path / "catalog.pkl"),
            ]
        )

    assert source.read_bytes() == b"original"
    assert filtered_paths and not filtered_paths[0].parent.exists()


def test_catalog_england_profile_reports_reader_and_serialization_phases(tmp_path, capsys):
    out = tmp_path / "catalog.pkl"
    assert (
        cli.main(
            [
                "catalog",
                "england",
                "--pbf",
                str(Path("packages/pound-core/tests/fixtures/tiny_bulk.osm")),
                "--out",
                str(out),
                "--profile",
            ]
        )
        == 0
    )
    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [record["phase"] for record in records] == [
        "catalog_read",
        "catalog_artifact_validation",
        "catalog_artifact_serialization",
    ]
    assert all(record["status"] == "completed" for record in records)
    assert records[0]["counts"]["scanned"] == 54
    assert records[-1]["counts"]["output_bytes"] == out.stat().st_size


def test_catalog_england_requires_original_pbf(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli.main(
            [
                "catalog",
                "england",
                "--pbf",
                str(tmp_path / "missing.osm.pbf"),
                "--out",
                str(tmp_path / "catalog.pkl"),
            ]
        )
    assert exc_info.value.code != 0
    assert "original" in capsys.readouterr().out.lower()


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
    # Fake the three pyosmium passes with an Oxford-shaped fixture.
    try:
        raw = json.loads(Path(oxford_fixture_path()).read_text())
        fake_feats = parse(raw["elements"], None, osm_timestamp=raw["osm3s"]["timestamp_osm_base"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(f"Failed to load Oxford fixture: {e}") from e
    fake_feats = fake_feats.model_copy(update={"source": "geofabrik", "bbox": None})

    monkeypatch.setenv("POUND_PBF_PATH", str(tmp_path / "england.osm.pbf"))
    Path(tmp_path / "england.osm.pbf").write_bytes(b"")  # dummy so the guard passes
    candidates = list(fake_feats.poi_candidates)
    graph_features = fake_feats.model_copy(update={"poi_candidates": []})
    filtered = tmp_path / "england_waterways.osm.pbf"
    filtered.write_bytes(b"filtered")
    seen_paths = []
    monkeypatch.setattr(cli, "prepare_england_pbf", lambda _pbf, _profiler: filtered)
    monkeypatch.setattr(
        cli,
        "read_england_waterways",
        lambda path, _profiler: seen_paths.append(path) or graph_features,
    )

    def stream_linear(path, consume, _diagnostics, _counts):
        seen_paths.append(path)
        for candidate in candidates:
            if candidate.geometry_source != "area":
                consume(candidate)

    def stream_area(path, consume, _diagnostics, _counts):
        seen_paths.append(path)
        for candidate in candidates:
            if candidate.geometry_source == "area":
                consume(candidate)

    monkeypatch.setattr(cli, "stream_linear_pois", stream_linear)
    monkeypatch.setattr(cli, "stream_area_pois", stream_area)
    accumulator_options = []
    real_accumulator = cli.PoiBuildAccumulator

    def bounded_accumulator(index, **options):
        accumulator_options.append(options)
        return real_accumulator(index, **options)

    monkeypatch.setattr(cli, "PoiBuildAccumulator", bounded_accumulator)
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
    assert "Oxford" in artifact.gazetteer
    assert seen_paths == [filtered, filtered, filtered]
    assert accumulator_options == [{"retain_rejected_winners": False}]


def test_build_england_profile_reports_multi_pass_phase_order(monkeypatch, tmp_path, capsys):
    features = _sample_features().model_copy(update={"source": "geofabrik", "bbox": None})
    source = tmp_path / "england.osm.pbf"
    source.write_bytes(b"source")
    filtered = tmp_path / "england_waterways.osm.pbf"
    filtered.write_bytes(b"filtered")

    def prepare(_pbf, profiler):
        with profiler.phase("tags_filter"):
            return filtered

    def read_waterways(_path, profiler):
        with profiler.phase("waterway_processing"):
            return features

    monkeypatch.setattr(cli, "prepare_england_pbf", prepare)
    monkeypatch.setattr(cli, "read_england_waterways", read_waterways)
    monkeypatch.setattr(cli, "stream_linear_pois", lambda *_args: None)
    monkeypatch.setattr(cli, "stream_area_pois", lambda *_args: None)

    rc = cli.main(
        ["build", "england", "--pbf", str(source), "--out", str(tmp_path / "out.pkl"), "--profile"]
    )

    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert rc == 0
    assert [record["phase"] for record in records] == [
        "tags_filter",
        "waterway_processing",
        "graph_build",
        "graph_annotation",
        "lock_attachment",
        "linear_poi_processing",
        "area_poi_processing",
        "artifact_validation",
        "artifact_serialization",
    ]


def test_build_england_stream_failure_reports_failed_phase_and_does_not_write(
    monkeypatch, tmp_path, capsys
):
    features = _sample_features().model_copy(update={"source": "geofabrik", "bbox": None})
    source = tmp_path / "england.osm.pbf"
    source.write_bytes(b"source")
    filtered = tmp_path / "england_waterways.osm.pbf"
    filtered.write_bytes(b"filtered")
    monkeypatch.setattr(cli, "prepare_england_pbf", lambda _pbf, _profiler: filtered)
    monkeypatch.setattr(cli, "read_england_waterways", lambda _path, _profiler: features)
    monkeypatch.setattr(
        cli,
        "stream_linear_pois",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("broken PBF")),
    )
    writes = []
    monkeypatch.setattr(cli, "write_artifact", lambda *_args: writes.append(True))

    with pytest.raises(RuntimeError, match="broken PBF"):
        cli.main(
            [
                "build",
                "england",
                "--pbf",
                str(source),
                "--out",
                str(tmp_path / "out.pkl"),
                "--profile",
            ]
        )

    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert records[-1]["phase"] == "linear_poi_processing"
    assert records[-1]["status"] == "failed"
    assert writes == []


def test_build_attaches_pois_before_validation_and_saves_strict_signature(tmp_path, monkeypatch):
    events = []
    lock_calls = []
    features = _sample_features()
    graph = nx.Graph()
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

    def fake_attach_locks(actual_graph, _features, *, in_place=False):
        lock_calls.append((actual_graph, in_place))
        return actual_graph, {}

    monkeypatch.setattr(cli, "attach_locks", fake_attach_locks)
    monkeypatch.setattr(
        cli,
        "attach_pois",
        lambda actual_graph, candidates: (
            events.append(("pois", actual_graph, candidates)) or poi_result
        ),
    )
    monkeypatch.setattr(
        cli,
        "validate_graph",
        lambda actual_graph, lock_report, poi_validation: (
            events.append(("validate", actual_graph, poi_validation))
            or {"derelict_edges": 0, "self_loops": 0, "poi_duplicate_identities": 0}
        ),
    )
    monkeypatch.setattr(
        cli,
        "_prepare_build_artifact",
        lambda actual_graph, pois, gazetteer, metadata: (
            events.append(("prepare", actual_graph, pois, gazetteer, metadata))
            or "prepared-artifact"
        ),
    )
    monkeypatch.setattr(
        cli,
        "write_artifact",
        lambda artifact, out: events.append(("write", artifact, out)),
    )

    rc = cli._build_from_features(features, type("Args", (), {"out": tmp_path / "x.pkl"})())

    assert rc == 0
    assert lock_calls == [(graph, True)]
    assert [event[0] for event in events] == ["pois", "validate", "prepare", "write"]
    assert events[0][1:] == (graph, features.poi_candidates)
    assert events[2][1:4] == (graph, (), {})
    assert set(events[2][4]) == {
        "source",
        "fetched_at",
        "built_at",
        "validation",
        "poi_summary",
    }
    assert events[3][1:] == ("prepared-artifact", tmp_path / "x.pkl")


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
    monkeypatch.setattr(cli, "_prepare_build_artifact", lambda *_args: saved.append(True))

    rc = cli._build_from_features(features, type("Args", (), {"out": tmp_path / "x.pkl"})())

    assert rc == 1
    assert saved == []


def test_build_releases_feature_ir_before_poi_attachment(tmp_path, monkeypatch):
    released = []
    graph = nx.Graph()
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

    def fetch_features():
        features = _sample_features()
        weakref.finalize(features, released.append, "released")
        return features

    def attach_poi_phase(actual_graph, candidates, _profiler):
        assert released == ["released"]
        assert actual_graph is graph
        assert candidates == []
        return poi_result

    monkeypatch.setattr(cli, "fetch_oxford", fetch_features)
    monkeypatch.setattr(cli, "_build_graph_phases", lambda _features, _profiler: (graph, {}))
    monkeypatch.setattr(cli, "_attach_poi_phase", attach_poi_phase)
    monkeypatch.setattr(
        cli,
        "validate_graph",
        lambda *_args: {"derelict_edges": 0, "self_loops": 0, "poi_duplicate_identities": 0},
    )
    monkeypatch.setattr(cli, "_prepare_build_artifact", lambda *_args: "artifact")
    monkeypatch.setattr(cli, "write_artifact", lambda *_args: None)

    rc = cli.main(["build", "oxford", "--out", str(tmp_path / "graph.pkl")])

    assert rc == 0


def test_batching_poi_consumer_flushes_fixed_size_batches_and_tail():
    batches = []
    accumulator = type("Accumulator", (), {"add_many": batches.append})()
    consumer = cli._BatchingPoiConsumer(cast(Any, accumulator), batch_size=2)

    for value in range(5):
        consumer(value)
    consumer.flush()

    assert batches == [[0, 1], [2, 3], [4]]
