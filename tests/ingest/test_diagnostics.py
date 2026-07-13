from pound.ingest.diagnostics import MAX_EXAMPLES_PER_REASON, PoiDiagnostics


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
        len(examples) == MAX_EXAMPLES_PER_REASON
        for examples in diagnostics._examples.values()
    )
    assert diagnostics.build_report().skipped_counts == {
        "invalid_geometry": 8,
        "unknown_value": 8,
    }
