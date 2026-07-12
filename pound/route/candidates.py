"""Pure helpers for finding and spacing canal access candidates."""

from collections.abc import Sequence

import networkx as nx

from pound.graph.build import _haversine_m
from pound.schemas import CanalCandidate, Coordinate

_UNNAMED_POINT = "Unnamed canal point"


def _display_name(graph: nx.Graph, uid: int) -> str:
    node_name = graph.nodes[uid].get("name")
    if isinstance(node_name, str) and node_name.strip():
        return node_name.strip()

    edge_names = {
        name.strip()
        for _, _, data in graph.edges(uid, data=True)
        if isinstance((name := data.get("name")), str) and name.strip()
    }
    return min(edge_names) if edge_names else _UNNAMED_POINT


def nearest_coord_candidates(
    lat: float,
    lon: float,
    graph: nx.Graph,
    *,
    artifact_revision: str,
    limit: int,
) -> list[CanalCandidate]:
    """Return graph nodes nearest to a coordinate without mutating the graph."""
    if limit <= 0:
        raise ValueError("limit must be greater than zero")

    ranked = sorted(
        (
            (_haversine_m((lat, lon), (data["lat"], data["lon"])), uid, data)
            for uid, data in graph.nodes(data=True)
        ),
        key=lambda item: (item[0], item[1]),
    )
    return [
        CanalCandidate(
            uid=int(uid),
            artifact_revision=artifact_revision,
            coordinate=Coordinate(lat=data["lat"], lon=data["lon"]),
            straight_line_distance_m=distance,
            display_name=_display_name(graph, uid),
        )
        for distance, uid, data in ranked[:limit]
    ]


def select_spaced_candidates(
    candidates: Sequence[CanalCandidate],
    *,
    destination_limit: int,
    minimum_spacing_m: float,
) -> list[CanalCandidate]:
    """Greedily retain nearest candidates separated by the requested distance."""
    if destination_limit <= 0:
        raise ValueError("destination_limit must be greater than zero")
    if minimum_spacing_m < 0:
        raise ValueError("minimum_spacing_m must be nonnegative")

    retained: list[CanalCandidate] = []
    for candidate in candidates:
        point = (candidate.coordinate.lat, candidate.coordinate.lon)
        if all(
            _haversine_m(
                point,
                (other.coordinate.lat, other.coordinate.lon),
            )
            >= minimum_spacing_m
            for other in retained
        ):
            retained.append(candidate)
            if len(retained) == destination_limit:
                break
    return retained
