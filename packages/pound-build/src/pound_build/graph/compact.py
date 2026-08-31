"""Contract detailed routing graphs into compact runtime graphs."""

import copy
import math
from collections.abc import Mapping
from typing import Any, cast

import networkx as nx
from pound.geometry import node_key as _node_key  # pyright: ignore[reportMissingImports]
from pound.models import WaterwayKind  # pyright: ignore[reportMissingImports]
from pyproj import Transformer  # pyright: ignore[reportMissingImports]
from shapely import transform
from shapely.errors import GEOSException
from shapely.geometry import LineString

_TO_BNG = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
_TO_WGS84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)

_RUNTIME_EDGE_FIELDS = {
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
    "lock_points",
}


def _kind_value(kind: object) -> object:
    return getattr(kind, "value", kind)


def _values(value: object) -> tuple:
    if value is None:
        return ()
    if isinstance(value, (tuple, list)):
        return tuple(value)
    if isinstance(value, set):
        return tuple(sorted(value, key=repr))
    return (value,)


def _bridge_ids(value: object) -> tuple[str, ...]:
    return tuple(sorted({str(item) for item in _values(value)}))


def _coordinate_values(value: object) -> tuple:
    return tuple(
        tuple(item) if isinstance(item, (tuple, list)) else item for item in _values(value)
    )


def _dimensions_signature(value: object) -> tuple | None:
    if value is None:
        return None
    names = ("max_beam_m", "max_length_m", "max_draft_m", "max_height_m")
    if isinstance(value, Mapping):
        return tuple(value.get(name) for name in names)
    return tuple(getattr(value, name, None) for name in names)


def _candidate_eligible(data: Mapping[str, object]) -> bool:
    """Return the persisted candidate policy for a detailed edge."""
    return not (
        bool(data.get("locks", 0))
        or _kind_value(data.get("kind")) == WaterwayKind.LOCK.value
        or bool(data.get("has_movable_bridge"))
        or bool(_bridge_ids(data.get("movable_bridge_ids")))
    )


def _edge_signature(data: Mapping[str, object]) -> tuple:
    """Return the complete runtime boundary signature, excluding geometry and length."""
    return (
        data.get("osm_way_id"),
        data.get("name"),
        _kind_value(data.get("kind")),
        _dimensions_signature(data.get("dimensions")),
        bool(data.get("has_tunnel")),
        _values(data.get("tunnel_restrictions")),
        bool(data.get("has_movable_bridge")),
        _bridge_ids(data.get("movable_bridge_ids")),
        int(cast(Any, data.get("locks", 0))),
        _coordinate_values(data.get("lock_points")),
        _values(data.get("access_caveats")),
        _candidate_eligible(data),
    )


def _discrete_edge(data: Mapping[str, object]) -> bool:
    return not _candidate_eligible(data)


def _protected_nodes(graph: nx.Graph) -> set[int]:
    protected: set[int] = set()
    for uid, data in graph.nodes(data=True):
        if graph.degree[uid] != 2:
            protected.add(uid)
        if data.get("name"):
            protected.add(uid)
        if _bridge_ids(data.get("movable_bridge_ids")):
            protected.add(uid)
        if data.get("turning_point"):
            protected.add(uid)

    for u, v, data in graph.edges(data=True):
        if _discrete_edge(data):
            protected.update((u, v))

    for uid in graph.nodes:
        if graph.degree[uid] != 2:
            continue
        neighbours = tuple(graph.neighbors(uid))
        if len(neighbours) != 2:
            protected.add(uid)
            continue
        first, second = (graph.edges[uid, neighbour] for neighbour in neighbours)
        if _edge_signature(first) != _edge_signature(second):
            protected.add(uid)
    return protected


def _edge_key(u: int, v: int) -> tuple[int, int]:
    return (u, v) if u <= v else (v, u)


def _canonical_path(path: tuple[int, ...]) -> tuple[int, ...]:
    return path if path[0] <= path[-1] else tuple(reversed(path))


def _chain_paths(graph: nx.Graph, protected: set[int]) -> list[tuple[int, ...]]:
    visited: set[tuple[int, int]] = set()
    chains: list[tuple[int, ...]] = []

    for start in sorted(protected):
        for neighbour in sorted(graph.neighbors(start)):
            edge_key = _edge_key(start, neighbour)
            if edge_key in visited:
                continue
            visited.add(edge_key)
            path = [start, neighbour]
            previous, current = start, neighbour
            while current not in protected and graph.degree[current] == 2:
                next_nodes = [uid for uid in graph.neighbors(current) if uid != previous]
                if len(next_nodes) != 1:
                    break
                next_node = next_nodes[0]
                next_key = _edge_key(current, next_node)
                if next_key in visited:
                    break
                visited.add(next_key)
                path.append(next_node)
                previous, current = current, next_node
            chains.append(tuple(path))

    # A component with no protected node is a cycle. Keeping its source edges is
    # the smallest safe representation that cannot invent a self-loop or a second edge.
    for u, v in graph.edges:
        edge_key = _edge_key(u, v)
        if edge_key not in visited:
            visited.add(edge_key)
            chains.append((u, v))
    return chains


