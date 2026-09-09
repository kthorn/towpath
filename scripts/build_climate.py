"""Fetch cached climate batches and build the versioned climate artifact.

Examples:
    python -m scripts.build_climate --fetch
    python -m scripts.build_climate --out artifacts/climate.json
    python -m scripts.build_climate --fetch --build --out artifacts/climate.json
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from pound.climate.artifact import write_climate
from pound_build.ingest.climate import ClimateImporter, build_climate, load_location_manifest

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_MANIFEST = _ROOT / "config" / "climate-locations.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locations", type=Path, default=_DEFAULT_MANIFEST)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/climate"))
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument(
        "--out", type=Path, default=Path("artifacts/climate.json"), help="artifact output path"
    )
    parser.add_argument("--fetch", action="store_true", help="fetch missing annual cache files")
    parser.add_argument("--build", action="store_true", help="build from cache after fetching")
    parser.add_argument("--endpoint", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--request-interval-seconds", type=float, default=1.0)
    parser.add_argument("--backoff-seconds", type=float, default=1.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    current_year = datetime.now(UTC).year
    if not 1924 <= args.end_year < current_year:
        _parser().error(
            f"--end-year must be a complete year from 1924 through {current_year - 1}"
        )
    locations = load_location_manifest(args.locations)
    importer_kwargs = {
        "cache_dir": args.cache_dir,
        "retries": args.retries,
        "request_interval_seconds": args.request_interval_seconds,
        "backoff_seconds": args.backoff_seconds,
    }
    if args.endpoint is not None:
        importer_kwargs["endpoint"] = args.endpoint
    importer = ClimateImporter(**importer_kwargs)

    if args.fetch:
        histories = importer.fetch_histories(locations, args.end_year)
        print(
            json.dumps(
                {
                    "mode": "fetch",
                    "locations": len(histories),
                    "years_per_location": 25,
                    "cache_dir": str(args.cache_dir),
                },
                sort_keys=True,
            )
        )
        if not args.build:
            return 0

    if args.out is None:
        _parser().error("--out is required for build mode")
    histories = importer.load_cached_histories(locations, args.end_year)
    artifact = build_climate(locations, args.end_year, histories)
    write_climate(artifact, args.out)
    print(
        json.dumps(
            {
                "mode": "build",
                "locations": len(artifact.locations),
                "end_year": artifact.end_year,
                "revision": artifact.revision,
                "output": str(args.out),
                "output_bytes": args.out.stat().st_size,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
