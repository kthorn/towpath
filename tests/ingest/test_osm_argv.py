"""Unit test for run_tags_filter argv construction (no osmium import)."""

from pound.ingest.osm import TAGS_FILTER_EXPR, run_tags_filter


def test_run_tags_filter_splits_argv(monkeypatch, tmp_path):
    """Verify the filter expression is split into per-line positional args."""
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv

    monkeypatch.setattr("subprocess.run", fake_run)

    in_pbf = tmp_path / "england.osm.pbf"
    out_pbf = tmp_path / "england_waterways.osm.pbf"
    in_pbf.touch()

    run_tags_filter(in_pbf, out_pbf)

    expected_exprs = [line for line in TAGS_FILTER_EXPR.splitlines() if line.strip()]
    assert captured["argv"] == [
        "osmium",
        "tags-filter",
        "--overwrite",  # idempotent re-runs (D.3 curation loop)
        "-o",
        str(out_pbf),
        str(in_pbf),
        *expected_exprs,
    ]
    # Ensure the entire expression is NOT a single multi-line element
    assert TAGS_FILTER_EXPR not in captured["argv"]
