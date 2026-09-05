"""Build and validate the artifact's offline turnaround index.

Mapped ``waterway=turning_point`` nodes come from the ingest IR.  Junctions are
derived from the noded routing graph, so the index remains independent of a
particular boat's restrictions.  This module deliberately owns the edge split
operation: callers must run it before attaching locks or other edge-local
infrastructure.
"""

from __future__ import annotations

import copy
import math
from collections import defaultdict
from typing import Any

import networkx as nx
from pyproj import Transformer
from shapely import transform
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from pound.graph.pois import _routing_eligible
from pound.ingest.ir import NodeKind, WaterwayFeatures, WaterwayNode

_TO_BNG = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
_TO_WGS84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
_ATTACHMENT_TOLERANCE_M = 25.0
_ENDPOINT_TOLERANCE_M = 0.01
_TIE_TOLERANCE_M = 0.1
_COORD_ROUND = 7
_SOURCE_REQUIRED = {"source", "identity", "source_date", "attribution"}
_RECORD_REQUIRED = {
    "turnaround_id",
    "kind",
    "node_uid",
    "coordinate",
    "display_name",
    "eligibility_basis",
    "sources",
    "turning_limits",
}
_LIMIT_FIELDS = {
    "boat_length_m",
    "boat_beam_m",
    "boat_draft_m",
    "boat_height_m",
    "prohibited",
}


def _coord_key(lat: float, lon: float) -> tuple[float, float]:
    return round(lat, _COORD_ROUND), round(lon, _COORD_ROUND)


def _node_sort_key(uid: Any) -> tuple[str, str]:
    return type(uid).__name__, repr(uid)


def _edge_key(u: Any, v: Any) -> frozenset[Any]:
    return frozenset((u, v))


def _metric_line(geometry: list | tuple):
    line = LineString([(float(lon), float(lat)) for lat, lon in geometry])
    return transform(line, _TO_BNG.transform, interleaved=False)


def _project(geometry, lat: float, lon: float):
    """Return (projected lat/lon, offset m, along m, total m), or None."""
    try:
        metric = _metric_line(geometry)
        if metric.is_empty or metric.length <= 0:
            return None
        source = Point(*_TO_BNG.transform(float(lon), float(lat)))
        along = float(metric.project(source))
        projected = metric.interpolate(along)
        projected_wgs = transform(projected, _TO_WGS84.transform, interleaved=False)
        return (
            (float(projected_wgs.y), float(projected_wgs.x)),
            float(source.distance(metric)),
            along,
            float(metric.length),
        )
    except (TypeError, ValueError, OverflowError, RuntimeError):
        return None


def _split_geometry(geometry, projected, along, total):
    """Split a polyline at a metric distance while retaining every vertex."""
    coordinates = [tuple(point) for point in geometry]
    metric_points = [_TO_BNG.transform(float(lon), float(lat)) for lat, lon in coordinates]
    distances = [0.0]
    for first, second in zip(metric_points, metric_points[1:], strict=False):
        distances.append(distances[-1] + math.hypot(second[0] - first[0], second[1] - first[1]))
    left = [coordinates[0]]
    right = [coordinates[-1]]
    inserted = False
    for index in range(1, len(coordinates)):
        if abs(along - distances[index]) <= 1e-7:
            return coordinates[: index + 1], coordinates[index:]
        if not inserted and along < distances[index] - 1e-8:
            left.append(projected)
            right = [projected, *coordinates[index:]]
            inserted = True
        if not inserted:
            left.append(coordinates[index])
    if not inserted:
        left = [*coordinates[:-1], projected]
        right = [projected, coordinates[-1]]
    return left, right


