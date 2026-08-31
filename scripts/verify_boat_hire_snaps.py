"""Report boat-hire projections before and after a routing-artifact change."""

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from pound.artifact import RuntimeArtifact, load_artifact  # pyright: ignore[reportMissingImports]
from pound.graph.spatial import (  # pyright: ignore[reportMissingImports]
    CandidateSpatialIndex,
    GraphSpatialIndex,
)
from pound_web.boat_hire import (  # pyright: ignore[reportMissingImports]
    BOAT_HIRE_OVERLAY_DISTANCE_EXCEPTIONS_M,
    BOAT_HIRE_OVERLAY_DISTANCE_M,
    BoatHireSeed,
    load_boat_hire_seeds,
)

_REQUIRED_BASE_IDENTITY = "canal-holidays/base:62"


def _graph(artifact: RuntimeArtifact | Path):
    return load_artifact(artifact).graph if isinstance(artifact, Path) else artifact.graph


def _project_old(index: GraphSpatialIndex, seed: BoatHireSeed) -> tuple[tuple[int, int], float]:
    edge, _projected, distance = index.project_to_nearest_edge(seed.latitude, seed.longitude)
    return edge, float(distance)


def _project_new(index: CandidateSpatialIndex, seed: BoatHireSeed) -> tuple[tuple[int, int], float]:
    result = index.nearest_projection(seed.latitude, seed.longitude)
    if result is None:
        raise ValueError(f"Boat-hire seed {seed.identity} could not be projected")
    projected, distance = result
    return projected.handle.edge, float(distance)


def _entry(
    seed: BoatHireSeed, old_index: GraphSpatialIndex, new_index: CandidateSpatialIndex
) -> dict[str, Any]:
    old_edge, old_distance = _project_old(old_index, seed)
    new_edge, new_distance = _project_new(new_index, seed)
    return {
        "identity": seed.identity,
        "old_edge": list(old_edge),
        "old_snap_distance_m": old_distance,
        "new_edge": list(new_edge),
        "new_snap_distance_m": new_distance,
    }


def canonical_boat_hire_seeds(seeds: Iterable[BoatHireSeed]) -> tuple[BoatHireSeed, ...]:
    """Return sorted curated seeds after enforcing the required Base62 entry."""
    boat_hire_seeds = tuple(sorted(seeds, key=lambda seed: seed.identity))
    if not any(seed.identity == _REQUIRED_BASE_IDENTITY for seed in boat_hire_seeds):
        raise ValueError(f"curated seeds must include {_REQUIRED_BASE_IDENTITY}")
    return boat_hire_seeds


def complete_records_by_identity(
    seeds: Iterable[BoatHireSeed], records: Iterable[Mapping[str, Any]], *, description: str
) -> dict[str, Mapping[str, Any]]:
    """Require exactly one report record for every curated seed."""
    expected = {seed.identity for seed in seeds}
    records = tuple(records)
    by_identity = {str(record["identity"]): record for record in records}
    actual = set(by_identity)
    if len(by_identity) != len(records) or actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ValueError(
            f"{description} identity coverage is incomplete: "
            f"missing={missing}, unexpected={unexpected}"
        )
    return by_identity


def build_boat_hire_snap_report(
    seeds: Iterable[BoatHireSeed], entries: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """Apply shared completeness and distance-threshold checks to snap entries."""
    boat_hire_seeds = canonical_boat_hire_seeds(seeds)
    entries_by_identity = complete_records_by_identity(
        boat_hire_seeds, entries, description="boat-hire snap report"
    )
    old_threshold_breaches: list[str] = []
    threshold_breaches: list[str] = []
    required_exception_changes: list[str] = []
    for seed in boat_hire_seeds:
        entry = entries_by_identity[seed.identity]
        default_limit = BOAT_HIRE_OVERLAY_DISTANCE_M
        limit = BOAT_HIRE_OVERLAY_DISTANCE_EXCEPTIONS_M.get(seed.identity, default_limit)
        if float(entry["old_snap_distance_m"]) > limit:
            old_threshold_breaches.append(seed.identity)
        new_distance = float(entry["new_snap_distance_m"])
        if new_distance > limit:
            threshold_breaches.append(seed.identity)
            required_exception_changes.append(seed.identity)
        elif (
            new_distance > default_limit
            and seed.identity not in BOAT_HIRE_OVERLAY_DISTANCE_EXCEPTIONS_M
        ):
            required_exception_changes.append(seed.identity)
    return {
        "bases": [entries_by_identity[seed.identity] for seed in boat_hire_seeds],
        "old_threshold_breaches": old_threshold_breaches,
        "threshold_breaches": threshold_breaches,
        "required_exception_changes": required_exception_changes,
    }


def verify_boat_hire_snaps(
    old_artifact: RuntimeArtifact | Path,
    new_artifact: RuntimeArtifact | Path,
    seeds: Iterable[BoatHireSeed] | Path,
) -> dict[str, Any]:
    """Return a deterministic old/new snap report and threshold failures."""
    boat_hire_seeds = canonical_boat_hire_seeds(
        load_boat_hire_seeds(seeds) if isinstance(seeds, Path) else tuple(seeds)
    )
    old_index = GraphSpatialIndex(_graph(old_artifact), build_candidate_index=False)
    new_index = CandidateSpatialIndex(_graph(new_artifact))
    entries = tuple(_entry(seed, old_index, new_index) for seed in boat_hire_seeds)
    return build_boat_hire_snap_report(boat_hire_seeds, entries)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True, help="old routing artifact")
    parser.add_argument("--after", type=Path, required=True, help="new routing artifact")
    parser.add_argument(
        "--boat-hire-enrichment",
        type=Path,
        required=True,
        help="curated boat-hire enrichment CSV",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        report = verify_boat_hire_snaps(args.before, args.after, args.boat_hire_enrichment)
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return (
        1
        if report["old_threshold_breaches"]
        or report["threshold_breaches"]
        or report["required_exception_changes"]
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
