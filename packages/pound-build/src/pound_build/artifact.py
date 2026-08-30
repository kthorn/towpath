"""Validate and serialize locally produced routing graph artifacts.

Artifacts use pickle and therefore must only be loaded from trusted, local Pound builds. Pickle is
not a safe interchange format and this module does not make untrusted pickle data safe to load.
"""

import math
import os
import pickle
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4

import networkx as nx
from pound.artifact import ROUTING_ARTIFACT_SCHEMA_VERSION, InvalidArtifactError, RuntimeArtifact
from pound.models import POI_CORRIDOR_M, AccessCaveat, RuntimePoi
from pydantic import ValidationError
from shapely.geometry import Point

from pound_build.graph.pois import _edge_line_wgs84, _routing_eligible, _to_bng
from pound_build.ingest.filters import extract_access_caveats
from pound_build.ingest.ir import PointOfInterest

_PAYLOAD_FIELDS = {"graph", "pois", "gazetteer", "metadata"}
_METADATA_FIELDS = {
    "artifact_schema_version",
    "artifact_revision",
    "source",
    "fetched_at",
    "built_at",
    "validation",
    "poi_summary",
}
_NODE_FIELDS = {
    "lat",
    "lon",
    "osm_node_ids",
    "movable_bridge_ids",
    "turning_point",
    "turning_max_length_m",
}
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
    "access_caveats",
}
_CORRIDOR_M = {category.value: distance for category, distance in POI_CORRIDOR_M.items()}


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


def _validate_access_caveats(edge: tuple[int, int], caveats: Any) -> None:
    if not isinstance(caveats, tuple):
        raise _invalid(f"graph edge {edge} attribute access_caveats", caveats, "expected a tuple")
    for caveat in caveats:
        if type(caveat) is not AccessCaveat:
            raise _invalid(f"graph edge {edge} access_caveat", caveat, "expected AccessCaveat")
        if type(caveat.osm_way_id) is not int or caveat.osm_way_id <= 0:
            raise _invalid(
                f"graph edge {edge} access_caveat",
                caveat,
                "expected a positive OSM way id",
            )
        if (
            not isinstance(caveat.tag, str)
            or caveat.tag not in {"boat", "access"}
            or not isinstance(caveat.value, str)
            or not caveat.value
        ):
            raise _invalid(
                f"graph edge {edge} access_caveat",
                caveat,
                "expected a supported non-empty tag value",
            )
        if extract_access_caveats(caveat.osm_way_id, {caveat.tag: caveat.value}) != (caveat,):
            raise _invalid(
                f"graph edge {edge} access_caveat",
                caveat,
                "does not match public-access policy",
            )
    if caveats != tuple(sorted(set(caveats))):
        raise _invalid(
            f"graph edge {edge} attribute access_caveats",
            caveats,
            "expected sorted unique caveats",
        )


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
        if type(data["turning_point"]) is not bool:
            raise _invalid(
                f"graph node {uid} attribute turning_point",
                data["turning_point"],
                "expected a boolean",
            )
        maximum = data["turning_max_length_m"]
        if maximum is not None and (
            isinstance(maximum, bool)
            or not isinstance(maximum, (int, float))
            or not math.isfinite(maximum)
            or maximum <= 0
        ):
            raise _invalid(
                f"graph node {uid} attribute turning_max_length_m",
                maximum,
                "expected None or a finite positive number",
            )
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
        _validate_access_caveats((u, v), data["access_caveats"])
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
    if metadata["artifact_schema_version"] != ROUTING_ARTIFACT_SCHEMA_VERSION:
        raise _invalid(
            "metadata.artifact_schema_version",
            metadata["artifact_schema_version"],
            f"expected supported version {ROUTING_ARTIFACT_SCHEMA_VERSION}",
        )
    for field in ("artifact_revision", "source", "fetched_at", "built_at"):
        if not isinstance(metadata[field], str) or not metadata[field]:
            raise _invalid(f"metadata.{field}", metadata[field], "expected a non-empty string")
    for field in ("validation", "poi_summary"):
        if not isinstance(metadata[field], dict):
            raise _invalid(f"metadata.{field}", metadata[field], "expected a mapping")
    return dict(metadata)


def _prepare_artifact(
    graph: nx.Graph,
    pois,
    gazetteer: dict,
    metadata: dict,
    *,
    trust_validated_instances: bool,
) -> RuntimeArtifact:
    graph = _validate_graph(graph)
    parsed_pois = _parse_pois(pois, trust_validated_instances=trust_validated_instances)
    metadata = _validate_metadata(metadata)
    _validate_attachments(graph, parsed_pois)
    if not isinstance(gazetteer, dict):
        raise _invalid("gazetteer", gazetteer, "expected a mapping")
    return RuntimeArtifact(
        graph=graph,
        pois=tuple(
            RuntimePoi(
                osm_type=poi.osm_type,
                osm_id=poi.osm_id,
                category=poi.category,
                kind=poi.kind,
                name=poi.name,
                lat=poi.lat,
                lon=poi.lon,
            )
            for poi in parsed_pois
        ),
        gazetteer=gazetteer,
        metadata=metadata,
    )


def prepare_artifact(graph: nx.Graph, pois, gazetteer: dict, metadata: dict) -> RuntimeArtifact:
    """Validate build values and return their runtime artifact representation."""
    complete_metadata = dict(metadata)
    complete_metadata.setdefault("artifact_revision", str(uuid4()))
    complete_metadata.setdefault("artifact_schema_version", ROUTING_ARTIFACT_SCHEMA_VERSION)
    return _prepare_artifact(
        graph,
        tuple(pois),
        gazetteer,
        complete_metadata,
        trust_validated_instances=False,
    )


def _prepare_build_artifact(
    graph: nx.Graph, pois, gazetteer: dict, metadata: dict
) -> RuntimeArtifact:
    """Prepare CLI-owned POIs without serializing them for Pydantic revalidation."""
    complete_metadata = dict(metadata)
    complete_metadata.setdefault("artifact_revision", str(uuid4()))
    complete_metadata.setdefault("artifact_schema_version", ROUTING_ARTIFACT_SCHEMA_VERSION)
    return _prepare_artifact(
        graph,
        tuple(pois),
        gazetteer,
        complete_metadata,
        trust_validated_instances=True,
    )


def write_artifact(artifact: RuntimeArtifact, path: Path) -> None:
    """Atomically publish an already validated runtime artifact."""
    if not isinstance(artifact, RuntimeArtifact):
        raise _invalid("artifact", artifact, "expected RuntimeArtifact")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "graph": artifact.graph,
        "pois": list(artifact.pois),
        "gazetteer": artifact.gazetteer,
        "metadata": artifact.metadata,
    }
    with NamedTemporaryFile("wb", dir=path.parent, delete=False) as stream:
        pickle.dump(payload, stream)  # pi-lens-ignore: python-pickle
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(stream.name, path)
