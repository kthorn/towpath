"""Acquire and build the UK climate grid directly from Copernicus ERA5-Land.

Raw Zarr chunks and annual daily caches are resumable and contain no credentials.
The build command is strictly offline and reuses the existing grid artifact format.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from pound.climate.artifact import ClimateSource
from pound.climate.grid import ClimateGrid
from pound_build.ingest.climate_cds import (
    CDS_ZARR_URL,
    CdsStore,
    acquire_cells,
    cache_endpoint,
    summer_hours,
)
from pound_build.ingest.climate_grid import build_climate_grid, load_grid_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["acquire", "build"])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--mask", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if not 1974 <= args.end_year < datetime.now(UTC).year:
        parser.error("end-year must allow 25 complete ERA5-Land years")
    locations = load_grid_manifest(args.manifest)
    chunks = args.cache_dir / "chunks"
    annual = args.cache_dir / "annual"
    if args.command == "acquire":
        import zarr

        store = CdsStore(chunks)
        fingerprint = store.verify_snapshot(historical_end=summer_hours(args.end_year)[-1])
        group = zarr.open_consolidated(store, mode="r")
        for report in acquire_cells(locations, group, annual, args.end_year, fingerprint):
            print(
                json.dumps(
                    {
                        **report,
                        "downloaded_chunks": store.downloaded_chunks,
                        "downloaded_bytes": store.downloaded_bytes,
                    }
                ),
                flush=True,
            )
        store.verify_snapshot(
            historical_end=summer_hours(args.end_year)[-1],
            progress=lambda r: print(json.dumps(r), flush=True),
        )
    else:
        if args.mask is None or args.out is None:
            parser.error("build requires --mask and --out")
        identity = json.loads((chunks / "source.json").read_text())
        import hashlib

        fingerprint = hashlib.sha256((chunks / ".zmetadata").read_bytes()).hexdigest()
        if identity != {"url": CDS_ZARR_URL, "metadata_sha256": fingerprint}:
            raise ValueError("CDS source cache identity mismatch")
        source = ClimateSource(
            name="Copernicus ERA5-Land",
            url="https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land",
            attribution="Copernicus Climate Change Service (C3S), CC BY; hourly model extrema, "
            "nearest land point within 15 km; no elevation correction.",
            timezone="Europe/London",
            model="era5_land_hourly:" + fingerprint[:16],
        )
        build_climate_grid(
            locations,
            args.mask,
            annual,
            args.end_year,
            args.out,
            endpoint=cache_endpoint(fingerprint),
            source=source,
        )
        grid = ClimateGrid(args.out)
        surface = grid.surface(8, 25, "high_p90")
        print(
            json.dumps(
                {
                    "artifact": str(args.out),
                    "revision": surface["revision"],
                    "cells": len(surface["cells"]),
                    "available": sum(c["value"] is not None for c in surface["cells"]),
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
