"""Minimal pound-locate CLI — resolve a coordinate to the nearest canal node.

Type a lat/lon pair, get the nearest canal-network node uid + distance (metres).
Plain human-readable stdout; no --json. A future map-click UI uses the
resolve_coord function this CLI wraps (design §6: test harness, not a product
surface).

Usage:
    pound-locate --lat X --lon Y [--artifact PATH] [--max-distance-m N]
"""

import argparse
import sys
from pathlib import Path

from pound.graph.artifact import load_artifact
from pound.route.resolve import resolve_coord

_DEFAULT_ARTIFACT = Path("pound/artifacts/england.pkl")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pound-locate")
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--artifact", default=str(_DEFAULT_ARTIFACT))
    p.add_argument("--max-distance-m", type=float, default=None)
    args = p.parse_args(argv)

    artifact = Path(args.artifact)
    if not artifact.exists():
        print(f"artifact not found: {artifact}", file=sys.stderr)
        return 2

    graph, _ = load_artifact(artifact)
    try:
        uid, dist_m = resolve_coord(args.lat, args.lon, graph)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    name = graph.nodes[uid].get("name") or "-"

    if args.max_distance_m is not None and dist_m > args.max_distance_m:
        print(
            f"nearest canal node is {dist_m:.1f} m away "
            f"-- exceeds --max-distance-m {args.max_distance_m}",
            file=sys.stderr,
        )
        return 1

    print(f"{uid}  {name}  {dist_m:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
