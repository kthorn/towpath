"""Dev CLI for the ingest pipeline.

Usage:
    python -m pound.ingest.cli oxford [--out pound/data/oxford_canal_waterways.json]
    python -m pound.ingest.cli build oxford --out pound/artifacts/oxford.pkl

Fetches the Oxford Canal Overpass extract, prints the summarize() report as
JSON, and optionally writes the WaterwayFeatures IR to --out. The `build`
subcommand ingests, builds the graph, attaches locks, validates, and writes a
pickled artifact. Network use only. Not imported by library code.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from pound.graph.artifact import save_artifact
from pound.graph.build import build_graph
from pound.graph.locks import attach_locks
from pound.ingest.overpass import fetch_oxford
from pound.ingest.summarize import summarize
from pound.validate.connectivity import validate_graph


def _cmd_oxford(args: argparse.Namespace) -> int:
    features = fetch_oxford()
    report = summarize(features)
    print(json.dumps(report, indent=2))

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(features.model_dump_json(indent=2))
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    features = fetch_oxford()
    graph = build_graph(features)
    graph, lock_report = attach_locks(graph, features)
    validation = validate_graph(graph, lock_report)

    metadata = {
        "source": features.source,
        "fetched_at": features.fetched_at,
        "built_at": datetime.now(UTC).isoformat(),
        "version": "1",
        "validation": validation,
    }

    out = Path(args.out)
    save_artifact(graph, out, metadata)
    print(json.dumps(validation, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pound-ingest")
    subparsers = parser.add_subparsers(dest="command", required=True)

    oxford_parser = subparsers.add_parser("oxford", help="fetch and summarize Oxford Canal")
    oxford_parser.add_argument(
        "--out",
        default=None,
        help=(
            "path to write the WaterwayFeatures JSON (e.g. pound/data/oxford_canal_waterways.json)"
        ),
    )
    oxford_parser.set_defaults(func=_cmd_oxford)

    build_parser = subparsers.add_parser(
        "build", help="ingest, build graph, attach locks, validate, and save a pickled artifact"
    )
    build_parser.add_argument("region", choices=["oxford"], help="region to fetch and build")
    build_parser.add_argument(
        "--out",
        required=True,
        help="path to write the pickled graph artifact (e.g. pound/artifacts/oxford.pkl)",
    )
    build_parser.set_defaults(func=_cmd_build)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
