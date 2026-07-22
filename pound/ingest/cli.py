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
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pound.catalog.artifact import prepare_catalog, write_catalog
from pound.catalog.reader import read_catalog
from pound.graph.artifact import _prepare_build_artifact, write_artifact
from pound.graph.build import build_graph
from pound.graph.gazetteer import attach_node_names, build_gazetteer
from pound.graph.locks import attach_locks
from pound.graph.pois import PoiAttachmentIndex, PoiBuildAccumulator, attach_pois
from pound.ingest.diagnostics import PoiDiagnostics
from pound.ingest.osm import (
    prepare_england_pbf,
    read_england_waterways,
    stream_area_pois,
    stream_linear_pois,
)
from pound.ingest.overpass import fetch_oxford
from pound.ingest.profile import BuildProfiler
from pound.ingest.summarize import summarize, summarize_pois
from pound.validate.connectivity import validate_graph

_GEOFABRIK_ENGLAND_URL = (
    "https://download.geofabrik.de/europe/united-kingdom/england-latest.osm.pbf"
)
_ENGLAND_EXPECTED_GIB = 1.5
_POI_BATCH_SIZE = 1024


class _BatchingPoiConsumer:
    def __init__(self, accumulator: Any, *, batch_size: int = _POI_BATCH_SIZE):
        self._accumulator = accumulator
        self._batch_size = batch_size
        self._candidates = []

    def __call__(self, candidate) -> None:
        self._candidates.append(candidate)
        if len(self._candidates) >= self._batch_size:
            self.flush()

    def flush(self) -> None:
        if not self._candidates:
            return
        candidates = self._candidates
        self._candidates = []
        self._accumulator.add_many(candidates)


def _cmd_oxford(args):
    features = fetch_oxford()
    report = summarize(features)
    print(json.dumps(report, indent=2))
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(features.model_dump_json(indent=2))
    return 0


def _catalog_inventory_summary(places) -> dict:
    counts_by_kind = Counter(place.kind for place in places)
    metadata_coverage = Counter()
    for place in places:
        for field, value in place.metadata.model_dump().items():
            if value not in (None, [], {}):
                metadata_coverage[field] += 1
    return {
        "place_count": len(places),
        "counts_by_kind": dict(sorted(counts_by_kind.items())),
        "metadata_coverage": dict(sorted(metadata_coverage.items())),
    }


def _cmd_catalog(args):
    pbf = Path(args.pbf)
    if not pbf.is_file():
        print(f"Missing original England PBF at {pbf}.")
        raise SystemExit(2)

    profiler = BuildProfiler(enabled=args.profile)
    places = read_catalog(pbf, profiler=profiler)
    build_summary = dict(getattr(places, "report", {}))
    metadata = {
        "source": str(pbf),
        "fetched_at": datetime.fromtimestamp(pbf.stat().st_mtime, tz=UTC).isoformat(),
        "built_at": datetime.now(UTC).isoformat(),
        "inventory_summary": _catalog_inventory_summary(places),
        "build_summary": build_summary,
    }
    out = Path(args.out)
    validation_counts = {"places": len(places)}
    with profiler.phase("catalog_artifact_validation", counts=lambda: validation_counts):
        artifact = prepare_catalog(places, metadata)

    serialization_counts: dict[str, int] = {}
    with profiler.phase(
        "catalog_artifact_serialization",
        counts=lambda: serialization_counts,
    ):
        write_catalog(artifact, out)
        if profiler.enabled:
            serialization_counts["output_bytes"] = out.stat().st_size

    print(
        json.dumps(
            {
                "catalog_count": len(artifact.places),
                "inventory_summary": artifact.metadata["inventory_summary"],
                "build_summary": artifact.metadata["build_summary"],
                "output_bytes": out.stat().st_size,
                "catalog_revision": artifact.metadata["catalog_revision"],
            },
            indent=2,
            sort_keys=True,
        )
    )
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
    return _complete_build(
        graph,
        lock_report,
        poi_result,
        poi_ingest_report,
        source,
        fetched_at,
        args,
        profiler,
    )


def _complete_build(
    graph,
    lock_report,
    poi_result,
    poi_ingest_report,
    source,
    fetched_at,
    args,
    profiler: BuildProfiler,
) -> int:
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


def _build_england_multipass(pbf_path: Path, args, profiler: BuildProfiler | None = None) -> int:
    profiler = profiler or BuildProfiler()
    filtered = prepare_england_pbf(pbf_path, profiler)
    features = read_england_waterways(filtered, profiler)
    graph, lock_report = _build_graph_phases(features, profiler)
    source = features.source
    fetched_at = features.fetched_at
    del features

    # The split readers emit each source identity once. Avoid retaining millions of rejected
    # candidate payloads solely to defend against duplicates that the producer excludes.
    accumulator = PoiBuildAccumulator(PoiAttachmentIndex(graph), retain_rejected_winners=False)
    linear_diagnostics = PoiDiagnostics()
    linear_counts = {}
    with profiler.phase("linear_poi_processing", counts=lambda: linear_counts):
        linear_consumer = _BatchingPoiConsumer(accumulator)
        stream_linear_pois(filtered, linear_consumer, linear_diagnostics, linear_counts)
        linear_consumer.flush()
        linear_counts["accepted"] = accumulator.accepted_count

    area_diagnostics = PoiDiagnostics()
    area_counts = {}
    with profiler.phase("area_poi_processing", counts=lambda: area_counts):
        area_consumer = _BatchingPoiConsumer(accumulator)
        stream_area_pois(filtered, area_consumer, area_diagnostics, area_counts)
        area_consumer.flush()
        area_counts["accepted"] = accumulator.accepted_count

    poi_result = accumulator.build_result()
    diagnostics = PoiDiagnostics()
    diagnostics.merge(linear_diagnostics.build_report())
    diagnostics.merge(area_diagnostics.build_report())
    return _complete_build(
        graph,
        lock_report,
        poi_result,
        diagnostics.build_report(),
        source,
        fetched_at,
        args,
        profiler,
    )


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
    return _build_england_multipass(pbf, args, profiler)


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


def _register_catalog(sub):
    catalog = sub.add_parser("catalog", help="build an independent OSM place catalog")
    catalog_sub = catalog.add_subparsers(dest="region", required=True)
    england = catalog_sub.add_parser("england", help="read an original England PBF")
    england.add_argument("--out", required=True)
    england.add_argument("--pbf", required=True, help="original England PBF path")
    england.add_argument(
        "--profile", action="store_true", help="emit build phase JSON Lines to stderr"
    )
    england.set_defaults(func=_cmd_catalog)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pound-ingest")
    sub = parser.add_subparsers(dest="command", required=True)
    _register_oxford(sub)
    _register_build(sub)
    _register_catalog(sub)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