def _split_edge(graph: nx.Graph, u, v, projection) -> Any:
    data = graph.edges[u, v]
    projected, _, along, total = projection
    geometry = [tuple(point) for point in data["geometry"]]
    u_coordinate = (graph.nodes[u]["lat"], graph.nodes[u]["lon"])
    reversed_geometry = False
    if _coord_key(*geometry[0]) != _coord_key(*u_coordinate):
        geometry.reverse()
        along = total - along
        reversed_geometry = True
    left_geometry, right_geometry = _split_geometry(geometry, projected, along, total)
    numeric_uids = [uid for uid in graph.nodes if type(uid) is int]
    new_uid = (max(numeric_uids) + 1) if numeric_uids else 0
    while graph.has_node(new_uid):
        new_uid += 1
    graph.add_node(
        new_uid,
        lat=projected[0],
        lon=projected[1],
        osm_node_ids=set(),
        movable_bridge_ids=(),
    )

    left_data = copy.deepcopy(data)
    right_data = copy.deepcopy(data)
    original_length = float(data.get("length_m", 0.0))
    ratio = max(0.0, min(1.0, along / total))
    left_data["length_m"] = original_length * ratio
    right_data["length_m"] = original_length - left_data["length_m"]
    left_data["geometry"] = left_geometry
    right_data["geometry"] = right_geometry

    if "lock_points" in data:
        left_points = []
        right_points = []
        for point in data["lock_points"]:
            point_projection = _project(geometry, point[0], point[1])
            if point_projection is not None and point_projection[2] <= along + 1e-8:
                left_points.append(point)
            else:
                right_points.append(point)
        left_data["lock_points"] = left_points
        right_data["lock_points"] = right_points
        locks = int(data.get("locks", 0))
        if locks and (left_points or right_points):
            left_data["locks"] = min(locks, len(left_points))
            right_data["locks"] = locks - left_data["locks"]
        elif locks:
            positions = list(data.get("_turnaround_lock_positions", (0.5,) * locks))
            if reversed_geometry:
                positions = [1.0 - position for position in positions]
            left_positions = [position for position in positions if position <= along / total]
            right_positions = [position for position in positions if position > along / total]
            left_data["locks"] = len(left_positions)
            right_data["locks"] = len(right_positions)
            left_data["_turnaround_lock_positions"] = (
                [position / (along / total) for position in left_positions]
                if left_positions and along > 0
                else []
            )
            right_data["_turnaround_lock_positions"] = (
                [(position - along / total) / (1 - along / total) for position in right_positions]
                if right_positions and along < total
                else []
            )
    elif int(data.get("locks", 0)):
        locks = int(data["locks"])
        positions = list(data.get("_turnaround_lock_positions", (0.5,) * locks))
        if reversed_geometry:
            positions = [1.0 - position for position in positions]
        ratio = along / total
        left_positions = [position for position in positions if position <= ratio]
        right_positions = [position for position in positions if position > ratio]
        left_data["locks"] = len(left_positions)
        right_data["locks"] = len(right_positions)
        left_data["_turnaround_lock_positions"] = [position / ratio for position in left_positions]
        right_data["_turnaround_lock_positions"] = [
            (position - ratio) / (1 - ratio) for position in right_positions
        ]
    # IDs identify occurrences. Keep each on one child edge, placing an
    # otherwise unlocated occurrence at the source edge midpoint. This keeps a
    # bridge operation from being charged twice and avoids charging a bridge
    # before a turning point that lies before it.
    bridge_ids = tuple(data.get("movable_bridge_ids", ()))
    has_bridge = bool(data.get("has_movable_bridge"))
    bridge_positions = {
        bridge_id: float(data.get("_turnaround_bridge_positions", {}).get(bridge_id, 0.5))
        for bridge_id in bridge_ids
    }
    if reversed_geometry:
        bridge_positions = {
            bridge_id: 1.0 - position for bridge_id, position in bridge_positions.items()
        }
    ratio = along / total
    left_bridge_positions = {
        bridge_id: position for bridge_id, position in bridge_positions.items() if position <= ratio
    }
    right_bridge_positions = {
        bridge_id: position for bridge_id, position in bridge_positions.items() if position > ratio
    }
    left_data["movable_bridge_ids"] = tuple(sorted(left_bridge_positions))
    left_data["has_movable_bridge"] = bool(left_bridge_positions) or (
        has_bridge and not bridge_ids and ratio > 0.5
    )
    right_data["movable_bridge_ids"] = tuple(sorted(right_bridge_positions))
    right_data["has_movable_bridge"] = bool(right_bridge_positions) or (
        has_bridge and not bridge_ids and ratio <= 0.5
    )
    if left_bridge_positions:
        left_data["_turnaround_bridge_positions"] = {
            bridge_id: position / ratio for bridge_id, position in left_bridge_positions.items()
        }
    if right_bridge_positions:
        right_data["_turnaround_bridge_positions"] = {
            bridge_id: (position - ratio) / (1 - ratio)
            for bridge_id, position in right_bridge_positions.items()
        }
    graph.remove_edge(u, v)
    graph.add_edge(u, new_uid, **left_data)
    graph.add_edge(new_uid, v, **right_data)
    return new_uid


