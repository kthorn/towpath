"""Validate and serialize locally produced routing graph artifacts.

Artifacts use pickle and therefore must only be loaded from trusted, local Pound builds. Pickle is
not a safe interchange format and this module does not make untrusted pickle data safe to load.
"""

import math
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import networkx as nx
from pydantic import ValidationError
from shapely.geometry import Point

from pound.graph.pois import _edge_line_wgs84, _routing_eligible, _to_bng
from pound.ingest.ir import PointOfInterest

_PAYLOAD_FIELDS = {"graph", "pois", "metadata"}
_METADATA_FIELDS = {
    "artifact_revision",
    "source",
    "fetched_at",
    "built_at",
    "validation",
    "poi_summary",
}
_NODE_FIELDS = {"lat", "lon", "osm_node_ids", "movable_bridge_ids"}
_EDGE_FIELDS = {
    "osm_way_id",
    "name",
    "kind",
    "length_m",
    "dimensions",
    "has_tunnel",
    "has_movable_bridge",
    "locks",
    "geometry",
    "movable_bridge_ids",
    "tunnel_restrictions",
}
_CORRIDOR_M = {
    "canal_service": 250.0,
    "pedestrian_access": 250.0,
    "provisions": 1000.0,
    "transport": 1000.0,
}


class InvalidArtifactError(ValueError):
    """An artifact does not satisfy the current strict build contract."""


def _invalid(field: str, value: Any, problem: str) -> InvalidArtifactError:
    return InvalidArtifactError(
        f"Invalid artifact {field}={value!r}: {problem}. "
        "Rebuild the artifact with this Pound version."
    )


def _finite_coordinate(field: str, value: Any, lower: float, upper: float) -> None:
    if (
        not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not lower <= value <= upper
    ):
        raise _invalid(field, value, f"expected a finite value from {lower} through {upper}")


def _validate_sorted_bridge_ids(field: str, value: Any) -> None:
    if not isinstance(value, tuple) or any(not isinstance(item, str) or not item for item in value):
        raise _invalid(field, value, "expected sorted unique non-empty bridge IDs")
    if value != tuple(sorted(set(value))):
        raise _invalid(field, value, "expected sorted unique bridge IDs")


def _validate_tunnel_restrictions(field: str, value: Any) -> None:
    if not isinstance(value, tuple):
        raise _invalid(field, value, "expected sorted unique tunnel restriction tuples")
    for item in value:
        if (
            not isinstance(item, tuple)
            or len(item) != 3
            or isinstance(item[0], bool)
            or not isinstance(item[0], int)
            or not isinstance(item[1], str)
            or not item[1]
            or not isinstance(item[2], str)
        ):
            raise _invalid(
                field,
                value,
                "expected (integer OSM way ID, non-empty key, string value) tuples",
            )
    if value != tuple(sorted(set(value))):
        raise _invalid(field, value, "expected sorted unique tunnel restriction tuples")


