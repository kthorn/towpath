"""Inventory a trusted place catalog and benchmark bounded national name scans."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

try:
    import resource
except ImportError:  # pragma: no cover - resource is unavailable on some platforms
    resource = None

from pound.catalog.artifact import load_catalog

DEFAULT_WARMUPS = 2
DEFAULT_ITERATIONS = 7
MISS_QUERY = "place-resolution-inventory-no-such-name-9f4b"


def _normalize(value: str) -> str:
    return " ".join(value.split()).casefold()


def _place_names(place: Any) -> tuple[str, ...]:
    values = (place.name, place.metadata.alt_name)
    return tuple(dict.fromkeys(_normalize(value) for value in values if value))


def _identity(place: Any) -> list[Any]:
    return [place.osm_type.value, place.osm_id, place.kind]


def _scan(places: tuple[Any, ...], query: str, *, exact: bool) -> tuple[Any, ...]:
    normalized_query = _normalize(query)
    matches = []
    for place in places:
        names = _place_names(place)
        if any(
            name == normalized_query if exact else normalized_query in name
            for name in names
        ):
            matches.append(place)
    return tuple(matches)


def _rss_kib() -> int | None:
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


def _percentile(values: list[float], percentile: int) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[percentile - 1]


def _measure_scan(
    places: tuple[Any, ...], query: str, *, exact: bool, warmups: int, iterations: int
) -> dict[str, Any]:
    expected = tuple(_identity(place) for place in _scan(places, query, exact=exact))
    for _ in range(warmups):
        observed = tuple(_identity(place) for place in _scan(places, query, exact=exact))
        if observed != expected:
            raise RuntimeError(f"non-deterministic national lookup for {query!r}")

    latencies_ms: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        observed = tuple(_identity(place) for place in _scan(places, query, exact=exact))
        latencies_ms.append((time.perf_counter_ns() - started) / 1_000_000)
        if observed != expected:
            raise RuntimeError(f"non-deterministic national lookup for {query!r}")

    return {
        "query": query,
        "match_count": len(expected),
        "matches": [list(identity) for identity in expected],
        "examined_records": len(places),
        "work_units": len(places),
        "iterations": iterations,
        "p50_ms": statistics.median(latencies_ms),
        "p95_ms": _percentile(latencies_ms, 95),
        "max_ms": max(latencies_ms),
        "rss_kib": _rss_kib(),
    }


def _fraction(count: int, total: int) -> float:
    return count / total if total else 0.0


def _coverage(places: tuple[Any, ...]) -> dict[str, Any]:
    named = sum(place.name is not None and bool(place.name.strip()) for place in places)
    aliases = sum(
        place.metadata.alt_name is not None and bool(place.metadata.alt_name.strip())
        for place in places
    )
    alias_values = sum(
        1
        for place in places
        if place.metadata.alt_name is not None and bool(place.metadata.alt_name.strip())
    )
    locality_components = {"place": 0, "city": 0}
    records_with_locality = 0
    for place in places:
        address = place.metadata.address
        if address is None:
            continue
        present = [component for component in locality_components if getattr(address, component)]
        for component in present:
            locality_components[component] += 1
        records_with_locality += bool(present)
    return {
        "name_completeness": {
            "named": named,
            "unnamed": len(places) - named,
            "fraction": _fraction(named, len(places)),
        },
        "alias_completeness": {
            "records_with_alias": aliases,
            "alias_values": alias_values,
        },
        "locality_completeness": {
            "records_with_locality": records_with_locality,
            "fraction": _fraction(records_with_locality, len(places)),
            **locality_components,
        },
    }


def inventory_catalog(
    catalog_path: Path, *, warmups: int = DEFAULT_WARMUPS, iterations: int = DEFAULT_ITERATIONS
) -> dict[str, Any]:
    """Return provenance, coverage, and national name-scan measurements."""
    if warmups < 0:
        raise ValueError("warmups must be nonnegative")
    if iterations < 2:
        raise ValueError("iterations must be at least 2")

    path = Path(catalog_path).resolve()
    started = time.perf_counter_ns()
    artifact = load_catalog(path)
    load_ms = (time.perf_counter_ns() - started) / 1_000_000
    places = tuple(artifact.places)

    lats = [place.lat for place in places]
    lons = [place.lon for place in places]
    extent = (
        {
            "lat_min": min(lats),
            "lat_max": max(lats),
            "lon_min": min(lons),
            "lon_max": max(lons),
        }
        if places
        else None
    )
    coverage = _coverage(places)
    kinds = sorted({place.kind for place in places})
    kind_counts = {kind: sum(place.kind == kind for place in places) for kind in kinds}
    queries = {
        "exact": ("Bletchley Park", True),
        "partial": ("bletchley", False),
        "miss": (MISS_QUERY, False),
    }
    baseline = {
        label: _measure_scan(
            places,
            query,
            exact=exact,
            warmups=warmups,
            iterations=iterations,
        )
        for label, (query, exact) in queries.items()
    }
    return {
        "catalog": {
            "path": str(path),
            "bytes": path.stat().st_size,
            "metadata": artifact.metadata,
            "load_ms": load_ms,
            "rss_kib": _rss_kib(),
        },
        "record_count": len(places),
        "extent": extent,
        "supported_kinds": dict(sorted(kind_counts.items())),
        **coverage,
        "bletchley_matches": {
            label: {
                key: value
                for key, value in result.items()
                if key in {"query", "match_count", "matches"}
            }
            for label, result in baseline.items()
        },
        "national_lookup_baseline": baseline,
        "measurement": {"warmups": warmups, "iterations": iterations},
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True, help="trusted catalog artifact")
    parser.add_argument("--warmups", type=int, default=DEFAULT_WARMUPS)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        payload = inventory_catalog(args.catalog, warmups=args.warmups, iterations=args.iterations)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
