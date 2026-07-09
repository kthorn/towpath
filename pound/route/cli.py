"""Minimal pound-plan CLI — a test harness, not a product surface (design §6).

Type two place names, get a route to eyeball that the engine works on real
data. Plain human-readable stdout; no --json, no fancy formatting. A future
REST API supersedes it.

Usage:
    pound-plan <start> <end> [--days N] [--hours-per-day H]
               [--boat-beam M] [--boat-draft M] [--boat-length M] [--boat-height M]
               [--artifact PATH]
"""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from pound.graph.artifact import load_artifact
from pound.route.plan import plan_route_from_constraints
from pound.schemas import CanalConstraints

_DEFAULT_ARTIFACT = Path("pound/artifacts/england.pkl")


def _render(result) -> str:
    lines = [f"Route: {result.start} -> {result.end}"]
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
    p.add_argument("--days", type=int, required=True)
    p.add_argument("--hours-per-day", type=float, default=6.0)
    p.add_argument("--boat-beam", type=float, default=None)
    p.add_argument("--boat-draft", type=float, default=None)
    p.add_argument("--boat-length", type=float, default=None)
    p.add_argument("--boat-height", type=float, default=None)
    p.add_argument("--artifact", default=str(_DEFAULT_ARTIFACT))
    args = p.parse_args(argv)

    try:
        constraints = CanalConstraints(
            start=args.start,
            end=args.end,
            days=args.days,
            hours_per_day=args.hours_per_day,
            boat_length_m=args.boat_length,
            boat_beam_m=args.boat_beam,
            boat_draft_m=args.boat_draft,
            boat_height_m=args.boat_height,
        )
    except ValidationError as e:
        print(str(e), file=sys.stderr)
        return 2

    artifact = Path(args.artifact)
    if not artifact.exists():
        print(f"artifact not found: {artifact}", file=sys.stderr)
        return 2

    graph, meta = load_artifact(artifact)
    graph.graph["fetched_at"] = meta.get("fetched_at", "")

    try:
        result = plan_route_from_constraints(constraints, graph=graph)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(_render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