def _same_coordinate(first: tuple[float, float], second: tuple[float, float]) -> bool:
    return first == second or _node_key(*first) == _node_key(*second)


def _assembled_geometry(graph: nx.Graph, path: tuple[int, ...]) -> list[tuple[float, float]]:
    assembled: list[tuple[float, float]] = []
    for u, v in zip(path, path[1:], strict=False):
        raw_geometry = graph.edges[u, v].get("geometry")
        if not isinstance(raw_geometry, (tuple, list)) or len(raw_geometry) < 2:
            raise ValueError(f"edge {(u, v)!r} has invalid geometry")
        segment = [tuple(point) for point in raw_geometry]
        if any(len(point) != 2 for point in segment):
            raise ValueError(f"edge {(u, v)!r} has invalid geometry")
        start = (graph.nodes[u]["lat"], graph.nodes[u]["lon"])
        end = (graph.nodes[v]["lat"], graph.nodes[v]["lon"])
        if _same_coordinate(segment[0], start):
            pass
        elif _same_coordinate(segment[-1], start):
            segment.reverse()
        else:
            raise ValueError(f"edge {(u, v)!r} geometry does not meet node {u!r}")
        if not _same_coordinate(segment[-1], end):
            raise ValueError(f"edge {(u, v)!r} geometry does not meet node {v!r}")
        if assembled and not _same_coordinate(assembled[-1], segment[0]):
            raise ValueError(f"chain {path!r} has a discontinuous join at node {u!r}")
        if assembled:
            assembled.extend(segment[1:])
        else:
            assembled.extend(segment)
    if not assembled:
        raise ValueError(f"chain {path!r} has no geometry")
    first_node = (graph.nodes[path[0]]["lat"], graph.nodes[path[0]]["lon"])
    last_node = (graph.nodes[path[-1]]["lat"], graph.nodes[path[-1]]["lon"])
    if not _same_coordinate(assembled[0], first_node):
        raise ValueError(f"chain {path!r} geometry does not meet node {path[0]!r}")
    if not _same_coordinate(assembled[-1], last_node):
        raise ValueError(f"chain {path!r} geometry does not meet node {path[-1]!r}")
    return assembled


def _simplified_geometry(
    source_geometry: list[tuple[float, float]], tolerance_m: float
) -> list[tuple[float, float]]:
    try:
        source = LineString([(lon, lat) for lat, lon in source_geometry])
        if source.is_empty or not source.is_valid or source.length == 0:
            raise ValueError("source geometry is empty or invalid")
        source_bng = transform(source, cast(Any, _TO_BNG.transform), interleaved=False)
        simplified_bng = source_bng.simplify(tolerance_m, preserve_topology=False)
        if (
            simplified_bng.is_empty
            or not simplified_bng.is_valid
            or simplified_bng.geom_type != "LineString"
            or len(simplified_bng.coords) < 2
        ):
            raise ValueError("simplified geometry is empty or invalid")
        simplified_coords = list(simplified_bng.coords)
        simplified_coords[0] = source_bng.coords[0]
        simplified_coords[-1] = source_bng.coords[-1]
        result_bng = LineString(simplified_coords)
        deviation_m = max(
            float(source_bng.hausdorff_distance(result_bng)),
            float(result_bng.hausdorff_distance(source_bng)),
        )
        if not math.isfinite(deviation_m) or deviation_m > tolerance_m + 1e-9:
            raise ValueError(f"simplified geometry exceeds {tolerance_m} m ({deviation_m} m)")
        result_wgs84 = transform(result_bng, cast(Any, _TO_WGS84.transform), interleaved=False)
        result = [(float(y), float(x)) for x, y in result_wgs84.coords]
        result[0] = cast(tuple[float, float], tuple(source_geometry[0]))
        result[-1] = cast(tuple[float, float], tuple(source_geometry[-1]))
        return result
    except ValueError:
        raise
    except (GEOSException, TypeError, OverflowError) as exc:
        raise ValueError("could not simplify edge geometry") from exc