def _positive_limit(tags: dict[str, str], aliases: tuple[str, ...]) -> float | None:
    for alias in aliases:
        if alias not in tags:
            continue
        try:
            value = float(tags[alias])
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0:
            return value
    return None


def _turning_limits(tags: dict[str, str]) -> dict[str, object]:
    limits: dict[str, object] = {}
    aliases = {
        "boat_length_m": ("maxlength", "max_length"),
        "boat_beam_m": ("maxwidth", "maxbeam", "width"),
        "boat_draft_m": ("maxdraft", "maxdraught", "depth"),
        "boat_height_m": ("maxheight", "maxclosedheight"),
    }
    for field, names in aliases.items():
        value = _positive_limit(tags, names)
        if value is not None:
            limits[field] = value
    prohibited_values = {
        tags.get("turning"),
        tags.get("turning:boat"),
        tags.get("boat"),
        tags.get("access"),
    }
    if prohibited_values & {"no", "private", "permit", "unsuitable", "canoe"}:
        limits["prohibited"] = True
    return limits


def _source(node: WaterwayNode, features: WaterwayFeatures) -> dict[str, object]:
    return {
        "source": features.source,
        "identity": f"node/{node.osm_id}",
        "source_date": features.fetched_at,
        "attribution": "© OpenStreetMap contributors",
        "tags": dict(sorted(node.tags.items())),
    }


def _winding_record(
    node: WaterwayNode, uid: int, graph: nx.Graph, features: WaterwayFeatures
) -> dict:
    name = node.tags.get("name") or "Winding hole"
    attached_coordinate = {
        "lat": float(graph.nodes[uid]["lat"]),
        "lon": float(graph.nodes[uid]["lon"]),
    }
    source = _source(node, features)
    source["evidence"] = {"source_coordinate": {"lat": float(node.lat), "lon": float(node.lon)}}
    return {
        "turnaround_id": f"osm:node/{node.osm_id}",
        "kind": "winding_hole",
        "node_uid": uid,
        "coordinate": attached_coordinate,
        "display_name": name,
        "eligibility_basis": "mapped_winding_hole",
        "sources": [source],
        "turning_limits": _turning_limits(node.tags),
    }


def _junction_record(graph: nx.Graph, uid: int, features: WaterwayFeatures) -> dict:
    node = graph.nodes[uid]
    lat, lon = float(node["lat"]), float(node["lon"])
    incident = [
        graph.edges[uid, neighbor]
        for neighbor in graph.neighbors(uid)
        if _routing_eligible(graph.edges[uid, neighbor])
    ]
    kinds = sorted({getattr(edge.get("kind"), "value", edge.get("kind")) for edge in incident})
    identity = f"junction:{_coord_key(lat, lon)[0]:.7f},{_coord_key(lat, lon)[1]:.7f}"
    return {
        "turnaround_id": identity,
        "kind": "junction",
        "node_uid": uid,
        "coordinate": {"lat": lat, "lon": lon},
        "display_name": node.get("name") or "Canal junction",
        "eligibility_basis": "junction_assumption",
        "sources": [
            {
                "source": "pound",
                "identity": identity,
                "source_date": features.fetched_at,
                "attribution": "Pound graph derivation",
                "evidence": {"degree": len(set(graph.neighbors(uid))), "incident_kinds": kinds},
            }
        ],
        "turning_limits": {},
    }


def _merge_limits(records: list[dict], conflicts: list[dict]) -> dict:
    merged: dict[str, object] = {}
    for record in records:
        for field, value in record["turning_limits"].items():
            previous = merged.get(field)
            if field == "prohibited":
                merged[field] = bool(previous) or bool(value)
            elif previous is None:
                merged[field] = value
            else:
                if float(previous) != float(value):
                    conflicts.append({"field": field, "values": [previous, value]})
                accepted = min(float(previous), float(value))
                merged[field] = accepted
    return merged