def _validate_graph(graph: Any) -> nx.Graph:
    if not isinstance(graph, nx.Graph) or graph.is_directed() or graph.is_multigraph():
        raise _invalid("graph", type(graph).__name__, "expected an undirected networkx.Graph")
    for uid, data in graph.nodes(data=True):
        missing = _NODE_FIELDS - data.keys()
        if missing:
            attribute = sorted(missing)[0]
            raise _invalid(
                f"graph node {uid} attribute {attribute}", None, "required attribute missing"
            )
        _finite_coordinate(f"graph node {uid} lat", data["lat"], -90, 90)
        _finite_coordinate(f"graph node {uid} lon", data["lon"], -180, 180)
        _validate_sorted_bridge_ids(
            f"graph node {uid} attribute movable_bridge_ids", data["movable_bridge_ids"]
        )
    for u, v, data in graph.edges(data=True):
        missing = _EDGE_FIELDS - data.keys()
        if missing:
            attribute = sorted(missing)[0]
            raise _invalid(
                f"graph edge {(u, v)} attribute {attribute}", None, "required attribute missing"
            )
        _validate_sorted_bridge_ids(
            f"graph edge {(u, v)} attribute movable_bridge_ids", data["movable_bridge_ids"]
        )
        _validate_tunnel_restrictions(
            f"graph edge {(u, v)} attribute tunnel_restrictions", data["tunnel_restrictions"]
        )
        geometry = data["geometry"]
        if not isinstance(geometry, (list, tuple)) or len(geometry) < 2:
            raise _invalid(
                f"graph edge {(u, v)} attribute geometry",
                geometry,
                "expected at least two (lat, lon) coordinate pairs",
            )
        for index, coordinate in enumerate(geometry):
            if not isinstance(coordinate, (list, tuple)) or len(coordinate) != 2:
                raise _invalid(
                    f"graph edge {(u, v)} geometry[{index}]",
                    coordinate,
                    "expected a (lat, lon) coordinate pair",
                )
            _finite_coordinate(f"graph edge {(u, v)} geometry[{index}].lat", coordinate[0], -90, 90)
            _finite_coordinate(
                f"graph edge {(u, v)} geometry[{index}].lon", coordinate[1], -180, 180
            )
        if "lock_points" in data:
            lock_points = data["lock_points"]
            if not isinstance(lock_points, (list, tuple)):
                raise _invalid(
                    f"graph edge {(u, v)} attribute lock_points",
                    lock_points,
                    "expected a list or tuple of coordinate pairs",
                )
            for index, coordinate in enumerate(lock_points):
                if not isinstance(coordinate, (list, tuple)) or len(coordinate) != 2:
                    raise _invalid(
                        f"graph edge {(u, v)} lock_points[{index}]",
                        coordinate,
                        "expected a (lat, lon) coordinate pair",
                    )
                _finite_coordinate(
                    f"graph edge {(u, v)} lock_points[{index}].lat", coordinate[0], -90, 90
                )
                _finite_coordinate(
                    f"graph edge {(u, v)} lock_points[{index}].lon", coordinate[1], -180, 180
                )
    return graph


def _parse_pois(
    raw_pois: Any, *, trust_validated_instances: bool = False
) -> tuple[PointOfInterest, ...]:
    if not isinstance(raw_pois, (list, tuple)):
        raise _invalid("pois", raw_pois, "expected a list or tuple")
    parsed = []
    expected_fields = set(PointOfInterest.model_fields)
    for index, raw_poi in enumerate(raw_pois):
        if trust_validated_instances and type(raw_poi) is PointOfInterest:
            poi = raw_poi
        else:
            values = raw_poi.model_dump() if isinstance(raw_poi, PointOfInterest) else raw_poi
            if not isinstance(values, dict):
                raise _invalid(f"pois[{index}]", values, "expected a PointOfInterest mapping")
            unexpected = values.keys() - expected_fields
            if unexpected:
                raise _invalid(
                    f"pois[{index}] unexpected fields",
                    sorted(unexpected),
                    "fields are not permitted",
                )
            try:
                poi = PointOfInterest.model_validate(values)
            except ValidationError as exc:
                errors = exc.errors(include_url=False)
                location = ".".join(str(part) for part in errors[0]["loc"])
                value = values.get(location)
                raise _invalid(f"pois[{index}].{location}", value, errors[0]["msg"]) from exc
        for field, lower, upper in (
            ("lat", -90, 90),
            ("lon", -180, 180),
            ("projected_lat", -90, 90),
            ("projected_lon", -180, 180),
        ):
            _finite_coordinate(f"pois[{index}].{field}", getattr(poi, field), lower, upper)
        distance = poi.nearest_waterway_distance_m
        if not math.isfinite(distance):
            raise _invalid(
                f"pois[{index}].nearest_waterway_distance_m", distance, "expected a finite distance"
            )
        limit = _CORRIDOR_M[poi.category.value]
        if distance > limit:
            raise _invalid(
                f"pois[{index}].nearest_waterway_distance_m",
                distance,
                f"distance exceeds the {limit} m {poi.category.value} corridor",
            )
        parsed.append(poi)
    return tuple(parsed)


def _validate_attachments(graph: nx.Graph, pois: tuple[PointOfInterest, ...]) -> None:
    identities = set()
    for index, poi in enumerate(pois):
        if poi.identity in identities:
            raise _invalid(f"pois[{index}].identity", poi.identity, "duplicate POI identity")
        identities.add(poi.identity)
        u, v = poi.nearest_edge
        if not graph.has_edge(u, v):
            raise _invalid(f"pois[{index}].nearest_edge", poi.nearest_edge, "edge is absent")
        if poi.nearest_node_uid not in poi.nearest_edge:
            raise _invalid(
                f"pois[{index}].nearest_node_uid",
                poi.nearest_node_uid,
                "node must be an endpoint of nearest_edge",
            )
        edge_data = graph.edges[u, v]
        if not _routing_eligible(edge_data):
            raise _invalid(f"pois[{index}].nearest_edge", poi.nearest_edge, "edge is not navigable")
        edge_bng = _to_bng(_edge_line_wgs84(graph, u, v, edge_data))
        projected_bng = _to_bng(Point(poi.projected_lon, poi.projected_lat))
        offset_m = projected_bng.distance(edge_bng)
        if not math.isfinite(offset_m) or offset_m > 0.01:
            raise _invalid(
                f"pois[{index}].projected point",
                (poi.projected_lat, poi.projected_lon),
                f"point is {offset_m:.6f} m from its attached edge; maximum is 0.01 m",
            )


