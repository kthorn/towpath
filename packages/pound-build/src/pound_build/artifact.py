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
from pound.artifact import (  # pyright: ignore[reportMissingImports]
    ROUTING_ARTIFACT_SCHEMA_VERSION,
    InvalidArtifactError,
    RuntimeArtifact,
)
from pound.geometry import (
    edge_line_wgs84 as _edge_line_wgs84,  # pyright: ignore[reportMissingImports]
)
from pound.models import (  # pyright: ignore[reportMissingImports]
    POI_CORRIDOR_M,
    AccessCaveat,
    OsmElementType,
    PoiCategory,
    RuntimePoi,
)
from pydantic import ValidationError  # pyright: ignore[reportMissingImports]
from shapely.geometry import Point

from pound_build.graph.compact import _candidate_eligible
from pound_build.graph.pois import (  # pyright: ignore[reportPrivateUsage,reportPrivateImportUsage]
    _routing_eligible,
    _to_bng,
)
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
_DETAILED_NODE_FIELDS = {
    "lat",
    "lon",
    "osm_node_ids",
    "movable_bridge_ids",
    "turning_point",
    "turning_max_length_m",
}
_COMPACT_NODE_FIELDS = {
    "lat",
    "lon",
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
_COMPACT_EDGE_FIELDS = _EDGE_FIELDS | {"candidate_eligible"}
_CORRIDOR_M = {category.value: distance for category, distance in POI_CORRIDOR_M.items()}


def _invalid(field: str, value: Any, problem: str) -> InvalidArtifactError:
    return InvalidArtifactError(
        f"Invalid artifact {field}={value!r}: {problem}. "
        "Rebuild the artifact with this Pound version."
    )


def _finite_coordinate(field: str, value: Any, lower: float, upper: float) -> None:
    if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
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


def _validate_graph(graph: Any, *, compact: bool = False) -> nx.Graph:
    if not isinstance(graph, nx.Graph) or graph.is_directed() or graph.is_multigraph():
        raise _invalid("graph", type(graph).__name__, "expected an undirected networkx.Graph")
    node_fields = _COMPACT_NODE_FIELDS if compact else _DETAILED_NODE_FIELDS
    edge_fields = _COMPACT_EDGE_FIELDS if compact else _EDGE_FIELDS
    for uid, data in graph.nodes(data=True):
        missing = node_fields - data.keys()
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
        if compact and "osm_node_ids" in data:
            raise _invalid(
                f"graph node {uid} attribute osm_node_ids",
                data["osm_node_ids"],
                "build-only node fields are not permitted",
            )
        _validate_sorted_bridge_ids(
            f"graph node {uid} attribute movable_bridge_ids", data["movable_bridge_ids"]
        )
    for u, v, data in graph.edges(data=True):
        missing = edge_fields - data.keys()
        if missing:
            attribute = sorted(missing)[0]
            raise _invalid(
                f"graph edge {(u, v)} attribute {attribute}", None, "required attribute missing"
            )
        length_m = data["length_m"]
        if type(length_m) not in (int, float) or not math.isfinite(length_m) or length_m < 0:
            raise _invalid(
                f"graph edge {(u, v)} attribute length_m",
                length_m,
                "expected a finite nonnegative number",
            )
        locks = data["locks"]
        if type(locks) is not int or locks < 0:
            raise _invalid(
                f"graph edge {(u, v)} attribute locks", locks, "expected a nonnegative integer"
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
        if compact:
            candidate_eligible = data["candidate_eligible"]
            if type(candidate_eligible) is not bool:
                raise _invalid(
                    f"graph edge {(u, v)} attribute candidate_eligible",
                    candidate_eligible,
                    "expected a boolean",
                )
            if candidate_eligible != _candidate_eligible(data):
                raise _invalid(
                    f"graph edge {(u, v)} attribute candidate_eligible",
                    candidate_eligible,
                    "does not match the lock and movable-bridge policy",
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


def validate_detailed_graph_and_attachments(
    graph: nx.Graph, attached_pois
) -> tuple[PointOfInterest, ...]:
    """Validate the detailed graph and preserve the 0.01 m POI attachment gate."""
    _validate_graph(graph)
    try:
        raw_pois = tuple(attached_pois)
    except TypeError as exc:
        raise _invalid("pois", attached_pois, "expected an iterable of attached POIs") from exc
    parsed_pois = _parse_pois(raw_pois, trust_validated_instances=True)
    _validate_attachments(graph, parsed_pois)
    return parsed_pois


def validate_compact_graph(graph: nx.Graph) -> nx.Graph:
    """Validate the compact runtime graph contract."""
    return _validate_graph(graph, compact=True)


def _runtime_poi(poi: PointOfInterest) -> RuntimePoi:
    return RuntimePoi(
        osm_type=poi.osm_type,
        osm_id=poi.osm_id,
        category=poi.category,
        kind=poi.kind,
        name=poi.name,
        lat=poi.lat,
        lon=poi.lon,
    )


def _runtime_pois(attached_pois: tuple[PointOfInterest, ...]) -> tuple[RuntimePoi, ...]:
    return tuple(_runtime_poi(poi) for poi in attached_pois)


def validate_runtime_pois(pois) -> tuple[RuntimePoi, ...]:
    """Validate attachment-free immutable runtime POI records."""
    if not isinstance(pois, (list, tuple)):
        raise _invalid("pois", pois, "expected a list or tuple")
    identities = set()
    validated: list[RuntimePoi] = []
    for index, poi in enumerate(pois):
        if type(poi) is not RuntimePoi:
            raise _invalid(f"pois[{index}]", poi, "expected RuntimePoi")
        if not isinstance(poi.osm_type, OsmElementType):
            raise _invalid(f"pois[{index}].osm_type", poi.osm_type, "expected OsmElementType")
        if type(poi.osm_id) is not int or poi.osm_id <= 0:
            raise _invalid(f"pois[{index}].osm_id", poi.osm_id, "expected a positive integer")
        if not isinstance(poi.category, PoiCategory):
            raise _invalid(f"pois[{index}].category", poi.category, "expected PoiCategory")
        if not isinstance(poi.kind, str) or not poi.kind:
            raise _invalid(f"pois[{index}].kind", poi.kind, "expected a non-empty string")
        if poi.name is not None and not isinstance(poi.name, str):
            raise _invalid(f"pois[{index}].name", poi.name, "expected a string or null")
        _finite_coordinate(f"pois[{index}].lat", poi.lat, -90, 90)
        _finite_coordinate(f"pois[{index}].lon", poi.lon, -180, 180)
        identity = (poi.osm_type, poi.osm_id, poi.kind)
        if identity in identities:
            raise _invalid(f"pois[{index}].identity", identity, "duplicate POI identity")
        identities.add(identity)
        validated.append(poi)
    return tuple(validated)


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
    version = metadata["artifact_schema_version"]
    if type(version) is not int or version != ROUTING_ARTIFACT_SCHEMA_VERSION:
        raise _invalid(
            "metadata.artifact_schema_version",
            version,
            f"expected supported version {ROUTING_ARTIFACT_SCHEMA_VERSION}",
        )
    for field in ("artifact_revision", "source", "fetched_at", "built_at"):
        if not isinstance(metadata[field], str) or not metadata[field]:
            raise _invalid(f"metadata.{field}", metadata[field], "expected a non-empty string")
    for field in ("validation", "poi_summary"):
        if not isinstance(metadata[field], dict):
            raise _invalid(f"metadata.{field}", metadata[field], "expected a mapping")
    return dict(metadata)


def _validate_gazetteer(gazetteer: Any) -> dict:
    if not isinstance(gazetteer, dict):
        raise _invalid("gazetteer", gazetteer, "expected a mapping")

    for name, entry in gazetteer.items():
        if type(name) is not str or not name:
            raise _invalid("gazetteer key", name, "expected a non-empty string")
        if isinstance(entry, tuple):
            coordinates = (entry,)
            if len(entry) != 2:
                raise _invalid(
                    f"gazetteer[{name!r}]", entry, "expected a (latitude, longitude) pair"
                )
        elif isinstance(entry, list) and len(entry) >= 2:
            coordinates = entry
        else:
            raise _invalid(
                f"gazetteer[{name!r}]",
                entry,
                "expected a coordinate pair or a duplicate-name list",
            )

        for index, coordinate in enumerate(coordinates):
            if type(coordinate) is not tuple or len(coordinate) != 2:
                raise _invalid(
                    f"gazetteer[{name!r}][{index}]",
                    coordinate,
                    "expected a (latitude, longitude) pair",
                )
            latitude, longitude = coordinate
            if (
                type(latitude) not in (int, float)
                or not math.isfinite(latitude)
                or not -90 <= latitude <= 90
                or type(longitude) not in (int, float)
                or not math.isfinite(longitude)
                or not -180 <= longitude <= 180
            ):
                raise _invalid(
                    f"gazetteer[{name!r}][{index}]",
                    coordinate,
                    "expected finite latitude/longitude values in geographic bounds",
                )
    return gazetteer


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
    gazetteer = _validate_gazetteer(gazetteer)
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
    """Validate detailed build inputs and convert attached POIs to runtime records."""
    attached_pois = validate_detailed_graph_and_attachments(graph, tuple(pois))
    complete_metadata = dict(metadata)
    complete_metadata.setdefault("artifact_revision", str(uuid4()))
    complete_metadata.setdefault("artifact_schema_version", ROUTING_ARTIFACT_SCHEMA_VERSION)
    return RuntimeArtifact(
        graph=graph,
        pois=_runtime_pois(attached_pois),
        gazetteer=_validate_gazetteer(gazetteer),
        metadata=_validate_metadata(complete_metadata),
    )


def _prepare_compact_artifact(
    graph: nx.Graph, pois, gazetteer: dict, metadata: dict
) -> RuntimeArtifact:
    """Validate compact graph and attachment-free POIs immediately before writing."""
    complete_metadata = dict(metadata)
    complete_metadata.setdefault("artifact_revision", str(uuid4()))
    complete_metadata.setdefault("artifact_schema_version", ROUTING_ARTIFACT_SCHEMA_VERSION)
    return RuntimeArtifact(
        graph=validate_compact_graph(graph),
        pois=validate_runtime_pois(tuple(pois)),
        gazetteer=_validate_gazetteer(gazetteer),
        metadata=_validate_metadata(complete_metadata),
    )


def write_artifact(
    artifact_or_graph: RuntimeArtifact | nx.Graph,
    runtime_pois_or_path,
    gazetteer: dict | None = None,
    metadata: dict | None = None,
    path: Path | None = None,
) -> None:
    """Atomically publish a validated compact artifact.

    The two-argument RuntimeArtifact form remains for existing build utilities; new builds use
    ``(graph, runtime_pois, gazetteer, metadata, path)`` so validation stays in the producer.
    """
    artifact: RuntimeArtifact
    output_path: Path
    if isinstance(artifact_or_graph, RuntimeArtifact):
        if gazetteer is not None or metadata is not None or path is not None:
            raise _invalid("artifact", artifact_or_graph, "unexpected compact artifact arguments")
        artifact = artifact_or_graph
        output_path = Path(runtime_pois_or_path)
    else:
        if path is None:
            raise _invalid("path", path, "expected an output path for compact graph inputs")
        artifact = _prepare_compact_artifact(
            artifact_or_graph,
            runtime_pois_or_path,
            {} if gazetteer is None else gazetteer,
            {} if metadata is None else metadata,
        )
        output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "graph": artifact.graph,
        "pois": list(artifact.pois),
        "gazetteer": artifact.gazetteer,
        "metadata": artifact.metadata,
    }
    with NamedTemporaryFile("wb", dir=output_path.parent, delete=False) as stream:
        pickle.dump(payload, stream)  # pi-lens-ignore: python-pickle
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(stream.name, output_path)
