"""Memory-bounded diagnostic collection shared by OSM readers."""

from pound.ingest.ir import PoiIngestReport

MAX_EXAMPLES_PER_REASON = 5


class PoiDiagnostics:
    """Count every skip while retaining only deterministic bounded examples."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._examples: dict[str, set[str]] = {}

    def record(self, reason: str, example: str) -> None:
        self._counts[reason] = self._counts.get(reason, 0) + 1
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
