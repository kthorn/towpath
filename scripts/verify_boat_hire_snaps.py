"""Report boat-hire projections before and after a routing-artifact change."""

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pound.artifact import RuntimeArtifact, load_artifact  # pyright: ignore[reportMissingImports]
from pound.graph.spatial import GraphSpatialIndex  # pyright: ignore[reportMissingImports]
from pound_web.boat_hire import (  # pyright: ignore[reportMissingImports]
    BOAT_HIRE_OVERLAY_DISTANCE_EXCEPTIONS_M,
    BOAT_HIRE_OVERLAY_DISTANCE_M,
    BoatHireSeed,
    load_boat_hire_seeds,
)

_REQUIRED_BASE_IDENTITY = "canal-holidays/base:62"


def _graph(artifact: RuntimeArtifact | Path):
    return load_artifact(artifact).graph if isinstance(artifact, Path) else artifact.graph


def _project(index: GraphSpatialIndex, seed: BoatHireSeed):
    result = index.candidate_index.nearest_projection(seed.latitude, seed.longitude)
    if result is None:
        raise ValueError(f"Boat-hire seed {seed.identity} could not be projected")
    return result


def _entry(
    seed: BoatHireSeed, old_index: GraphSpatialIndex, new_index: GraphSpatialIndex
) -> dict[str, Any]:
    old_projected, old_distance = _project(old_index, seed)
    new_projected, new_distance = _project(new_index, seed)
    return {
        "identity": seed.identity,
        "old_edge": list(old_projected.handle.edge),
        "old_snap_distance_m": float(old_distance),
        "new_edge": list(new_projected.handle.edge),
        "new_snap_distance_m": float(new_distance),
    }


def verify_boat_hire_snaps(
    old_artifact: RuntimeArtifact | Path,
    new_artifact: RuntimeArtifact | Path,
    seeds: Iterable[BoatHireSeed] | Path,
) -> dict[str, Any]:
    """Return a deterministic old/new snap report and threshold failures."""
    boat_hire_seeds = load_boat_hire_seeds(seeds) if isinstance(seeds, Path) else tuple(seeds)
    boat_hire_seeds = tuple(sorted(boat_hire_seeds, key=lambda seed: seed.identity))
    if not any(seed.identity == _REQUIRED_BASE_IDENTITY for seed in boat_hire_seeds):
        raise ValueError(f"curated seeds must include {_REQUIRED_BASE_IDENTITY}")

    old_index = GraphSpatialIndex(_graph(old_artifact))
    new_index = GraphSpatialIndex(_graph(new_artifact))
    entries = tuple(_entry(seed, old_index, new_index) for seed in boat_hire_seeds)
    threshold_breaches: list[str] = []
    required_exception_changes: list[str] = []
    for seed, entry in zip(boat_hire_seeds, entries, strict=True):
        default_limit = BOAT_HIRE_OVERLAY_DISTANCE_M
        limit = BOAT_HIRE_OVERLAY_DISTANCE_EXCEPTIONS_M.get(seed.identity, default_limit)
        new_distance = entry["new_snap_distance_m"]
        if new_distance > limit:
            threshold_breaches.append(seed.identity)
            required_exception_changes.append(seed.identity)
        elif (
            new_distance > default_limit
            and seed.identity not in BOAT_HIRE_OVERLAY_DISTANCE_EXCEPTIONS_M
        ):
            required_exception_changes.append(seed.identity)

    return {
        "bases": list(entries),
        "threshold_breaches": threshold_breaches,
        "required_exception_changes": required_exception_changes,
    }


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
    return 1 if report["threshold_breaches"] or report["required_exception_changes"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
