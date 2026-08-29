"""Measure bounded nationwide places queries through the public runtime path."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

try:
    import resource
except ImportError:  # pragma: no cover - resource is unavailable on some platforms
    resource = None

from pound.catalog.artifact import load_catalog
from pound.catalog.manifest import MAX_CATALOG_RADIUS_M
from pound.catalog.spatial import CatalogSpatialIndex
from pound.graph.artifact import load_artifact
from pound.graph.spatial import GraphSpatialIndex
from pound.schemas import (
    GeoJSONLineString,
    MapBounds,
    NearbyPlacesRequest,
    ViewportPlacesRequest,
)
from pound.web.boat_hire import load_boat_hire_seeds
from pound.web.places import (
    MAX_PLACES_QUERY_WORK,
    PlacesIndex,
    PlacesQueryStats,
    PlacesResultLimitError,
)

MAX_QUERY_WORK = MAX_PLACES_QUERY_WORK
DEFAULT_WARMUPS = 2
DEFAULT_ITERATIONS = 7
Outcome = Literal["ok", "result_limit_exceeded"]

# These fixed viewports keep comparisons stable across artifacts and hosts. The
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
_NEARBY_KINDS = ["pub", "cafe", "restaurant", "museum", "marina"]
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
_NEARBY_POINT = {"type": "Point", "coordinates": [-0.75, 52.08]}
_NEARBY_LINE = {
    "type": "LineString",
    "coordinates": [[-0.85, 52.03], [-0.75, 52.08], [-0.65, 52.15]],
}
_NEARBY_RADIUS_M = 1_000.0


@dataclass(frozen=True)
class BenchmarkCase:
    """One deterministic request and its optional viewport preflight count."""

    name: str
    request: ViewportPlacesRequest | NearbyPlacesRequest
    candidate_count: int | None
    viewport_name: str | None


@dataclass(frozen=True)
class _QueryMeasurement:
    outcome: Outcome
    result_count: int | None
    signature: tuple[Any, ...]
    candidate_work: int
    latency_ms: float


def _request(
    *,
    bounds: MapBounds,
    kinds: list[str],
    policy: dict[str, Any],
    route_geometry: GeoJSONLineString | None = None,
    day_geometry: GeoJSONLineString | None = None,
) -> ViewportPlacesRequest:
    return ViewportPlacesRequest.model_validate(
        {
            "mode": "viewport",
            "kinds": kinds,
            "bounds": bounds,
            "route_geometry": route_geometry,
            "day_geometry": day_geometry,
            "policy": policy,
        }
    )


def _nearby_request(targets: list[dict[str, Any]]) -> NearbyPlacesRequest:
    return NearbyPlacesRequest.model_validate(
        {
            "mode": "nearby",
            "kinds": _NEARBY_KINDS,
            "radius_m": _NEARBY_RADIUS_M,
            "targets": targets,
        }
    )


def _bounded_candidate_count(catalog_index, bounds: MapBounds) -> int:
    count = catalog_index.viewport_candidate_count(bounds)
    if count > MAX_QUERY_WORK:
        raise ValueError(
            f"benchmark viewport has {count:,} candidates, exceeding "
            f"the {MAX_QUERY_WORK:,}-candidate work budget"
        )
    return count


def build_benchmark_cases(places_index: PlacesIndex) -> tuple[BenchmarkCase, ...]:
    """Build fixed viewport and nearby cases for the public places query path."""

    catalog_index = places_index.catalog_index
    viewports = dict(_PREDEFINED_VIEWPORTS)
    locality_bounds = viewports["oxford"]
    route_bounds = viewports["milton_keynes"]
    locality = BenchmarkCase(
        name="locality_no_policy",
        request=_request(
            bounds=locality_bounds,
            kinds=_LOCALITY_KINDS,
            policy={"basis": "none", "radius_m": None},
        ),
        candidate_count=_bounded_candidate_count(catalog_index, locality_bounds),
        viewport_name="oxford",
    )
    route_day = BenchmarkCase(
        name="route_day",
        request=_request(
            bounds=route_bounds,
            kinds=_ROUTE_KINDS,
            route_geometry=_ROUTE_GEOMETRY,
            day_geometry=_DAY_GEOMETRY,
            policy={"basis": "route", "radius_m": MAX_CATALOG_RADIUS_M},
        ),
        candidate_count=_bounded_candidate_count(catalog_index, route_bounds),
        viewport_name="milton_keynes",
    )
    waterway = BenchmarkCase(
        name="waterway",
        request=_request(
            bounds=route_bounds,
            kinds=_WATERWAY_KINDS,
            policy={"basis": "waterway", "radius_m": MAX_CATALOG_RADIUS_M},
        ),
        candidate_count=_bounded_candidate_count(catalog_index, route_bounds),
        viewport_name="milton_keynes",
    )

    nearby_point = BenchmarkCase(
        name="nearby-point",
        request=_nearby_request(
            [{"id": "point", "geometry": _NEARBY_POINT}],
        ),
        candidate_count=None,
        viewport_name=None,
    )
    nearby_line = BenchmarkCase(
        name="nearby-line",
        request=_nearby_request(
            [{"id": "line", "geometry": _NEARBY_LINE}],
        ),
        candidate_count=None,
        viewport_name=None,
    )
    nearby_multi_target = BenchmarkCase(
        name="nearby-multi-target",
        request=_nearby_request(
            [
                {"id": "point", "geometry": _NEARBY_POINT},
                {"id": "line", "geometry": _NEARBY_LINE},
            ],
        ),
        candidate_count=None,
        viewport_name=None,
    )

    eligible_viewports = [
        (name, bounds, count)
        for name, bounds in _PREDEFINED_VIEWPORTS
        for count in (catalog_index.viewport_candidate_count(bounds),)
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
            bounds=dense_bounds,
            kinds=_DENSE_KINDS,
            policy={"basis": "none", "radius_m": None},
        ),
        candidate_count=dense_count,
        viewport_name=dense_name,
    )
    return tuple(
        sorted(
            (
                dense,
                locality,
                nearby_line,
                nearby_multi_target,
                nearby_point,
                route_day,
                waterway,
            ),
            key=lambda case: case.name,
        )
    )


def _percentile(values: list[float], percentile: int) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[percentile - 1]


def result_payload(
    *,
    candidate_work: int,
    outcome: Outcome,
    result_count: int | None = None,
    latencies_ms: list[float],
    rss_kib: int | None,
) -> dict[str, Any]:
    """Return one sorted-key-compatible result payload for JSON output."""

    payload: dict[str, Any] = {
        "candidate_work": candidate_work,
        "max_ms": max(latencies_ms),
        "outcome": outcome,
        "p50_ms": statistics.median(latencies_ms),
        "p95_ms": _percentile(latencies_ms, 95),
        "rss_kib": rss_kib,
    }
    if outcome == "ok":
        if result_count is None:
            raise ValueError("successful benchmark results require result_count")
        payload["result_count"] = result_count
    return payload


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


def _place_signature(place) -> tuple[Any, ...]:
    provenance = place.provenance
    if provenance.source == "osm":
        return ("osm", provenance.osm_type, provenance.osm_id)
    return ("boat_hire", provenance.provider_id, provenance.location_id)


def _run_query(index: PlacesIndex, request) -> _QueryMeasurement:
    stats = PlacesQueryStats()
    started = time.perf_counter_ns()
    try:
        response = index.query(request, stats=stats)
    except PlacesResultLimitError as exc:
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        return _QueryMeasurement(
            outcome="result_limit_exceeded",
            result_count=None,
            signature=("result_limit_exceeded", exc.target_id),
            candidate_work=stats.work_used,
            latency_ms=elapsed_ms,
        )
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    return _QueryMeasurement(
        outcome="ok",
        result_count=len(response.places),
        signature=("ok", tuple(_place_signature(place) for place in response.places)),
        candidate_work=stats.work_used,
        latency_ms=elapsed_ms,
    )


def _measure_case(
    index: PlacesIndex, case: BenchmarkCase, *, warmups: int, iterations: int
) -> dict[str, Any]:
    expected_signature = None
    for _ in range(warmups):
        measurement = _run_query(index, case.request)
        if expected_signature is None:
            expected_signature = measurement.signature
        elif measurement.signature != expected_signature:
            raise RuntimeError(f"benchmark case {case.name!r} returned non-deterministic results")

    measurements = []
    expected_work = None
    for _ in range(iterations):
        measurement = _run_query(index, case.request)
        if expected_signature is None:
            expected_signature = measurement.signature
        elif measurement.signature != expected_signature:
            raise RuntimeError(f"benchmark case {case.name!r} returned non-deterministic results")
        if expected_work is None:
            expected_work = measurement.candidate_work
        elif measurement.candidate_work != expected_work:
            raise RuntimeError(
                f"benchmark case {case.name!r} used non-deterministic candidate work"
            )
        measurements.append(measurement)

    if not measurements or expected_work is None:
        raise RuntimeError(f"benchmark case {case.name!r} did not run")
    first = measurements[0]
    return result_payload(
        candidate_work=expected_work,
        outcome=first.outcome,
        result_count=first.result_count,
        latencies_ms=[measurement.latency_ms for measurement in measurements],
        rss_kib=_rss_kib(),
    )


def run_benchmark(
    catalog_path: Path,
    routing_artifact_path: Path,
    boat_hire_enrichment_path: Path,
    *,
    warmups: int = DEFAULT_WARMUPS,
    iterations: int = DEFAULT_ITERATIONS,
) -> dict[str, Any]:
    """Load runtime sources, then measure public ``PlacesIndex.query`` calls."""

    if warmups < 0:
        raise ValueError("warmups must be nonnegative")
    if iterations < 2:
        raise ValueError("iterations must be at least 2")

    startup_started = time.perf_counter_ns()
    routing_artifact = load_artifact(routing_artifact_path)
    catalog_artifact = load_catalog(catalog_path)
    waterway_index = GraphSpatialIndex(routing_artifact.graph)
    catalog_index = CatalogSpatialIndex(catalog_artifact.places, waterway_index)
    boat_hire_seeds = load_boat_hire_seeds(boat_hire_enrichment_path)
    places_index = PlacesIndex(catalog_index, waterway_index, boat_hire_seeds)
    startup_ms = (time.perf_counter_ns() - startup_started) / 1_000_000

    cases = build_benchmark_cases(places_index)
    results = [
        {
            "name": case.name,
            **({"viewport": case.viewport_name} if case.viewport_name is not None else {}),
            **_measure_case(places_index, case, warmups=warmups, iterations=iterations),
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
        "startup_ms": startup_ms,
        "warmups": warmups,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark bounded nationwide queries through PlacesIndex.query."
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
    parser.add_argument(
        "--boat-hire-enrichment",
        type=Path,
        required=True,
        help="validated curated boat-hire enrichment CSV to load",
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
            args.boat_hire_enrichment,
            warmups=args.warmups,
            iterations=args.iterations,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
