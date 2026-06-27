"""Dev CLI for the ingest pipeline.

Usage:
    pound-ingest oxford [--out pound/data/oxford_canal_waterways.json]
    pound-ingest build oxford  --out <path> [--tolerance-m M] [--max-unresolved-snaps N]
    pound-ingest build england --out <path> [--tolerance-m M] [--max-unresolved-snaps N]
                               [--pbf PATH] [--overrides PATH]
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from pound.graph.artifact import save_artifact
from pound.graph.build import build_graph, load_overrides
from pound.graph.gazetteer import attach_node_names, build_gazetteer
from pound.graph.locks import attach_locks
from pound.ingest.osm import read_england
from pound.ingest.overpass import fetch_oxford
from pound.ingest.summarize import summarize
from pound.validate.connectivity import validate_graph

_DEFAULT_OVERRIDES = Path("pound/data/overrides.json")
_GEOFABRIK_ENGLAND_URL = "https://download.geofabrik.de/europe/great-britain/england-latest.osm.pbf"
_ENGLAND_EXPECTED_GIB = 1.5


def _cmd_oxford(args):
    features = fetch_oxford()
    report = summarize(features)
    print(json.dumps(report, indent=2))
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(features.model_dump_json(indent=2))
    return 0


def _build_from_features(features, args) -> int:
    overrides_path = Path(args.overrides) if args.overrides else _DEFAULT_OVERRIDES
    overrides = load_overrides(overrides_path)
    graph = build_graph(features, tolerance_m=args.tolerance_m, overrides=overrides)
    attach_node_names(graph, features)
    graph.graph["gazetteer"] = build_gazetteer(features)
    graph.graph["place_nodes_seen"] = sum(1 for n in features.nodes if "place" in n.tags)
    graph, lock_report = attach_locks(graph, features)
    validation = validate_graph(graph, lock_report)

    metadata = {
        "source": features.source,
        "fetched_at": features.fetched_at,
        "built_at": datetime.now(UTC).isoformat(),
        "version": "1",
        "validation": validation,
    }
    print(json.dumps(validation, indent=2))

    fail_reasons = []
    if validation["derelict_edges"] > 0:
        fail_reasons.append("derelict_edges > 0 (filter is broken)")
    if validation["self_loops"] > 0:
        fail_reasons.append("self_loops > 0")
    if len(validation["tolerance_snaps_unresolved"]) > args.max_unresolved_snaps:
        fail_reasons.append(
            f"tolerance_snaps_unresolved={len(validation['tolerance_snaps_unresolved'])} "
            f"> --max-unresolved-snaps={args.max_unresolved_snaps}"
        )
    if fail_reasons:
        for r in fail_reasons:
            print(f"BUILD FAILED: {r}", file=sys.stderr)
        return 1

    out = Path(args.out)
    save_artifact(graph, out, metadata)
    return 0


def _resolve_pbf(args) -> Path:
    if args.pbf:
        return Path(args.pbf)
    return Path(os.environ.get("POUND_PBF_PATH", "pound/data/england.osm.pbf"))


def _cmd_build(args) -> int:
    if args.region == "oxford":
        features = fetch_oxford()
        return _build_from_features(features, args)

    pbf = _resolve_pbf(args)
    if not pbf.exists():
        print(
            f"Missing England extract at {pbf}.\n"
            f"Download manually from:\n  {_GEOFABRIK_ENGLAND_URL}\n"
            f"Expected size ~{_ENGLAND_EXPECTED_GIB} GiB.\n"
            f"Set POUND_PBF_PATH or pass --pbf PATH."
        )
        raise SystemExit(2)
    features = read_england(pbf)
    return _build_from_features(features, args)


def _register_oxford(sub):
    o = sub.add_parser("oxford", help="fetch and summarize Oxford Canal")
    o.add_argument("--out", default=None)
    o.set_defaults(func=_cmd_oxford)


def _register_build(sub):
    b = sub.add_parser("build", help="ingest, build, validate, and save a pickled artifact")
    b.add_argument("region", choices=["oxford", "england"])
    b.add_argument("--out", required=True)
    b.add_argument("--tolerance-m", type=float, default=10.0)
    b.add_argument("--max-unresolved-snaps", type=int, default=0)
    b.add_argument("--pbf", default=None, help="England PBF path (else POUND_PBF_PATH)")
    b.add_argument(
        "--overrides",
        default=None,
        help="overrides.json path (else pound/data/overrides.json)",
    )
    b.set_defaults(func=_cmd_build)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pound-ingest")
    sub = parser.add_subparsers(dest="command", required=True)
    _register_oxford(sub)
    _register_build(sub)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
