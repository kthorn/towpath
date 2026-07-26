"""Measure bounded nationwide catalog queries through the public spatial contract."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import resource
except ImportError:  # pragma: no cover - resource is unavailable on some platforms
    resource = None

from pound.catalog.artifact import load_catalog
from pound.catalog.manifest import MAX_CATALOG_RADIUS_M
from pound.catalog.spatial import MAX_CATALOG_QUERY_WORK, CatalogSpatialIndex
from pound.graph.artifact import load_artifact
from pound.graph.spatial import GraphSpatialIndex
from pound.schemas import CatalogPlacesRequest, GeoJSONLineString, MapBounds

MAX_QUERY_WORK = MAX_CATALOG_QUERY_WORK
DEFAULT_WARMUPS = 2
DEFAULT_ITERATIONS = 7

# These fixed viewports keep comparisons stable across artifacts and hosts.  The
# broad entries are candidates for the bounded worst-case case; any viewport
# over the public 100,000-candidate budget is excluded before it is queried.
_PREDEFINED_VIEWPORTS = (
    ("oxford", MapBounds(south=51.7, west=-1.4, north=51.9, east=-1.1)),
    ("milton_keynes", MapBounds(south=52.0, west=-0.9, north=52.2, east=-0.6)),
    ("london", MapBounds(south=51.3, west=-0.6, north=51.7, east=0.3)),
    ("birmingham", MapBounds(south=52.3, west=-2.1, north=52.6, east=-1.6)),
    ("manchester", MapBounds(south=53.3, west=-2.6, north=53.7, east=-1.9)),
)

_LOCALITY_KINDS = [
    "pub",
    "cafe",
    "restaurant",
    "supermarket",
    "convenience",
    "museum",
    "gallery",
    "historic_site",
    "garden",
    "wildlife_attraction",
    "landmark",
]
_ROUTE_KINDS = ["pub", "cafe", "restaurant", "museum", "marina"]
_WATERWAY_KINDS = ["marina", "mooring", "fuel", "water_point", "sanitary_disposal"]
# Keep this at the API's maximum so the dense case exercises the full validated
# kind-selection path without violating MAX_CATALOG_KINDS.
_DENSE_KINDS = [
    "pub",
    "cafe",
    "restaurant",
    "supermarket",
    "convenience",
    "bakery",
    "marina",
    "mooring",
    "fuel",
    "water_point",
    "sanitary_disposal",
    "museum",
    "gallery",
    "historic_site",
    "garden",
    "landmark",
]

_ROUTE_GEOMETRY = GeoJSONLineString(
    type="LineString",
    coordinates=[(-0.85, 52.03), (-0.75, 52.08), (-0.65, 52.15)],
)
_DAY_GEOMETRY = GeoJSONLineString(
    type="LineString",
    coordinates=[(-0.81, 52.05), (-0.73, 52.10)],
)


@dataclass(frozen=True)
class BenchmarkCase:
    """One deterministic request and its cheap viewport candidate count."""

    name: str
    request: CatalogPlacesRequest
    candidate_count: int
    viewport_name: str


def _request(
    catalog_revision: str,
    *,
    bounds: MapBounds,
    kinds: list[str],
    policy: dict[str, Any],
    route_geometry: GeoJSONLineString | None = None,
    day_geometry: GeoJSONLineString | None = None,
    day: int | None = None,
) -> CatalogPlacesRequest:
    return CatalogPlacesRequest.model_validate(
        {
            "catalog_revision": catalog_revision,
            "kinds": kinds,
            "bounds": bounds,
            "route_geometry": route_geometry,
            "day_geometry": day_geometry,
            "day": day,
            "policy": policy,
        }
    )


def _bounded_candidate_count(index, bounds: MapBounds) -> int:
    count = index.viewport_candidate_count(bounds)
    if count > MAX_QUERY_WORK:
        raise ValueError(
            f"benchmark viewport has {count:,} candidates, exceeding "
            f"the {MAX_QUERY_WORK:,}-candidate work budget"
        )
    return count


def build_benchmark_cases(catalog_revision: str, index) -> tuple[BenchmarkCase, ...]:
    """Build deterministic representative cases and select the dense viewport.

    ``index`` only supplies the public ``viewport_candidate_count`` method; all
    measured work later goes through ``CatalogSpatialIndex.query``.
    """

    viewports = dict(_PREDEFINED_VIEWPORTS)
    locality_bounds = viewports["oxford"]
    route_bounds = viewports["milton_keynes"]
    locality = BenchmarkCase(
        name="locality_no_policy",
        request=_request(
            catalog_revision,
            bounds=locality_bounds,
            kinds=_LOCALITY_KINDS,
            policy={"basis": "none", "radius_m": None},
        ),
        candidate_count=_bounded_candidate_count(index, locality_bounds),
        viewport_name="oxford",
    )
    route_day = BenchmarkCase(
        name="route_day",
        request=_request(
            catalog_revision,
            bounds=route_bounds,
            kinds=_ROUTE_KINDS,
            route_geometry=_ROUTE_GEOMETRY,
            day_geometry=_DAY_GEOMETRY,
            day=2,
            policy={"basis": "route", "radius_m": MAX_CATALOG_RADIUS_M},
        ),
        candidate_count=_bounded_candidate_count(index, route_bounds),
        viewport_name="milton_keynes",
    )
    waterway = BenchmarkCase(
        name="waterway",
        request=_request(
            catalog_revision,
            bounds=route_bounds,
            kinds=_WATERWAY_KINDS,
            policy={"basis": "waterway", "radius_m": MAX_CATALOG_RADIUS_M},
        ),
        candidate_count=_bounded_candidate_count(index, route_bounds),
        viewport_name="milton_keynes",
    )

    eligible_viewports = [
        (name, bounds, count)
        for name, bounds in _PREDEFINED_VIEWPORTS
        for count in (index.viewport_candidate_count(bounds),)
        if count <= MAX_QUERY_WORK
    ]
    if not eligible_viewports:
        raise ValueError(
            "no predefined benchmark viewport is within the "
            f"{MAX_QUERY_WORK:,}-candidate work budget"
        )
    dense_name, dense_bounds, dense_count = max(
        eligible_viewports,
        key=lambda item: (item[2], item[0]),
    )
    dense = BenchmarkCase(
        name="densest_predefined_viewport",
        request=_request(
            catalog_revision,
            bounds=dense_bounds,
            kinds=_DENSE_KINDS,
            policy={"basis": "none", "radius_m": None},
        ),
        candidate_count=dense_count,
        viewport_name=dense_name,
    )
    return tuple(sorted((dense, locality, route_day, waterway), key=lambda case: case.name))


def _percentile(values: list[float], percentile: int) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[percentile - 1]


def result_payload(
    *,
    candidate_count: int,
    matching_count: int,
    over_cap: bool,
    latencies_ms: list[float],
    rss_kib: int | None,
) -> dict[str, Any]:
    """Return one sorted-key-compatible result payload for JSON output."""

    return {
        "candidate_count": candidate_count,
        "matching_count": matching_count,
        "max_ms": max(latencies_ms),
        "over_cap": over_cap,
        "p50_ms": statistics.median(latencies_ms),
        "p95_ms": _percentile(latencies_ms, 95),
        "rss_kib": rss_kib,
    }


def _rss_kib() -> int | None:
    """Return current resident memory on Linux, with a portable fallback."""

    try:
        with Path("/proc/self/status").open(encoding="utf-8") as status:
            for line in status:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass

    if resource is None:
        return None
    try:
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (AttributeError, OSError):
        return None
    if sys.platform == "darwin":
        value /= 1024
    return int(value)


def _result_signature(result) -> tuple[int, bool, tuple[tuple[Any, ...], ...]]:
    return (
        result.matching_count,
        result.over_cap,
        tuple(place.identity for place in result.places),
    )


def _measure_case(
    index: CatalogSpatialIndex, case: BenchmarkCase, *, warmups: int, iterations: int
):
    expected = None
    result = None
    for _ in range(warmups):
        result = index.query(case.request)
        signature = _result_signature(result)
        if expected is None:
            expected = signature
        elif signature != expected:
            raise RuntimeError(f"benchmark case {case.name!r} returned non-deterministic results")

    latencies_ms = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        result = index.query(case.request)
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        signature = _result_signature(result)
        if expected is None:
            expected = signature
        elif signature != expected:
            raise RuntimeError(f"benchmark case {case.name!r} returned non-deterministic results")
        latencies_ms.append(elapsed_ms)

    if result is None:
        raise RuntimeError(f"benchmark case {case.name!r} did not run")
    return result_payload(
        candidate_count=case.candidate_count,
        matching_count=result.matching_count,
        over_cap=result.over_cap,
        latencies_ms=latencies_ms,
        rss_kib=_rss_kib(),
    )


def run_benchmark(
    catalog_path: Path,
    routing_artifact_path: Path,
    *,
    warmups: int = DEFAULT_WARMUPS,
    iterations: int = DEFAULT_ITERATIONS,
) -> dict[str, Any]:
    """Load both artifacts, build indexes, and measure public catalog queries."""

    if warmups < 0:
        raise ValueError("warmups must be nonnegative")
    if iterations < 2:
        raise ValueError("iterations must be at least 2")

    routing_artifact = load_artifact(routing_artifact_path)
    catalog_artifact = load_catalog(catalog_path)
    waterway_index = GraphSpatialIndex(routing_artifact.graph)
    catalog_index = CatalogSpatialIndex(catalog_artifact.places, waterway_index)
    cases = build_benchmark_cases(catalog_artifact.metadata["catalog_revision"], catalog_index)
    results = [
        {
            "name": case.name,
            "viewport": case.viewport_name,
            **_measure_case(catalog_index, case, warmups=warmups, iterations=iterations),
        }
        for case in cases
    ]
    return {
        "artifact_revision": routing_artifact.metadata["artifact_revision"],
        "catalog_records": len(catalog_artifact.places),
        "catalog_revision": catalog_artifact.metadata["catalog_revision"],
        "cases": results,
        "iterations": iterations,
        "query_work_budget": MAX_QUERY_WORK,
        "routing_edges": routing_artifact.graph.number_of_edges(),
        "routing_nodes": routing_artifact.graph.number_of_nodes(),
        "warmups": warmups,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark bounded nationwide catalog queries through CatalogSpatialIndex."
    )
    parser.add_argument(
        "--catalog-artifact",
        "--catalog",
        dest="catalog_path",
        type=Path,
        required=True,
        help="independent catalog artifact to load",
    )
    parser.add_argument(
        "--routing-artifact",
        "--artifact",
        dest="routing_artifact_path",
        type=Path,
        required=True,
        help="routing graph artifact supplying the waterway index",
    )
    parser.add_argument("--warmups", type=int, default=DEFAULT_WARMUPS)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        payload = run_benchmark(
            args.catalog_path,
            args.routing_artifact_path,
            warmups=args.warmups,
            iterations=args.iterations,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
