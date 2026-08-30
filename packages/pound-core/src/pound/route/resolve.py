"""Resolve named and raw geographic positions to projected canal handles."""

import networkx as nx

from pound.artifact import RuntimeArtifact
from pound.graph.spatial import CandidateSpatialIndex
from pound.schemas import CanalPointHandle

_DEFAULT_SNAP_TOLERANCE_M = 50.0


def _gazetteer_key(name: str, gazetteer: dict) -> str | None:
    folded = name.casefold()
    return next(
        (key for key in gazetteer if isinstance(key, str) and key.casefold() == folded),
        None,
    )


def resolve_place(
    name: str,
    artifact: RuntimeArtifact,
    spatial_index: CandidateSpatialIndex,
    tolerance_m: float = _DEFAULT_SNAP_TOLERANCE_M,
) -> CanalPointHandle:
    """Resolve a gazetteer place name to a projected canal handle."""
    gazetteer = artifact.gazetteer
    key = _gazetteer_key(name, gazetteer)
    if key is None:
        raise ValueError(
            f"{name!r} not found in gazetteer; this build covers {len(gazetteer)} places; "
            f"try a different name or wait for geocoding support"
        )
    entry = gazetteer[key]
    if isinstance(entry, list):
        raise ValueError(
            f"{name!r} matches {len(entry)} places; specify a nearby town or a more specific name"
        )
    projected = spatial_index.nearest_projection(*entry)
    if projected is None:
        raise ValueError(
            f"{name!r} cannot be projected because the artifact has no navigable edges"
        )
    point, distance_m = projected
    if distance_m > tolerance_m:
        raise ValueError(
            f"{name!r} at {entry} is not within {tolerance_m} m "
            f"of any navigable canal point (nearest {distance_m:.1f} m)"
        )
    return point.handle


def resolve_coord(
    lat: float,
    lon: float,
    graph: nx.Graph,
    candidate_index: CandidateSpatialIndex,
) -> tuple[CanalPointHandle, float]:
    """Resolve a coordinate to its nearest projected canal handle and distance."""
    del graph
    projected = candidate_index.nearest_projection(lat, lon)
    if projected is None:
        raise ValueError("no navigable edges to resolve against")
    point, distance_m = projected
    return point.handle, distance_m