def _canonical_sources(sources: list[dict]) -> list[dict]:
    unique = {repr(sorted(source.items())): source for source in sources}
    return [unique[key] for key in sorted(unique)]


def _merge_records(records: list[dict], conflicts: list[dict]) -> dict:
    records = sorted(
        records,
        key=lambda record: (record["kind"] != "winding_hole", record["turnaround_id"]),
    )
    primary = copy.deepcopy(records[0])
    primary["sources"] = _canonical_sources(
        [source for record in records for source in record["sources"]]
    )
    primary["turning_limits"] = _merge_limits(records, conflicts)
    return primary


class _EdgeSpatialIndex:
    """Metric edge index used only for source points without exact node joins."""

    def __init__(self, graph: nx.Graph):
        self._edges = []
        self._descendants: dict[int, set[tuple[Any, Any]]] = {}
        geometries = []
        for u, v, data in graph.edges(data=True):
            if not _routing_eligible(data):
                continue
            try:
                metric = _metric_line(data.get("geometry", ()))
            except (TypeError, ValueError, RuntimeError):
                continue
            if metric.is_empty or metric.length <= 0:
                continue
            index = len(self._edges)
            self._edges.append((u, v, data, metric))
            self._descendants[index] = {(u, v)}
            geometries.append(metric)
        self._tree = STRtree(geometries)

    def record_split(self, index: int, u, v, new_uid) -> None:
        descendants = self._descendants[index]
        old = next(edge for edge in descendants if _edge_key(*edge) == _edge_key(u, v))
        descendants.discard(old)
        if old[0] == u and old[1] == v:
            descendants.add((u, new_uid))
            descendants.add((new_uid, v))
        else:
            descendants.add((v, new_uid))
            descendants.add((new_uid, u))

    def candidates(self, graph: nx.Graph, node: WaterwayNode):
        try:
            source = Point(*_TO_BNG.transform(float(node.lon), float(node.lat)))
            indexes = self._tree.query(source.buffer(_ATTACHMENT_TOLERANCE_M))
        except (TypeError, ValueError, RuntimeError, OverflowError):
            return []
        matches = []
        for raw_index in indexes:
            index = int(raw_index)
            for u, v in self._descendants[index]:
                if not graph.has_edge(u, v):
                    continue
                data = graph.edges[u, v]
                projection = _project(data.get("geometry", ()), node.lat, node.lon)
                if projection is None or projection[1] > _ATTACHMENT_TOLERANCE_M:
                    continue
                matches.append((projection[1], u, v, projection, index))
        return sorted(
            matches,
            key=lambda value: (
                value[0],
                *_node_sort_key(value[1]),
                *_node_sort_key(value[2]),
            ),
        )


def _projected_endpoint_uid(graph: nx.Graph, u, v, projection):
    first = graph.edges[u, v]["geometry"][0]
    starts_at_u = _coord_key(*first) == _coord_key(graph.nodes[u]["lat"], graph.nodes[u]["lon"])
    if projection[2] <= _ENDPOINT_TOLERANCE_M:
        return u if starts_at_u else v
    if projection[2] >= projection[3] - _ENDPOINT_TOLERANCE_M:
        return v if starts_at_u else u
    return None


def _near_restricted(coordinate, restricted_coordinates) -> bool:
    return any(
        abs(coordinate[0] - other[0]) <= 2e-6 and abs(coordinate[1] - other[1]) <= 2e-6
        for other in restricted_coordinates
    )


