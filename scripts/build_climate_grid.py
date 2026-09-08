"""Prepare, estimate, acquire, and build the offline UK climate grid.

Examples::

    python -m scripts.build_climate_grid prepare --mask data/ons-uk.json \
        --manifest data/climate-grid-manifest.json
    python -m scripts.build_climate_grid estimate --manifest data/climate-grid-manifest.json
    python -m scripts.build_climate_grid acquire-limited \
        --manifest data/climate-grid-manifest.json --max-weighted-calls 1000
    python -m scripts.build_climate_grid build --manifest data/climate-grid-manifest.json \
        --mask data/ons-uk.json --cache-dir data/climate-grid --out artifacts/climate-grid.sqlite

Acquisition is intentionally a separate command and requires an explicit weighted
call ceiling.  ``build`` only reads the annual cache and never contacts a provider.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from pound.climate.artifact import DEFAULT_SOURCE, ClimateSource
from pound_build.ingest.climate_grid import (
    DEFAULT_MASK_SOURCE,
    DEFAULT_WEIGHTED_CALLS_PER_REQUEST,
    GRID_MIN_END_YEAR,
    OPEN_METEO_ARCHIVE_URL,
    ClimateGridBudgetExceeded,
    ClimateGridImporter,
    build_climate_grid,
    download_land_mask,
    generate_grid_cells,
    load_grid_manifest,
    load_land_mask,
    write_grid_manifest,
)


def _end_year(value: str) -> int:
    try:
        year = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("end year must be an integer") from exc
    current_year = datetime.now(UTC).year
    if not GRID_MIN_END_YEAR <= year < current_year:
        raise argparse.ArgumentTypeError(
            f"end year must be a complete year from {GRID_MIN_END_YEAR} through {current_year - 1}"
        )
    return year


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare", help="rasterize a WGS84 mask into a grid manifest")
    prepare.add_argument("--mask", type=Path, required=True)
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument("--spacing-km", type=int, default=10)

    download = commands.add_parser("download-mask", help="download and validate one GeoJSON mask")
    download.add_argument("--url", required=True)
    download.add_argument("--out", type=Path, required=True)

    estimate = commands.add_parser("estimate", help="estimate missing requests without fetching")
    estimate.add_argument("--manifest", type=Path, required=True)
    estimate.add_argument("--cache-dir", type=Path, default=Path("data/climate-grid"))
    estimate.add_argument("--end-year", type=_end_year, default=datetime.now(UTC).year - 1)
    estimate.add_argument(
        "--weighted-calls-per-request", type=int, default=DEFAULT_WEIGHTED_CALLS_PER_REQUEST
    )
    estimate.add_argument("--retries", type=int, default=1)
    estimate.add_argument("--endpoint", default=None)

    acquire = commands.add_parser(
        "acquire-limited", help="fetch missing cache batches under an explicit call ceiling"
    )
    acquire.add_argument("--manifest", type=Path, required=True)
    acquire.add_argument("--cache-dir", type=Path, default=Path("data/climate-grid"))
    acquire.add_argument("--end-year", type=_end_year, default=datetime.now(UTC).year - 1)
    acquire.add_argument("--max-weighted-calls", type=int, required=True)
    acquire.add_argument(
        "--weighted-calls-per-request", type=int, default=DEFAULT_WEIGHTED_CALLS_PER_REQUEST
    )
    acquire.add_argument("--endpoint", default=None)
    acquire.add_argument("--retries", type=int, default=1)
    acquire.add_argument("--backoff-seconds", type=float, default=1.0)
    acquire.add_argument("--request-interval-seconds", type=float, default=7.0)

    build = commands.add_parser("build", help="build SQLite from complete annual cache")
    build.add_argument("--manifest", type=Path, required=True)
    build.add_argument("--mask", type=Path, required=True)
    build.add_argument("--cache-dir", type=Path, default=Path("data/climate-grid"))
    build.add_argument("--end-year", type=_end_year, default=datetime.now(UTC).year - 1)
    build.add_argument("--out", type=Path, default=Path("artifacts/climate-grid.sqlite"))
    build.add_argument("--mask-source-name", default=DEFAULT_MASK_SOURCE["name"])
    build.add_argument("--mask-source-url", default=DEFAULT_MASK_SOURCE["url"])
    build.add_argument("--mask-source-attribution", default=DEFAULT_MASK_SOURCE["attribution"])
    build.add_argument("--built-at", default=None)
    build.add_argument("--mask-simplification-metres", type=float, default=150.0)
    build.add_argument("--endpoint", default=None)
    build.add_argument("--source-name", default=DEFAULT_SOURCE.name)
    build.add_argument("--source-url", default=DEFAULT_SOURCE.url)
    build.add_argument("--source-attribution", default=DEFAULT_SOURCE.attribution)
    build.add_argument("--source-timezone", default=DEFAULT_SOURCE.timezone)
    build.add_argument("--source-model", default=DEFAULT_SOURCE.model)
    return parser


def _source(args: argparse.Namespace) -> ClimateSource:
    return ClimateSource(
        name=args.source_name,
        url=args.source_url,
        attribution=args.source_attribution,
        timezone=args.source_timezone,
        model=args.source_model,
    )


def _json_print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "download-mask":
        output = download_land_mask(args.url, args.out)
        _json_print({"mode": args.command, "output": str(output), "bytes": output.stat().st_size})
        return 0

    if args.command == "prepare":
        mask = load_land_mask(args.mask)
        cells = generate_grid_cells(mask, spacing_km=args.spacing_km)
        output = write_grid_manifest(cells, args.manifest)
        _json_print({"mode": args.command, "cells": len(cells), "manifest": str(output)})
        return 0

    if args.command == "build":
        return _build_main(args)

    locations = load_grid_manifest(args.manifest)
    if args.command == "estimate":
        importer = ClimateGridImporter(
            cache_dir=args.cache_dir,
            weighted_calls_per_request=args.weighted_calls_per_request,
            retries=args.retries,
            endpoint=args.endpoint or OPEN_METEO_ARCHIVE_URL,
            fetcher=lambda *_: {},
        )
        estimate = importer.estimate_weighted_calls(locations, args.end_year)
        _json_print({"mode": args.command, **estimate, "cache_dir": str(args.cache_dir)})
        return 0

    if args.max_weighted_calls <= 0:
        _parser().error("--max-weighted-calls must be positive")
    importer_kwargs = {
        "cache_dir": args.cache_dir,
        "max_weighted_calls": args.max_weighted_calls,
        "weighted_calls_per_request": args.weighted_calls_per_request,
        "retries": args.retries,
        "backoff_seconds": args.backoff_seconds,
        "request_interval_seconds": args.request_interval_seconds,
    }
    if args.endpoint is not None:
        importer_kwargs["endpoint"] = args.endpoint
    importer = ClimateGridImporter(**importer_kwargs)
    completed = 0
    try:
        for _location_id, _year, _payload in importer.iter_limited(locations, args.end_year):
            completed += 1
    except ClimateGridBudgetExceeded as exc:
        _json_print(
            {
                "mode": args.command,
                "status": "budget_exhausted",
                "weighted_calls": importer.weighted_calls,
                "batches_completed": completed,
                "error": str(exc),
            }
        )
        return 2
    _json_print(
        {
            "mode": args.command,
            "status": "complete",
            "batches_completed": completed,
            "weighted_calls": importer.weighted_calls,
            "cache_dir": str(args.cache_dir),
        }
    )
    return 0


def _build_main(args: argparse.Namespace) -> int:
    """Internal build dispatch kept separate so acquisition cannot fall through to it."""

    locations = load_grid_manifest(args.manifest)
    mask = load_land_mask(args.mask)
    output = build_climate_grid(
        locations,
        mask,
        args.cache_dir,
        args.end_year,
        args.out,
        source=_source(args),
        endpoint=args.endpoint,
        mask_source={
            "name": args.mask_source_name,
            "url": args.mask_source_url,
            "attribution": args.mask_source_attribution,
        },
        built_at=args.built_at,
        mask_simplification_metres=args.mask_simplification_metres,
    )
    _json_print(
        {
            "mode": "build",
            "cells": len(locations),
            "output": str(output),
            "bytes": output.stat().st_size,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
