import io
import json

import pytest
from pound_build.ingest import osm, profile
from pound_build.ingest.ir import WaterwayFeatures
from pound_build.ingest.profile import BuildProfiler, linux_max_rss_bytes


def test_linux_max_rss_bytes_converts_kib_to_bytes():
    assert linux_max_rss_bytes(123) == 123 * 1024


def test_disabled_build_profile_does_not_sample_or_evaluate_counts(monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(
        profile.time,
        "perf_counter",
        lambda: (_ for _ in ()).throw(AssertionError("sampled time")),
    )
    monkeypatch.setattr(
        profile,
        "_peak_rss_bytes",
        lambda: (_ for _ in ()).throw(AssertionError("sampled RSS")),
    )

    with BuildProfiler(enabled=False, stream=stream).phase(
        "unused",
        counts=lambda: (_ for _ in ()).throw(AssertionError("evaluated counts")),
    ):
        pass

    assert stream.getvalue() == ""


def test_build_profile_emits_completed_phase_as_one_json_line(monkeypatch):
    stream = io.StringIO()
    times = iter([10.0, 12.5])
    monkeypatch.setattr(profile.time, "perf_counter", lambda: next(times))
    monkeypatch.setattr(profile, "_peak_rss_bytes", lambda: 4096)

    with BuildProfiler(enabled=True, stream=stream).phase(
        "graph_build", counts=lambda: {"nodes": 3}
    ):
        pass

    assert json.loads(stream.getvalue()) == {
        "build_profile": 1,
        "phase": "graph_build",
        "status": "completed",
        "elapsed_s": 2.5,
        "peak_rss_bytes": 4096,
        "counts": {"nodes": 3},
    }


def test_build_profile_reports_failure_before_reraising(monkeypatch):
    stream = io.StringIO()
    times = iter([4.0, 4.25])
    monkeypatch.setattr(profile.time, "perf_counter", lambda: next(times))
    monkeypatch.setattr(profile, "_peak_rss_bytes", lambda: 8192)

    with pytest.raises(RuntimeError, match="broken"):
        with BuildProfiler(enabled=True, stream=stream).phase("pbf_processing"):
            raise RuntimeError("broken")

    record = json.loads(stream.getvalue())
    assert record == {
        "build_profile": 1,
        "phase": "pbf_processing",
        "status": "failed",
        "elapsed_s": 0.25,
        "peak_rss_bytes": 8192,
        "counts": {},
    }


def test_read_great_britain_profiles_ingest_phases_and_internal_pbf_counts(tmp_path, monkeypatch):
    source = tmp_path / "region.osm.pbf"
    source.write_bytes(b"source")
    features = WaterwayFeatures(
        ways=[],
        nodes=[],
        source="geofabrik",
        fetched_at="2026-07-12T00:00:00+00:00",
        bbox=None,
    )

    def fake_filter(_source, filtered):
        filtered.write_bytes(b"filtered")

    def fake_read(_filtered, *, profile_counts=None):
        assert profile_counts is not None
        profile_counts.update(
            ways=2,
            nodes=3,
            candidates=4,
            pending_areas=5,
            skipped_reasons={"invalid_geometry": 6},
        )
        return features

    monkeypatch.setattr(osm, "run_tags_filter", fake_filter)
    monkeypatch.setattr(osm, "read_pbf", fake_read)
    monkeypatch.setattr(osm, "prune_non_navigable_infra", lambda value: value)
    monkeypatch.setattr(osm, "filter_navigable_ways", lambda value: value)
    stream = io.StringIO()

    result = osm.read_great_britain(source, profiler=BuildProfiler(enabled=True, stream=stream))

    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert result is features
    assert [record["phase"] for record in records] == [
        "tags_filter",
        "pbf_processing",
        "prune",
        "navigable_filter",
    ]
    assert records[1]["counts"] == {
        "ways": 2,
        "nodes": 3,
        "candidates": 4,
        "pending_areas": 5,
        "skipped_reasons": {"invalid_geometry": 6},
    }