def _runtime_node_data(data: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {
        "lat": data["lat"],
        "lon": data["lon"],
        "movable_bridge_ids": _bridge_ids(data.get("movable_bridge_ids")),
        "turning_point": bool(data.get("turning_point")),
        "turning_max_length_m": data.get("turning_max_length_m"),
    }
    if data.get("name"):
        result["name"] = data["name"]
    return result


def _emit_chain(
    compact: nx.Graph,
    source: nx.Graph,
    path: tuple[int, ...],
    tolerance_m: float,
) -> None:
    path = _canonical_path(path)
    if len(path) < 2 or path[0] == path[-1]:
        raise ValueError(f"cannot contract chain {path!r}")
    source_geometry = _assembled_geometry(source, path)
    edge_data = source.edges[path[0], path[1]]
    attrs = {
        key: copy.deepcopy(value) for key, value in edge_data.items() if key in _RUNTIME_EDGE_FIELDS
    }
    attrs["length_m"] = sum(
        float(source.edges[u, v]["length_m"]) for u, v in zip(path, path[1:], strict=False)
    )
    attrs["geometry"] = _simplified_geometry(source_geometry, tolerance_m)
    attrs["movable_bridge_ids"] = _bridge_ids(attrs.get("movable_bridge_ids"))
    attrs["candidate_eligible"] = _candidate_eligible(attrs)
    low, high = _edge_key(path[0], path[-1])
    if compact.has_edge(low, high):
        raise ValueError(f"compaction would create a second edge between {(low, high)!r}")
    compact.add_edge(low, high, **attrs)


def _emit_chain_group(
    compact: nx.Graph,
    source: nx.Graph,
    paths: list[tuple[int, ...]],
    tolerance_m: float,
) -> None:
    ordered = sorted((_canonical_path(path) for path in paths), key=lambda path: (len(path), path))
    _emit_chain(compact, source, ordered[0], tolerance_m)
    for path in ordered[1:]:
        anchor = min(path[1:-1], default=None)
        if anchor is not None:
            compact.add_node(anchor, **_runtime_node_data(source.nodes[anchor]))
        if anchor is None:
            _emit_chain(compact, source, path, tolerance_m)
            continue
        index = path.index(anchor)
        _emit_chain(compact, source, path[: index + 1], tolerance_m)
        _emit_chain(compact, source, path[index:], tolerance_m)


def compact_graph(graph: nx.Graph, *, tolerance_m: float = 1.0) -> nx.Graph:
    """Contract detailed degree-two chains into a deterministic runtime graph."""
    if not isinstance(graph, nx.Graph) or graph.is_directed() or graph.is_multigraph():
        raise TypeError("expected an undirected networkx.Graph")
    if (
        isinstance(tolerance_m, bool)
        or not isinstance(tolerance_m, (int, float))
        or not math.isfinite(tolerance_m)
        or tolerance_m < 0
    ):
        raise ValueError("tolerance_m must be a finite nonnegative number")

    protected = _protected_nodes(graph)
    chains = _chain_paths(graph, protected)
    grouped: dict[tuple[int, int], list[tuple[int, ...]]] = {}
    for path in chains:
        low, high = _edge_key(path[0], path[-1])
        if low == high:
            # This should only arise from malformed cyclic input; retaining every
            # source edge avoids manufacturing a self-loop.
            for u, v in zip(path, path[1:], strict=False):
                grouped.setdefault(_edge_key(u, v), []).append((u, v))
        else:
            grouped.setdefault((low, high), []).append(path)

    compact = nx.Graph()
    retained_nodes = set(protected)
    for paths in grouped.values():
        retained_nodes.update((paths[0][0], paths[0][-1]))
    for uid in sorted(retained_nodes):
        compact.add_node(uid, **_runtime_node_data(graph.nodes[uid]))

    for endpoints in sorted(grouped):
        paths = grouped[endpoints]
        for path in sorted(_canonical_path(item) for item in paths):
            if path[0] not in compact or path[-1] not in compact:
                compact.add_node(path[0], **_runtime_node_data(graph.nodes[path[0]]))
                compact.add_node(path[-1], **_runtime_node_data(graph.nodes[path[-1]]))
        # Each ordinary group is emitted as one direct chain plus anchored alternatives.
        for path in paths[1:]:
            canonical = _canonical_path(path)
            anchor = min(canonical[1:-1], default=None)
            if anchor is not None:
                compact.add_node(anchor, **_runtime_node_data(graph.nodes[anchor]))
        _emit_chain_group(compact, graph, paths, float(tolerance_m))

    return compact
