"""Produce a deterministic JSON tag inventory from an original OSM source."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from pound_build.catalog.inventory import inventory_pbf  # pyright: ignore[reportMissingImports]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pbf", type=Path, required=True, help="original PBF or OSM XML path")
    parser.add_argument("--out", type=Path, required=True, help="JSON output path")
    args = parser.parse_args(argv)

    output = args.out.resolve()
    _ensure_external_output(output)
    report = inventory_pbf(args.pbf)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"source: {report.source}")
    print(f"scanned_objects: {report.scanned_objects}")
    print(f"candidate_objects: {report.candidate_objects}")
    print(f"counts_by_kind: {json.dumps(report.counts_by_kind, sort_keys=True)}")
    print(f"tag_coverage_by_kind: {json.dumps(report.tag_coverage_by_kind, sort_keys=True)}")
    print(f"excluded_counts: {json.dumps(report.excluded_counts, sort_keys=True)}")
    return 0


def _ensure_external_output(output: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    package_root = root / "packages" / "pound-core" / "src" / "pound"
    forbidden = (package_root / "data", package_root / "artifacts")
    if any(_is_relative_to(output, directory) for directory in forbidden):
        raise ValueError(
            "generated inventory output cannot be inside repository data or artifact directory"
        )


def _is_relative_to(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
