"""Projected canal candidate discovery over an immutable candidate index."""

import math
from collections.abc import Sequence

import networkx as nx

from pound.geometry import haversine_m as _haversine_m
from pound.graph.spatial import CandidateSpatialIndex, GraphSpatialIndex
from pound.schemas import CanalCandidate, ProjectedCanalPoint

_DEFAULT_SPACING_M = 250.0


def candidate_id(point: ProjectedCanalPoint) -> str:
    """Return the deterministic presentation ID for a projected point."""
    u, v = point.handle.edge
    return f"{u}:{v}:{point.handle.fraction:.12f}"


def _validate_query(lat: float, lon: float) -> None:
    if (
        isinstance(lat, bool)
        or isinstance(lon, bool)
        or not isinstance(lat, (int, float))
        or not isinstance(lon, (int, float))
        or not math.isfinite(lat)
        or not math.isfinite(lon)
        or not -90 <= lat <= 90
        or not -180 <= lon <= 180
    ):
        raise ValueError("lat and lon must be finite coordinates in geographic bounds")


def _spaced(
    candidates: Sequence[CanalCandidate], *, limit: int, spacing_m: float
) -> list[CanalCandidate]:
    retained: list[CanalCandidate] = []
    for candidate in candidates:
        point = (candidate.coordinate.lat, candidate.coordinate.lon)
        if all(
            _haversine_m(point, (other.coordinate.lat, other.coordinate.lon)) >= spacing_m
            for other in retained
        ):
            retained.append(candidate)
            if len(retained) == limit:
                break
    return retained


def nearest_candidates(
    lat: float, lon: float, index: CandidateSpatialIndex, *, limit: int
) -> list[CanalCandidate]:
    """Return nearest exact and fixed projected candidates with cross-branch spacing."""
    if limit <= 0:
        raise ValueError("limit must be greater than zero")
    _validate_query(lat, lon)

    pool: dict[str, tuple[float, ProjectedCanalPoint]] = {}
    exact = index.nearest_projection(lat, lon)
    if exact is not None:
        point, _metric_distance = exact
        pool[candidate_id(point)] = (
            _haversine_m((lat, lon), (point.coordinate.lat, point.coordinate.lon)),
            point,
        )
    for point, _metric_distance in index.nearest_samples(lat, lon):
        identity = candidate_id(point)
        pool.setdefault(
            identity,
            (
                _haversine_m((lat, lon), (point.coordinate.lat, point.coordinate.lon)),
                point,
            ),
        )

    ranked = sorted(pool.values(), key=lambda item: (item[0], candidate_id(item[1])))
    records = [
        CanalCandidate(
            candidate_id=candidate_id(point),
            handle=point.handle,
            coordinate=point.coordinate,
            straight_line_distance_m=distance,
            display_name=index.display_name(point.handle, point.coordinate),
        )
        for distance, point in ranked
    ]
    return _spaced(records, limit=limit, spacing_m=index.spacing_m)


def select_spaced_candidates(
    candidates: Sequence[CanalCandidate],
    *,
    destination_limit: int,
    minimum_spacing_m: float,
) -> list[CanalCandidate]:
    """Retain nearest candidates separated by a caller-supplied distance.

    Kept as a small compatibility helper for the pre-projection web caller; new
    code should use :func:`nearest_candidates`, whose spacing is index-owned.
    """
    if destination_limit <= 0:
        raise ValueError("destination_limit must be greater than zero")
    if minimum_spacing_m < 0:
        raise ValueError("minimum_spacing_m must be nonnegative")
    return _spaced(candidates, limit=destination_limit, spacing_m=minimum_spacing_m)


def nearest_coord_candidates(
    lat: float,
    lon: float,
    graph: nx.Graph,
    spatial_index: GraphSpatialIndex,
    *,
    artifact_revision: str,
    limit: int,
) -> list[CanalCandidate]:
    """Compatibility bridge for the pre-projection web endpoint.

    ``artifact_revision`` is intentionally not copied into each candidate; the
    response-level field remains owned by that endpoint until its migration.
    """
    del spatial_index, artifact_revision
    return nearest_candidates(lat, lon, CandidateSpatialIndex(graph), limit=limit)
