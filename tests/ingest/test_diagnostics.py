from pound.ingest.diagnostics import MAX_EXAMPLES_PER_REASON, PoiDiagnostics
from pound.ingest.ir import PoiIngestReport


def test_poi_diagnostics_counts_every_event_and_keeps_smallest_distinct_examples():
    diagnostics = PoiDiagnostics()
    examples = ["way/z", "way/y", "way/x", "way/w", "way/v", "way/u", "way/t"]

    for example in [*examples, "way/z"]:
        diagnostics.record("invalid_geometry", example)
        assert len(diagnostics._examples["invalid_geometry"]) <= MAX_EXAMPLES_PER_REASON

    report = diagnostics.build_report()
    assert report.skipped_counts == {"invalid_geometry": 8}
    assert report.skipped_examples == {
        "invalid_geometry": ["way/t", "way/u", "way/v", "way/w", "way/x"]
    }


def test_poi_diagnostics_bounds_each_reason_independently():
    diagnostics = PoiDiagnostics()

    for index in reversed(range(8)):
        diagnostics.record("invalid_geometry", f"way/{index}")
        diagnostics.record("unknown_value", f"node/{index}")

    assert all(
        len(examples) == MAX_EXAMPLES_PER_REASON for examples in diagnostics._examples.values()
    )
    assert diagnostics.build_report().skipped_counts == {
        "invalid_geometry": 8,
        "unknown_value": 8,
    }


def test_poi_diagnostics_merges_counts_and_bounded_examples_deterministically():
    first = PoiIngestReport(
        skipped_counts={"invalid_geometry": 4, "unknown_value": 1},
        skipped_examples={"invalid_geometry": ["way/9", "way/7", "way/5"]},
    )
    second = PoiIngestReport(
        skipped_counts={"invalid_geometry": 3, "unknown_value": 2},
        skipped_examples={
            "invalid_geometry": ["way/8", "way/6", "way/4", "way/3"],
            "unknown_value": ["node/2", "node/1"],
        },
    )

    forward = PoiDiagnostics()
    forward.merge(first)
    forward.merge(second)
    reverse = PoiDiagnostics()
    reverse.merge(second)
    reverse.merge(first)

    expected = PoiIngestReport(
        skipped_counts={"invalid_geometry": 7, "unknown_value": 3},
        skipped_examples={
            "invalid_geometry": ["way/3", "way/4", "way/5", "way/6", "way/7"],
            "unknown_value": ["node/1", "node/2"],
        },
    )
    assert forward.build_report() == expected
    assert reverse.build_report() == expected
