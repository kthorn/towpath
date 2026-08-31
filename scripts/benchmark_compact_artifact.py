"""Measure compact routing artifacts and compare representative route behavior."""

from __future__ import annotations

import argparse
import json
import pickle  # pi-lens-ignore: python-pickle
import resource
import subprocess
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, cast

_GEOMETRY_BOUND_M = 1.0
_DISTANCE_BOUND_M = 1.0
_REPRESENTATIVE_ROUTES = (
    {
        "name": "oxford-banbury",
        "start": (51.7520131, -1.2578499),
        "end": (52.0601807, -1.3402795),
    },
    {
        "name": "bath-reading",
        "start": (51.3813864, -2.3596963),
        "end": (51.4564242, -0.9700664),
    },
    {
        "name": "leeds-skipton",
        "start": (53.7974185, -1.5437941),
        "end": (53.9618497, -2.0160287),
    },
    {
        "name": "ely-cambridge",
        "start": (52.3990199, 0.262039),
        "end": (52.2055314, 0.1186637),
    },
)
_METRIC_FIELDS = (
    "artifact_bytes",
    "graph_pickle_bytes",
    "unpickle_seconds",
    "compatibility_check_seconds",
    "graph_index_seconds",
    "candidate_index_seconds",
    "poi_index_seconds",
    "startup_seconds",
    "peak_rss_kib",
    "nodes",
    "edges",
    "geometry_coordinates",
    "candidate_samples",
)


def _timed[T](call: Callable[[], T]) -> tuple[T, float]:
    started = time.perf_counter()
    result = call()
    return result, time.perf_counter() - started


def _rounded(value: float) -> float:
    return round(value, 6)


def _case_coordinates(case: Mapping[str, Any], field: str) -> tuple[float, float]:
    value = case[field]
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError(f"route case {case.get('name', '<unnamed>')!r} has invalid {field}")
    return float(value[0]), float(value[1])


def _route_record_current(artifact, candidate_index, case: Mapping[str, Any]) -> dict[str, Any]:
    from pound.route.plan import (  # pyright: ignore[reportMissingImports]
        RouteUnavailableError,
        _compute_traversal,
        plan_projected_route,
    )
    from pound.schemas import ProjectedRouteConstraints  # pyright: ignore[reportMissingImports]

    try:
        start = candidate_index.nearest_projection(*_case_coordinates(case, "start"))
        end = candidate_index.nearest_projection(*_case_coordinates(case, "end"))
        if start is None or end is None:
            raise ValueError("no projected route endpoint")
        constraints = ProjectedRouteConstraints(start=start[0].handle, end=end[0].handle)
        traversal = _compute_traversal(constraints, artifact.graph)
        response = plan_projected_route(constraints, artifact=artifact)
    except (RouteUnavailableError, ValueError):
        return {
            "available": False,
            "source_distance_m": None,
            "infrastructure": {},
            "restrictions": [],
            "_geometry": None,
        }

    restrictions = [
        f"access:{segment.osm_way_id}:{segment.kind}:{segment.tag}:{segment.value}"
        for segment in response.route.access_segments
    ]
    restrictions.extend(
        warning
        for warning in response.route.warnings
        if warning.startswith("tunnel way ") or warning.startswith("draft/beam unknown")
    )
    return {
        "available": True,
        "source_distance_m": _rounded(
            sum(
                float(artifact.graph.edges[edge.u, edge.v]["length_m"])
                * abs(edge.end_fraction - edge.start_fraction)
                for edge in traversal.edges
            )
        ),
        "infrastructure": {"locks": response.route.total_locks},
        "restrictions": sorted(set(restrictions)),
        "_geometry": [list(point) for point in response.geometry.coordinates],
    }


def _geometry_deviation_m(
    before: list[list[float]] | None, after: list[list[float]] | None
) -> float | None:
    if before is None or after is None:
        return None
    from pyproj import Transformer  # pyright: ignore[reportMissingImports]
    from shapely import transform  # pyright: ignore[reportMissingImports]
    from shapely.geometry import LineString  # pyright: ignore[reportMissingImports]

    to_bng = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
    before_line = transform(LineString(before), cast(Any, to_bng.transform), interleaved=False)
    after_line = transform(LineString(after), cast(Any, to_bng.transform), interleaved=False)
    return _rounded(
        max(
            float(before_line.hausdorff_distance(after_line)),
            float(after_line.hausdorff_distance(before_line)),
        )
    )


