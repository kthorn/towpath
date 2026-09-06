"""Minimal pound-plan CLI — a test harness, not a product surface (design §6).

Type two place names, get a route to eyeball that the engine works on real
data. Plain human-readable stdout; no --json, no fancy formatting. A future
REST API supersedes it.

Usage:
    pound-plan <start> <end> [--days N] [--hours-per-day H]
               [--boat-beam M] [--boat-draft M] [--boat-length M] [--boat-height M]
               [--verbose] [--locks] [--artifact PATH]

`start` and `end` are place names resolved through the artifact gazetteer.
`--days` is optional: omit it and the day count is inferred from
`--hours-per-day` (you get as many days as the route needs, no cap). Default
output is the route header + totals + the per-day summary + warnings; the leg
list is only printed with `--verbose`.
"""

import argparse
import math
import sys
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError  # pyright: ignore[reportMissingImports]

from pound.artifact import RuntimeArtifact, load_artifact
from pound.graph.spatial import CandidateSpatialIndex
from pound.route.plan import plan_projected_route
from pound.route.resolve import resolve_place
from pound.schemas import ProjectedRouteConstraints

_DEFAULT_ARTIFACT = Path("artifacts/great-britain.pkl")


def _finite_nonnegative(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a finite non-negative number") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be a finite non-negative number")
    return parsed


def _resolve_start_end(
    start_name: str,
    end_name: str,
    artifact: RuntimeArtifact,
    candidate_index: CandidateSpatialIndex,
    *,
    days: int | None,
    hours_per_day: float,
    boat_length_m: float | None,
    boat_beam_m: float | None,
    boat_draft_m: float | None,
    boat_height_m: float | None,
    movable_bridge_delay_min: float | None,
) -> ProjectedRouteConstraints:
    """Build projected routing constraints from two gazetteer place names."""
    boat = dict(
        boat_length_m=boat_length_m,
        boat_beam_m=boat_beam_m,
        boat_draft_m=boat_draft_m,
        boat_height_m=boat_height_m,
        movable_bridge_delay_min=movable_bridge_delay_min,
    )
    return ProjectedRouteConstraints(
        start=resolve_place(start_name, artifact, candidate_index),
        end=resolve_place(end_name, artifact, candidate_index),
        days=days,
        hours_per_day=hours_per_day,
        **cast(Any, boat),
    )


def _render(result, *, verbose: bool = False, locks: bool = False) -> str:
    lines = [f"Route: {result.start} -> {result.end}"]
    if verbose:
        lines.append("Legs:")
        for leg in result.legs:
            lines.append(
                f"  {leg.from_place} -> {leg.to_place}: "
                f"{leg.distance_km} km, {leg.locks} locks, {leg.est_minutes} min"
            )
    lines.append(
        f"Totals: {result.total_km} km, {result.total_locks} locks, {result.total_minutes} min"
    )
    lines.append("Days:")
    for day in result.days:
        day_locks = sum(leg.locks for leg in day.legs)
        if locks:
            lines.append(
                f"  Day {day.day}: {day.cruising_minutes} min, "
                f"{day_locks} locks, ends near {day.end_near}"
            )
        else:
            lines.append(f"  Day {day.day}: {day.cruising_minutes} min, ends near {day.end_near}")
    if result.warnings:
        lines.append("Warnings:")
        for w in result.warnings:
            lines.append(f"  - {w}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pound-plan")
    p.add_argument("start")
    p.add_argument("end")
    p.add_argument(
        "--days",
        type=int,
        default=None,
        help="max day count; omit to infer from --hours-per-day",
    )
    p.add_argument("--hours-per-day", type=float, default=6.0)
    p.add_argument("--verbose", action="store_true", help="show the per-leg list")
    p.add_argument(
        "--locks",
        action="store_true",
        help="show the per-day lock count in the day summary",
    )
    p.add_argument("--boat-beam", type=float, default=None)
    p.add_argument("--boat-draft", type=float, default=None)
    p.add_argument("--boat-length", type=float, default=None)
    p.add_argument("--boat-height", type=float, default=None)
    p.add_argument("--movable-bridge-delay-min", type=_finite_nonnegative, default=None)
    p.add_argument("--artifact", default=str(_DEFAULT_ARTIFACT))
    args = p.parse_args(argv)

    artifact_path = Path(args.artifact)
    if not artifact_path.exists():
        print(f"artifact not found: {artifact_path}", file=sys.stderr)
        return 2

    loaded = load_artifact(artifact_path)
    candidate_index = CandidateSpatialIndex(loaded.graph)

    try:
        constraints = _resolve_start_end(
            args.start,
            args.end,
            loaded,
            candidate_index,
            days=args.days,
            hours_per_day=args.hours_per_day,
            boat_length_m=args.boat_length,
            boat_beam_m=args.boat_beam,
            boat_draft_m=args.boat_draft,
            boat_height_m=args.boat_height,
            movable_bridge_delay_min=args.movable_bridge_delay_min,
        )
    except ValidationError as e:
        print(str(e), file=sys.stderr)
        return 2
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    try:
        result = plan_projected_route(constraints, artifact=loaded).route
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(_render(result, verbose=args.verbose, locks=args.locks))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
