"""Dev CLI for the ingest pipeline.

Usage:
    python -m pound.ingest.cli oxford [--out pound/data/oxford_canal_waterways.json]

Fetches the Oxford Canal Overpass extract, prints the summarize() report as
JSON, and optionally writes the WaterwayFeatures IR to --out. Network use only.
Not imported by library code.
"""

import argparse
import json
import sys
from pathlib import Path

from pound.ingest.overpass import fetch_oxford
from pound.ingest.summarize import summarize


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pound-ingest")
    parser.add_argument("region", choices=["oxford"], help="region to fetch")
    parser.add_argument(
        "--out",
        default=None,
        help=(
            "path to write the WaterwayFeatures JSON"
            " (e.g. pound/data/oxford_canal_waterways.json)"
        ),
    )
    args = parser.parse_args(argv)

    if args.region == "oxford":
        features = fetch_oxford()
    else:  # pragma: no cover - argparse choices guard this
        parser.error(f"unknown region: {args.region}")
        return

    report = summarize(features)
    print(json.dumps(report, indent=2))

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(features.model_dump_json(indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