def build_turnarounds(
    graph: nx.Graph,
    features: WaterwayFeatures,
    *,
    in_place: bool = False,
) -> tuple[nx.Graph, dict]:
    """Attach mapped points, split interior edges, and derive junction records."""
    result = graph if in_place else copy.deepcopy(graph)
    report: dict[str, object] = {
        "attached": [],
        "unmatched": [],
        "ambiguous": [],
        "restricted": [],
        "conflicting": [],
        "junctions": 0,
    }
    by_node: dict[Any, list[dict]] = defaultdict(list)
    restricted_uids: set[Any] = set()
    restricted_coordinates: set[tuple[float, float]] = set()
    edge_index = None

    def candidates_for(node):
        nonlocal edge_index
        if edge_index is None:
            edge_index = _EdgeSpatialIndex(result)
        return edge_index.candidates(result, node)

    osm_nodes: dict[str, list[Any]] = defaultdict(list)
    coordinate_nodes: dict[tuple[float, float], list[Any]] = defaultdict(list)
    for uid, data in result.nodes(data=True):
        for osm_id in data.get("osm_node_ids", set()):
            osm_nodes[str(osm_id)].append(uid)
        coordinate_nodes[_coord_key(data["lat"], data["lon"])].append(uid)
    for values in (*osm_nodes.values(), *coordinate_nodes.values()):
        values.sort(key=_node_sort_key)
    mapped_nodes = sorted(
        (node for node in features.nodes if node.kind == NodeKind.TURNING_POINT),
        key=lambda node: node.osm_id,
    )
    for node in mapped_nodes:
        public_access_values = {"no", "private", "permit", "unsuitable", "canoe"}
        if (
            node.tags.get("access") in public_access_values
            or node.tags.get("boat") in public_access_values
        ):
            report["restricted"].append(f"node/{node.osm_id}")
            restricted_coordinates.add(_coord_key(node.lat, node.lon))
            ids = osm_nodes.get(str(node.osm_id), [])
            if len(set(ids)) == 1:
                restricted_uids.add(ids[0])
            else:
                exact = coordinate_nodes.get(_coord_key(node.lat, node.lon), [])
                if len(set(exact)) == 1:
                    restricted_uids.add(exact[0])
                else:
                    candidates = candidates_for(node)
                    if candidates:
                        tied = [
                            candidate
                            for candidate in candidates
                            if candidate[0] - candidates[0][0] <= _TIE_TOLERANCE_M
                        ]
                        endpoints = {
                            _projected_endpoint_uid(
                                result, candidate[1], candidate[2], candidate[3]
                            )
                            for candidate in tied
                        }
                        if len(endpoints) == 1 and None not in endpoints:
                            restricted_uids.add(next(iter(endpoints)))
            continue
        ids = osm_nodes.get(str(node.osm_id), [])
        if len(set(ids)) == 1:
            uid = ids[0]
        else:
            exact = coordinate_nodes.get(_coord_key(node.lat, node.lon), [])
            if len(set(exact)) == 1:
                uid = exact[0]
            else:
                candidates = candidates_for(node)
                if not candidates:
                    report["unmatched"].append(f"node/{node.osm_id}")
                    continue
                best_distance = candidates[0][0]
                tied = [
                    candidate
                    for candidate in candidates
                    if candidate[0] - best_distance <= _TIE_TOLERANCE_M
                ]
                if len(tied) > 1:
                    tied_endpoint_uids = {
                        _projected_endpoint_uid(result, candidate[1], candidate[2], candidate[3])
                        for candidate in tied
                    }
                    if len(tied_endpoint_uids) == 1 and None not in tied_endpoint_uids:
                        uid = next(iter(tied_endpoint_uids))
                    else:
                        report["ambiguous"].append(
                            {
                                "identity": f"node/{node.osm_id}",
                                "edges": sorted(
                                    repr((candidate[1], candidate[2])) for candidate in tied
                                ),
                            }
                        )
                        continue
                else:
                    _, u, v, projection, edge_origin = candidates[0]
                    uid = _projected_endpoint_uid(result, u, v, projection)
                    if uid is None:
                        uid = _split_edge(result, u, v, projection)
                        edge_index.record_split(edge_origin, u, v, uid)
                        result.nodes[uid]["osm_node_ids"].add(str(node.osm_id))
                        osm_nodes[str(node.osm_id)].append(uid)
                        coordinate_nodes[_coord_key(*projection[0])].append(uid)
                        if _near_restricted(projection[0], restricted_coordinates):
                            restricted_uids.add(uid)
        if _near_restricted((node.lat, node.lon), restricted_coordinates):
            restricted_uids.add(uid)
        if not any(
            _routing_eligible(result.edges[uid, neighbor]) for neighbor in result.neighbors(uid)
        ):
            report["unmatched"].append(f"node/{node.osm_id}")
            continue
        by_node[uid].append(_winding_record(node, uid, result, features))
        report["attached"].append(f"node/{node.osm_id}")

    for uid in sorted(result.nodes, key=_node_sort_key):
        if uid in restricted_uids:
            continue
        incident_by_neighbor = {
            neighbor: result.edges[uid, neighbor]
            for neighbor in result.neighbors(uid)
            if _routing_eligible(result.edges[uid, neighbor])
        }
        neighbors = set(incident_by_neighbor)
        incident = list(incident_by_neighbor.values())
        if len(neighbors) < 3:
            continue
        kinds = {getattr(edge.get("kind"), "value", edge.get("kind")) for edge in incident}
        if "canal" not in kinds:
            continue
        by_node[uid].append(_junction_record(result, uid, features))
        report["junctions"] = int(report["junctions"]) + 1

    records = []
    for uid in sorted(by_node, key=_node_sort_key):
        if uid in restricted_uids:
            continue
        records.append(_merge_records(by_node[uid], report["conflicting"]))
    records.sort(key=lambda record: record["turnaround_id"])
    result.graph["turnarounds"] = records
    result.graph["turnaround_report"] = report
    return result, report


