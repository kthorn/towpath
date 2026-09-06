"""Memory-bounded diagnostic collection shared by OSM readers."""

from pound_build.ingest.ir import PoiIngestReport

MAX_EXAMPLES_PER_REASON = 5


class PoiDiagnostics:
    """Count every skip while retaining only deterministic bounded examples."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._examples: dict[str, set[str]] = {}

    def record(self, reason: str, example: str) -> None:
        self._counts[reason] = self._counts.get(reason, 0) + 1
        self._add_example(reason, example)

    def merge(self, report: PoiIngestReport) -> None:
        for reason, count in report.skipped_counts.items():
            self._counts[reason] = self._counts.get(reason, 0) + count
        for reason, examples in report.skipped_examples.items():
            for example in examples:
                self._add_example(reason, example)

    def _add_example(self, reason: str, example: str) -> None:
        examples = self._examples.setdefault(reason, set())
        examples.add(example)
        if len(examples) > MAX_EXAMPLES_PER_REASON:
            examples.remove(max(examples))

    def build_report(self) -> PoiIngestReport:
        return PoiIngestReport(
            skipped_counts=dict(self._counts),
            skipped_examples={
                reason: sorted(examples) for reason, examples in self._examples.items()
            },
        )
