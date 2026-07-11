"""Minimal pound-plan CLI — a test harness, not a product surface (design §6).

Type two place names, get a route to eyeball that the engine works on real
data. Plain human-readable stdout; no --json, no fancy formatting. A future
REST API supersedes it.

Usage:
    pound-plan <start> <end> [--days N] [--hours-per-day H]
               [--boat-beam M] [--boat-draft M] [--boat-length M] [--boat-height M]
               [--verbose] [--locks] [--artifact PATH]

`start` and `end` each accept EITHER a place name (resolved via the gazetteer)
OR a graph node uid (the integer `pound-locate` prints). Auto-detected by shape:
all-digits -> uid, else -> name. Mixed (one uid, one name) is allowed. A place
literally named "42" would mis-resolve as a uid (vanishingly rare; gazetteer
keys are "Oxford"/"Banbury"/etc.); add --start-uid/--end-uid flags if it ever bites.

`--days` is optional: omit it and the day count is inferred from `--hours-per-day`
(you get as many days as the route needs, no cap). Default output is the route
header + totals + the per-day summary + warnings; the node-to-node `Legs:` list
is only printed with `--verbose`.
"""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from pound.graph.artifact import load_artifact
from pound.route.plan import plan_route, plan_route_from_constraints
from pound.route.resolve import resolve_place
from pound.schemas import CanalConstraints, ResolvedConstraints

_DEFAULT_ARTIFACT = Path("pound/artifacts/england.pkl")


def _is_uid(tok: str) -> bool:
    """A bare all-digits token is a uid; anything else is a place name."""
    return tok.isdigit()


def _resolve_start_end(
    start_tok: str,
    end_tok: str,
    graph,
    *,
    days: int | None,
    hours_per_day: float,
    boat_length_m: float | None,
    boat_beam_m: float | None,
    boat_draft_m: float | None,
    boat_height_m: float | None,
) -> CanalConstraints | ResolvedConstraints:
    """Build the routing constraints, auto-detecting uid vs name per token.

    Returns a ResolvedConstraints when any token was a uid (caller routes via
    pure plan_route) or a CanalConstraints when both are names (caller uses the
    plan_route_from_constraints bridge, unchanged from PR2). Mixed uid/name is
    allowed. Dispatch is by isinstance, so the caller does not need a flag.
    """
    start_is_uid = _is_uid(start_tok)
    end_is_uid = _is_uid(end_tok)

    def _resolve(tok: str, is_uid: bool) -> int:
        if is_uid:
            uid = int(tok)
            if uid not in graph:
                raise ValueError(f"uid {uid} is not a node in the graph")
            return uid
        return resolve_place(tok, graph)

    start_uid = _resolve(start_tok, start_is_uid)
    end_uid = _resolve(end_tok, end_is_uid)

    boat = dict(
        boat_length_m=boat_length_m,
        boat_beam_m=boat_beam_m,
        boat_draft_m=boat_draft_m,
        boat_height_m=boat_height_m,
    )

    if start_is_uid or end_is_uid:
        return ResolvedConstraints(
            start_uid=start_uid,
            end_uid=end_uid,
            days=days,
            hours_per_day=hours_per_day,
            **boat,
        )
    return CanalConstraints(
        start=start_tok,
        end=end_tok,
        days=days,
        hours_per_day=hours_per_day,
        **boat,
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
    p.add_argument("--verbose", action="store_true", help="show the per-leg node-to-node list")
    p.add_argument(
        "--locks",
        action="store_true",
        help="show the per-day lock count in the day summary",
    )
    p.add_argument("--boat-beam", type=float, default=None)
    p.add_argument("--boat-draft", type=float, default=None)
    p.add_argument("--boat-length", type=float, default=None)
    p.add_argument("--boat-height", type=float, default=None)
    p.add_argument("--artifact", default=str(_DEFAULT_ARTIFACT))
    args = p.parse_args(argv)

    artifact = Path(args.artifact)
    if not artifact.exists():
        print(f"artifact not found: {artifact}", file=sys.stderr)
        return 2

    graph, meta = load_artifact(artifact)
    graph.graph["fetched_at"] = meta.get("fetched_at", "")

    try:
        constraints = _resolve_start_end(
            args.start,
            args.end,
            graph,
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
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    try:
        if isinstance(constraints, ResolvedConstraints):
            result = plan_route(constraints, graph=graph)
        else:
            result = plan_route_from_constraints(constraints, graph=graph)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(_render(result, verbose=args.verbose, locks=args.locks))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