def _public_route_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if not key.startswith("_")}


def _route_cases_from_legacy(
    routes: Iterable[tuple[str, Mapping[str, Any]]],
) -> tuple[dict[str, Any], ...]:
    """Reuse the detailed route's selected node coordinates for compact routing."""
    cases = []
    for name, record in routes:
        start = record.get("_source_start")
        end = record.get("_source_end")
        if start is None or end is None:
            continue
        cases.append(
            {
                "name": name,
                "start": _case_coordinates({"start": start}, "start"),
                "end": _case_coordinates({"end": end}, "end"),
            }
        )
    return tuple(cases)


def _route_parity(
    before_routes: Iterable[tuple[str, Mapping[str, Any]]],
    after_routes: Iterable[tuple[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    before_by_name = dict(before_routes)
    after_by_name = dict(after_routes)
    names = sorted(set(before_by_name) | set(after_by_name))
    cases = []
    for name in names:
        before = before_by_name.get(
            name,
            {
                "available": False,
                "source_distance_m": None,
                "infrastructure": {},
                "restrictions": [],
                "_geometry": None,
            },
        )
        after = after_by_name.get(
            name,
            {
                "available": False,
                "source_distance_m": None,
                "infrastructure": {},
                "restrictions": [],
                "_geometry": None,
            },
        )
        both_available = bool(before["available"] and after["available"])
        geometry_deviation_m = _geometry_deviation_m(before["_geometry"], after["_geometry"])
        matches = {
            "availability": before["available"] == after["available"],
            "source_distance": (
                not both_available
                or abs(before["source_distance_m"] - after["source_distance_m"])
                <= _DISTANCE_BOUND_M
            ),
            "infrastructure": (
                not both_available or before["infrastructure"] == after["infrastructure"]
            ),
            "restrictions": not both_available or before["restrictions"] == after["restrictions"],
            "geometry_bound": (
                geometry_deviation_m is None or geometry_deviation_m <= _GEOMETRY_BOUND_M
            ),
        }
        cases.append(
            {
                "name": name,
                "before": _public_route_record(before),
                "after": _public_route_record(after),
                "geometry_deviation_m": geometry_deviation_m,
                "matches": matches,
            }
        )
    return {"all_match": all(all(case["matches"].values()) for case in cases), "cases": cases}


def _boat_hire_report(before: Path, after: Path, enrichment: Path | None) -> dict[str, Any]:
    if enrichment is None:
        return {
            "bases": [],
            "old_threshold_breaches": [],
            "threshold_breaches": [],
            "required_exception_changes": [],
        }
    from scripts.verify_boat_hire_snaps import (  # pyright: ignore[reportMissingImports]
        verify_boat_hire_snaps,
    )

    return verify_boat_hire_snaps(before, after, enrichment)


def _startup_seconds(path: Path, catalog: Path | None, enrichment: Path | None) -> float | None:
    if enrichment is None:
        return None
    from pound_web.app import create_app  # pyright: ignore[reportMissingImports]
    from pound_web.config import WebSettings  # pyright: ignore[reportMissingImports]

    settings = WebSettings(
        artifact_path=path,
        static_dir=Path("."),
        boat_hire_enrichment_path=enrichment,
        catalog_path=catalog,
    )
    _, elapsed = _timed(lambda: _start_app(create_app(settings)))
    return _rounded(elapsed)


def _start_app(app) -> None:
    from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

    with TestClient(app):
        pass


def _current_artifact_report(
    path: Path,
    *,
    catalog: Path | None = None,
    enrichment: Path | None = None,
    route_cases: Iterable[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]]:
    from pound.artifact import load_artifact  # pyright: ignore[reportMissingImports]
    from pound.graph.spatial import (  # pyright: ignore[reportMissingImports]
        CandidateSpatialIndex,
        GraphSpatialIndex,
        PoiSpatialIndex,
    )

    _, unpickle_seconds = _timed(lambda: _load_pickle(path))
    artifact, compatibility_seconds = _timed(lambda: load_artifact(path))
    graph_index, graph_index_seconds = _timed(lambda: GraphSpatialIndex(artifact.graph))
    candidate_index, candidate_index_seconds = _timed(lambda: CandidateSpatialIndex(artifact.graph))
    _, poi_index_seconds = _timed(lambda: PoiSpatialIndex(artifact.pois))
    graph_pickle_bytes = len(pickle.dumps(artifact.graph, protocol=pickle.HIGHEST_PROTOCOL))
    routes = [
        (str(case["name"]), _route_record_current(artifact, candidate_index, case))
        for case in route_cases
    ]
    metrics = {
        "artifact_bytes": path.stat().st_size,
        "graph_pickle_bytes": graph_pickle_bytes,
        "unpickle_seconds": _rounded(unpickle_seconds),
        "compatibility_check_seconds": _rounded(compatibility_seconds),
        "graph_index_seconds": _rounded(graph_index_seconds),
        "candidate_index_seconds": _rounded(candidate_index_seconds),
        "poi_index_seconds": _rounded(poi_index_seconds),
        "startup_seconds": _startup_seconds(path, catalog, enrichment),
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "nodes": artifact.graph.number_of_nodes(),
        "edges": artifact.graph.number_of_edges(),
        "geometry_coordinates": sum(
            len(data.get("geometry", ())) for _, _, data in artifact.graph.edges(data=True)
        ),
        "candidate_samples": len(graph_index.candidate_index.candidate_points),
    }
    return metrics, routes


def _load_pickle(path: Path) -> Any:
    with path.open("rb") as stream:
        return pickle.load(stream)  # pi-lens-ignore: python-pickle


def benchmark_artifacts(
    before: Path,
    after: Path,
    *,
    catalog: Path | None = None,
    boat_hire_enrichment: Path | None = None,
    route_cases: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Return deterministic benchmark sections for two current-format artifacts."""
    before_metrics, before_routes = _current_artifact_report(
        Path(before), enrichment=boat_hire_enrichment, route_cases=route_cases
    )
    after_metrics, after_routes = _current_artifact_report(
        Path(after),
        catalog=catalog,
        enrichment=boat_hire_enrichment,
        route_cases=route_cases,
    )
    report = {
        metric: {"before": before_metrics[metric], "after": after_metrics[metric]}
        for metric in _METRIC_FIELDS
    }
    report["boat_hire_snaps"] = _boat_hire_report(Path(before), Path(after), boat_hire_enrichment)
    report["route_parity"] = _route_parity(before_routes, after_routes)
    return report


def _legacy_route_record(artifact, graph_index, case: Mapping[str, Any]) -> dict[str, Any]:
    from pound.route.plan import (  # pyright: ignore[reportMissingImports]
        RouteUnavailableError,
        _compute_route,
        plan_canal_route,
    )
    from pound.route.resolve import resolve_coord  # pyright: ignore[reportMissingImports]
    from pound.schemas import ResolvedConstraints  # pyright: ignore[reportMissingImports]

    try:
        start_uid, _ = resolve_coord(*_case_coordinates(case, "start"), artifact.graph, graph_index)
        end_uid, _ = resolve_coord(*_case_coordinates(case, "end"), artifact.graph, graph_index)
        constraints = ResolvedConstraints(start_uid=start_uid, end_uid=end_uid)
        computed = _compute_route(constraints, graph=artifact.graph)
        response = plan_canal_route(constraints, graph=artifact.graph)
        start_node = artifact.graph.nodes[start_uid]
        end_node = artifact.graph.nodes[end_uid]
    except (RouteUnavailableError, ValueError):
        return {
            "available": False,
            "source_distance_m": None,
            "infrastructure": {},
            "restrictions": [],
            "_geometry": None,
        }

    restrictions = [
        f"access:{segment.osm_way_id}:{segment.kind}:{segment.tag}:{segment.value}"
        for segment in response.route.access_segments
    ]
    restrictions.extend(
        warning
        for warning in response.route.warnings
        if warning.startswith("tunnel way ") or warning.startswith("draft/beam unknown")
    )
    return {
        "available": True,
        "source_distance_m": _rounded(
            sum(
                float(artifact.graph.edges[u, v]["length_m"])
                for u, v in zip(computed.path, computed.path[1:], strict=False)
            )
        ),
        "infrastructure": {"locks": response.route.total_locks},
        "restrictions": sorted(set(restrictions)),
        "_geometry": [list(point) for point in response.geometry.coordinates],
        "_source_start": [start_node["lat"], start_node["lon"]],
        "_source_end": [end_node["lat"], end_node["lon"]],
    }


def _legacy_startup_seconds(path: Path, enrichment: Path | None) -> float | None:
    if enrichment is None:
        return None
    from pound.web.app import create_app  # pyright: ignore[reportMissingImports]
    from pound.web.config import WebSettings  # pyright: ignore[reportMissingImports]

    settings = WebSettings(
        artifact_path=path,
        static_dir=Path("."),
        boat_hire_enrichment_path=enrichment,
    )
    _, elapsed = _timed(lambda: _start_app(create_app(settings)))
    return _rounded(elapsed)


def _legacy_artifact_report(
    path: Path,
    *,
    enrichment: Path | None,
    route_cases: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    from pound.graph.artifact import load_artifact  # pyright: ignore[reportMissingImports]
    from pound.graph.spatial import (  # pyright: ignore[reportMissingImports]
        GraphSpatialIndex,
        PoiSpatialIndex,
    )
    from pound.web.boat_hire import load_boat_hire_seeds  # pyright: ignore[reportMissingImports]

    _, unpickle_seconds = _timed(lambda: _load_pickle(path))
    artifact, compatibility_seconds = _timed(lambda: load_artifact(path))
    graph_index, graph_index_seconds = _timed(lambda: GraphSpatialIndex(artifact.graph))
    _, poi_index_seconds = _timed(lambda: PoiSpatialIndex(artifact.pois))
    routes = [
        (str(case["name"]), _legacy_route_record(artifact, graph_index, case))
        for case in route_cases
    ]
    boats = []
    if enrichment is not None:
        for seed in sorted(load_boat_hire_seeds(enrichment), key=lambda item: item.identity):
            edge, _projected, distance_m = graph_index.project_to_nearest_edge(
                seed.latitude, seed.longitude
            )
            boats.append(
                {
                    "identity": seed.identity,
                    "edge": list(edge),
                    "snap_distance_m": float(distance_m),
                }
            )
    metrics = {
        "artifact_bytes": path.stat().st_size,
        "graph_pickle_bytes": len(pickle.dumps(artifact.graph, protocol=pickle.HIGHEST_PROTOCOL)),
        "unpickle_seconds": _rounded(unpickle_seconds),
        "compatibility_check_seconds": _rounded(compatibility_seconds),
        "graph_index_seconds": _rounded(graph_index_seconds),
        "candidate_index_seconds": None,
        "poi_index_seconds": _rounded(poi_index_seconds),
        "startup_seconds": _legacy_startup_seconds(path, enrichment),
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "nodes": artifact.graph.number_of_nodes(),
        "edges": artifact.graph.number_of_edges(),
        "geometry_coordinates": sum(
            len(data.get("geometry", ())) for _, _, data in artifact.graph.edges(data=True)
        ),
        "candidate_samples": 0,
    }
    return {"metrics": metrics, "routes": routes, "boats": boats}


def _primary_checkout() -> Path:
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        check=True,
        text=True,
        capture_output=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            return Path(line.removeprefix("worktree "))
    raise RuntimeError("could not find the primary checkout")


def _legacy_report_subprocess(
    before: Path, enrichment: Path | None
) -> tuple[dict[str, Any], list[tuple[str, Mapping[str, Any]]], list[dict[str, Any]]]:
    command = [
        "uv",
        "run",
        "python",
        str(Path(__file__).resolve()),
        "--legacy-report",
        "--artifact",
        str(before.resolve()),
    ]
    if enrichment is not None:
        command.extend(["--boat-hire-enrichment", str(enrichment.resolve())])
    result = subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=True,
        cwd=_primary_checkout(),
    )
    payload = json.loads(result.stdout)
    return payload["metrics"], payload["routes"], payload["boats"]


def _combined_boat_hire_report(
    old_boats: Iterable[Mapping[str, Any]],
    after: Path,
    enrichment: Path | None,
) -> dict[str, Any]:
    if enrichment is None:
        return {
            "bases": [],
            "old_threshold_breaches": [],
            "threshold_breaches": [],
            "required_exception_changes": [],
        }
    from pound.artifact import load_artifact  # pyright: ignore[reportMissingImports]
    from pound.graph.spatial import GraphSpatialIndex  # pyright: ignore[reportMissingImports]
    from pound_web.boat_hire import (  # pyright: ignore[reportMissingImports]
        BOAT_HIRE_OVERLAY_DISTANCE_EXCEPTIONS_M,
        BOAT_HIRE_OVERLAY_DISTANCE_M,
        load_boat_hire_seeds,
    )

    old_by_identity = {record["identity"]: record for record in old_boats}
    index = GraphSpatialIndex(load_artifact(after).graph)
    bases = []
    old_threshold_breaches = []
    threshold_breaches = []
    required_exception_changes = []
    for seed in sorted(load_boat_hire_seeds(enrichment), key=lambda item: item.identity):
        old = old_by_identity[seed.identity]
        new, new_distance = index.candidate_index.nearest_projection(seed.latitude, seed.longitude)
        if new is None:
            raise ValueError(f"Boat-hire seed {seed.identity} could not be projected")
        limit = BOAT_HIRE_OVERLAY_DISTANCE_EXCEPTIONS_M.get(
            seed.identity, BOAT_HIRE_OVERLAY_DISTANCE_M
        )
        if old["snap_distance_m"] > limit:
            old_threshold_breaches.append(seed.identity)
        if new_distance > limit:
            threshold_breaches.append(seed.identity)
            required_exception_changes.append(seed.identity)
        elif (
            new_distance > BOAT_HIRE_OVERLAY_DISTANCE_M
            and seed.identity not in BOAT_HIRE_OVERLAY_DISTANCE_EXCEPTIONS_M
        ):
            required_exception_changes.append(seed.identity)
        bases.append(
            {
                "identity": seed.identity,
                "old_edge": old["edge"],
                "old_snap_distance_m": old["snap_distance_m"],
                "new_edge": list(new.handle.edge),
                "new_snap_distance_m": float(new_distance),
            }
        )
    return {
        "bases": bases,
        "old_threshold_breaches": old_threshold_breaches,
        "threshold_breaches": threshold_breaches,
        "required_exception_changes": required_exception_changes,
    }


def _benchmark_with_legacy_before(
    before: Path,
    after: Path,
    *,
    catalog: Path | None,
    enrichment: Path | None,
) -> dict[str, Any]:
    before_metrics, before_routes, old_boats = _legacy_report_subprocess(before, enrichment)
    after_metrics, after_routes = _current_artifact_report(
        after,
        catalog=catalog,
        enrichment=enrichment,
        route_cases=_route_cases_from_legacy(before_routes),
    )
    report = {
        metric: {"before": before_metrics[metric], "after": after_metrics[metric]}
        for metric in _METRIC_FIELDS
    }
    report["boat_hire_snaps"] = _combined_boat_hire_report(old_boats, after, enrichment)
    report["route_parity"] = _route_parity(before_routes, after_routes)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path)
    parser.add_argument("--after", type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument(
        "--boat-hire-enrichment",
        type=Path,
        default=Path("data/boat-hire-enrichment.csv"),
    )
    parser.add_argument("--legacy-report", action="store_true")
    parser.add_argument("--artifact", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.legacy_report:
        if args.artifact is None:
            raise ValueError("--legacy-report requires --artifact")
        print(
            json.dumps(
                _legacy_artifact_report(
                    args.artifact,
                    enrichment=args.boat_hire_enrichment,
                    route_cases=_REPRESENTATIVE_ROUTES,
                ),
                sort_keys=True,
            )
        )
        return 0
    if args.before is None or args.after is None:
        raise ValueError("--before and --after are required")
    try:
        report = benchmark_artifacts(
            args.before,
            args.after,
            catalog=args.catalog,
            boat_hire_enrichment=args.boat_hire_enrichment,
            route_cases=_REPRESENTATIVE_ROUTES,
        )
    except ModuleNotFoundError as exc:
        if not exc.name or not exc.name.startswith("pound."):
            raise
        report = _benchmark_with_legacy_before(
            args.before,
            args.after,
            catalog=args.catalog,
            enrichment=args.boat_hire_enrichment,
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
