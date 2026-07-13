"""Dev CLI for the ingest pipeline.

Usage:
    pound-ingest oxford [--out pound/data/oxford_canal_waterways.json]
    pound-ingest build oxford  --out <path>
    pound-ingest build england --out <path> [--pbf PATH]
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from pound.graph.artifact import _prepare_build_artifact, write_artifact
from pound.graph.build import build_graph
from pound.graph.gazetteer import attach_node_names, build_gazetteer
from pound.graph.locks import attach_locks
from pound.graph.pois import attach_pois
from pound.ingest.osm import read_england
from pound.ingest.overpass import fetch_oxford
from pound.ingest.profile import BuildProfiler
from pound.ingest.summarize import summarize, summarize_pois
from pound.validate.connectivity import validate_graph

_GEOFABRIK_ENGLAND_URL = (
    "https://download.geofabrik.de/europe/united-kingdom/england-latest.osm.pbf"
)
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


def _build_graph_phases(features, profiler: BuildProfiler):
    graph_counts = {"input_nodes": len(features.nodes), "input_ways": len(features.ways)}
    with profiler.phase("graph_build", counts=lambda: graph_counts):
        graph = build_graph(features)
        graph_counts.update(nodes=graph.number_of_nodes(), edges=graph.number_of_edges())

    annotation_counts = {}
    with profiler.phase("graph_annotation", counts=lambda: annotation_counts):
        attach_node_names(graph, features)
        graph.graph["gazetteer"] = build_gazetteer(features)
        graph.graph["place_nodes_seen"] = sum(1 for n in features.nodes if "place" in n.tags)
        annotation_counts.update(
            gazetteer_entries=len(graph.graph["gazetteer"]),
            place_nodes_seen=graph.graph["place_nodes_seen"],
        )

    lock_counts = {}
    with profiler.phase("lock_attachment", counts=lambda: lock_counts):
        graph, lock_report = attach_locks(graph, features, in_place=True)
        lock_counts.update(graph_nodes=graph.number_of_nodes(), graph_edges=graph.number_of_edges())
    return graph, lock_report


def _attach_poi_phase(graph, poi_candidates, profiler: BuildProfiler):
    poi_counts = {"candidates": len(poi_candidates)}
    with profiler.phase("poi_attachment", counts=lambda: poi_counts):
        poi_result = attach_pois(graph, poi_candidates)
        poi_counts["accepted"] = len(poi_result.pois)
    return poi_result


def _build_from_features(features, args, profiler: BuildProfiler | None = None) -> int:
    profiler = profiler or BuildProfiler()
    graph, lock_report = _build_graph_phases(features, profiler)

    poi_candidates = features.poi_candidates
    poi_ingest_report = features.poi_ingest_report
    source = features.source
    fetched_at = features.fetched_at
    del features

    poi_result = _attach_poi_phase(graph, poi_candidates, profiler)
    del poi_candidates
    validation = validate_graph(graph, lock_report, poi_result.summary)
    poi_summary = summarize_pois(poi_result.pois, poi_ingest_report, poi_result.summary)
    del poi_ingest_report

    metadata = {
        "source": source,
        "fetched_at": fetched_at,
        "built_at": datetime.now(UTC).isoformat(),
        "validation": validation,
        "poi_summary": poi_summary,
    }
    print(json.dumps({"validation": validation, "poi_summary": poi_summary}, indent=2))

    fail_reasons = []
    if validation["derelict_edges"] > 0:
        fail_reasons.append("derelict_edges > 0 (filter is broken)")
    if validation["self_loops"] > 0:
        fail_reasons.append("self_loops > 0")
    if validation["poi_duplicate_identities"] > 0:
        fail_reasons.append("poi_duplicate_identities > 0")
    if fail_reasons:
        for r in fail_reasons:
            print(f"BUILD FAILED: {r}", file=sys.stderr)
        return 1

    out = Path(args.out)
    validation_counts = {"pois": len(poi_result.pois)}
    with profiler.phase("artifact_validation", counts=lambda: validation_counts):
        artifact = _prepare_build_artifact(graph, poi_result.pois, metadata)

    serialization_counts = {}
    with profiler.phase("artifact_serialization", counts=lambda: serialization_counts):
        write_artifact(artifact, out)
        if profiler.enabled:
            serialization_counts["output_bytes"] = out.stat().st_size
    return 0


def _resolve_pbf(args) -> Path:
    if args.pbf:
        return Path(args.pbf)
    return Path(os.environ.get("POUND_PBF_PATH", "pound/data/england.osm.pbf"))


def _cmd_build(args) -> int:
    profiler = BuildProfiler(enabled=args.profile)
    if args.region == "oxford":
        return _build_from_features(fetch_oxford(), args, profiler)

    pbf = _resolve_pbf(args)
    if not pbf.exists():
        print(
            f"Missing England extract at {pbf}.\n"
            f"Download manually from:\n  {_GEOFABRIK_ENGLAND_URL}\n"
            f"Expected size ~{_ENGLAND_EXPECTED_GIB} GiB.\n"
            f"Set POUND_PBF_PATH or pass --pbf PATH."
        )
        raise SystemExit(2)
    return _build_from_features(read_england(pbf, profiler=profiler), args, profiler)


def _register_oxford(sub):
    o = sub.add_parser("oxford", help="fetch and summarize Oxford Canal")
    o.add_argument("--out", default=None)
    o.set_defaults(func=_cmd_oxford)


def _register_build(sub):
    b = sub.add_parser("build", help="ingest, build, validate, and save a pickled artifact")
    b.add_argument("region", choices=["oxford", "england"])
    b.add_argument("--out", required=True)
    b.add_argument("--pbf", default=None, help="England PBF path (else POUND_PBF_PATH)")
    b.add_argument("--profile", action="store_true", help="emit build phase JSON Lines to stderr")
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