def _validate_metadata(metadata: Any) -> dict:
    if not isinstance(metadata, dict):
        raise _invalid("metadata", metadata, "expected a mapping")
    fields = set(metadata)
    if fields != _METADATA_FIELDS:
        missing = sorted(_METADATA_FIELDS - fields)
        unexpected = sorted(fields - _METADATA_FIELDS)
        detail = f"metadata fields must be exact; missing={missing}, unexpected={unexpected}"
        field = missing[0] if missing else "metadata fields"
        raise _invalid(field, metadata, detail)
    for field in ("artifact_revision", "source", "fetched_at", "built_at"):
        if not isinstance(metadata[field], str) or not metadata[field]:
            raise _invalid(f"metadata.{field}", metadata[field], "expected a non-empty string")
    for field in ("validation", "poi_summary"):
        if not isinstance(metadata[field], dict):
            raise _invalid(f"metadata.{field}", metadata[field], "expected a mapping")
    return dict(metadata)


@dataclass(frozen=True)
class GraphArtifact:
    graph: nx.Graph
    pois: tuple[PointOfInterest, ...]
    metadata: dict

    def __post_init__(self) -> None:
        graph = _validate_graph(self.graph)
        pois = _parse_pois(self.pois)
        metadata = _validate_metadata(self.metadata)
        _validate_attachments(graph, pois)
        object.__setattr__(self, "pois", pois)
        object.__setattr__(self, "metadata", metadata)


def prepare_artifact(graph: nx.Graph, pois, metadata: dict) -> GraphArtifact:
    """Validate graph build values and return their strict artifact representation."""
    complete_metadata = dict(metadata)
    if "artifact_revision" not in complete_metadata:
        complete_metadata["artifact_revision"] = str(uuid4())
    return GraphArtifact(graph=graph, pois=tuple(pois), metadata=complete_metadata)


def _prepare_build_artifact(graph: nx.Graph, pois, metadata: dict) -> GraphArtifact:
    """Prepare CLI-owned, freshly built POIs without serializing them for revalidation."""
    complete_metadata = dict(metadata)
    if "artifact_revision" not in complete_metadata:
        complete_metadata["artifact_revision"] = str(uuid4())
    artifact = GraphArtifact(graph=graph, pois=(), metadata=complete_metadata)
    parsed_pois = _parse_pois(tuple(pois), trust_validated_instances=True)
    _validate_attachments(artifact.graph, parsed_pois)
    object.__setattr__(artifact, "pois", parsed_pois)
    return artifact


def write_artifact(artifact: GraphArtifact, path: Path) -> None:
    """Serialize an already prepared artifact to a trusted local pickle."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        pickle.dump(
            {"graph": artifact.graph, "pois": list(artifact.pois), "metadata": artifact.metadata},
            stream,
        )


def save_artifact(graph: nx.Graph, pois, path: Path, metadata: dict) -> None:
    """Validate and save exactly one graph, POI collection, and metadata mapping."""
    write_artifact(prepare_artifact(graph, pois, metadata), path)


def load_artifact(path: Path) -> GraphArtifact:
    """Load a trusted local pickle and validate its exact artifact contract."""
    try:
        with Path(path).open("rb") as stream:
            payload = pickle.load(stream)
    except Exception as exc:
        raise _invalid("pickle", str(path), f"could not load trusted local pickle: {exc}") from exc
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_FIELDS:
        keys = sorted(payload) if isinstance(payload, dict) else type(payload).__name__
        raise _invalid("top-level keys", keys, f"expected exactly {sorted(_PAYLOAD_FIELDS)}")
    return GraphArtifact(
        graph=payload["graph"],
        pois=tuple(payload["pois"]) if isinstance(payload["pois"], list) else payload["pois"],
        metadata=payload["metadata"],
    )