def validate_turnarounds(graph: nx.Graph) -> list[dict]:
    """Validate and return the normalized index; missing legacy indexes are valid."""
    if "turnarounds" not in graph.graph:
        return []
    records = graph.graph["turnarounds"]
    if not isinstance(records, list):
        raise ValueError("turnarounds must be a list")
    previous = None
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != _RECORD_REQUIRED:
            raise ValueError(f"turnaround[{index}] fields are invalid")
        if not isinstance(record["turnaround_id"], str) or not record["turnaround_id"]:
            raise ValueError(f"turnaround[{index}] turnaround_id is invalid")
        if previous is not None and record["turnaround_id"] <= previous:
            raise ValueError("turnarounds must be sorted by turnaround_id")
        previous = record["turnaround_id"]
        if record["kind"] not in {"winding_hole", "junction"}:
            raise ValueError(f"turnaround[{index}] kind is invalid")
        expected_basis = (
            "mapped_winding_hole" if record["kind"] == "winding_hole" else "junction_assumption"
        )
        if record["eligibility_basis"] != expected_basis:
            raise ValueError(f"turnaround[{index}] eligibility_basis is invalid")
        uid = record["node_uid"]
        if isinstance(uid, bool) or not isinstance(uid, int) or not graph.has_node(uid):
            raise ValueError(f"turnaround[{index}] node_uid reference is invalid")
        coordinate = record["coordinate"]
        if not isinstance(coordinate, dict) or set(coordinate) != {"lat", "lon"}:
            raise ValueError(f"turnaround[{index}] coordinate is invalid")
        for field, lower, upper in (("lat", -90, 90), ("lon", -180, 180)):
            value = coordinate[field]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not lower <= value <= upper
            ):
                raise ValueError(f"turnaround[{index}] coordinate.{field} is invalid")
            if abs(float(value) - float(graph.nodes[uid][field])) > 1e-5:
                raise ValueError(f"turnaround[{index}] coordinate does not match node_uid")
        if not isinstance(record["display_name"], str) or not record["display_name"]:
            raise ValueError(f"turnaround[{index}] display_name is invalid")
        sources = record["sources"]
        if not isinstance(sources, list) or not sources:
            raise ValueError(f"turnaround[{index}] sources are invalid")
        for source in sources:
            if not isinstance(source, dict) or not _SOURCE_REQUIRED <= set(source):
                raise ValueError(f"turnaround[{index}] source is invalid")
            if any(
                not isinstance(source[field], str) or not source[field]
                for field in _SOURCE_REQUIRED
            ):
                raise ValueError(f"turnaround[{index}] source fields are invalid")
            for field in set(source) - _SOURCE_REQUIRED:
                if field not in {"tags", "evidence"} or not isinstance(source[field], dict):
                    raise ValueError(f"turnaround[{index}] source evidence is invalid")
        limits = record["turning_limits"]
        if not isinstance(limits, dict) or not set(limits) <= _LIMIT_FIELDS:
            raise ValueError(f"turnaround[{index}] turning_limits are invalid")
        for field, value in limits.items():
            if field == "prohibited":
                if type(value) is not bool:
                    raise ValueError(f"turnaround[{index}] prohibited is invalid")
            elif (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"turnaround[{index}] turning limit is invalid")
    return records
