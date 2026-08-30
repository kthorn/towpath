"""Attach lock counts to graph edges (design §4.2, §3.1, OQ-A Model D).

Lock semantics (flight-level chamber model, OQ-A decision 2026-07-03):
A FLIGHT is a connected component of LOCK ways chained by shared endpoints.
chambers = max(1, G-1) where G = count of DISTINCT gate nodes (lock_gate or
lock=yes) referenced along the flight's ways — shared/adjacent gates counted
once. Attribution: for each chamber whose downstream boundary is a gate node,
set locks=1 on the segment edge whose downstream endpoint IS that gate (you
bill the chamber on exiting through its downstream gate; direction-insensitive).
A gateless flight (G<2) floors to 1 lock on its first segment edge.
"""

import copy
import math

import networkx as nx
from pyproj import Transformer
from shapely import transform
from shapely.geometry import LineString, Point

from pound.ingest.ir import NodeKind, WaterwayFeatures, WaterwayKind

LOCK_SOURCE_TOLERANCE_M = 25.0
_TO_BNG = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
_TO_WGS84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)


def project_point_to_edge(
    edge_geom: object, lat: object, lon: object
) -> tuple[tuple[float, float], float] | None:
    """Project a finite WGS84 source point onto an edge line and return metric distance."""
    if (
        isinstance(lat, bool)
        or isinstance(lon, bool)
        or not isinstance(lat, (int, float))
        or not isinstance(lon, (int, float))
        or not isinstance(edge_geom, (tuple, list))
    ):
        return None
    try:
        source_lat = float(lat)
        source_lon = float(lon)
        if not math.isfinite(source_lat) or not math.isfinite(source_lon):
            return None
        coordinates = []
        for point in edge_geom:
            if not isinstance(point, (tuple, list)) or len(point) != 2:
                return None
            point_lat, point_lon = point
            if (
                isinstance(point_lat, bool)
                or isinstance(point_lon, bool)
                or not isinstance(point_lat, (int, float))
                or not isinstance(point_lon, (int, float))
            ):
                return None
            point_lat = float(point_lat)
            point_lon = float(point_lon)
            if not math.isfinite(point_lat) or not math.isfinite(point_lon):
                return None
            coordinates.append((point_lon, point_lat))
        if len(coordinates) < 2:
            return None
        edge = transform(LineString(coordinates), _TO_BNG.transform, interleaved=False)
        source = Point(*_TO_BNG.transform(source_lon, source_lat))
        if edge.is_empty or edge.length == 0:
            return None
        distance_m = float(source.distance(edge))
        projected = edge.interpolate(edge.project(source))
        if distance_m <= 1e-6:
            return (source_lat, source_lon), distance_m
        projected_wgs84 = transform(projected, _TO_WGS84.transform, interleaved=False)
        return (float(projected_wgs84.y), float(projected_wgs84.x)), distance_m
    except (TypeError, ValueError, RuntimeError, OverflowError):
        return None


def attach_locks(
    graph: nx.Graph,
    features: WaterwayFeatures,
    tolerance_m: float = LOCK_SOURCE_TOLERANCE_M,
    *,
    in_place: bool = False,
) -> tuple[nx.Graph, dict]:
    g = graph if in_place else copy.deepcopy(graph)
    report = {
        "lock_ways_attached": 0,
        "lock_nodes_attached": 0,
        "orphan_lock_ways": [],
        "orphan_lock_nodes": [],
        "lock_gate_nodes": 0,
    }

    # --- Lock ways: flight-level chamber attribution (Model D + iii) --------
    # A FLIGHT is a connected component of LOCK ways chained by shared endpoints
    # (linear; England has zero branch endpoints). chambers = max(1, G-1) where
    # G = count of DISTINCT gate nodes (lock_gate or lock=yes) referenced along
    # the flight's ways — shared/adjacent gates counted once. "Three gates in a
    # row -> two chambers"; one chamber's exit gate being the next's entrance
    # (a gate node referenced by two ways) is counted once, not twice.
    # Attribution: for each chamber whose downstream boundary is a gate node, set
    # locks=1 on the segment edge whose downstream endpoint IS that gate (you
    # bill the chamber on exiting through its downstream gate; direction-
    # insensitive — routes in either direction read the one locks attr). A
    # gateless flight (G<2, gates not mapped) floors to 1 lock on its first
    # segment edge by (osm_way_id, segment index) order.
    gate_points = {
        n.osm_id: (n.lat, n.lon)
        for n in features.nodes
        if n.kind in (NodeKind.LOCK_GATE, NodeKind.LOCK)
    }
    gate_ids = set(gate_points)
    lock_ways = [w for w in features.ways if w.kind == WaterwayKind.LOCK]
    # Build adjacency by shared OSM node-id endpoint, then find flights (CCs).
    endpoint_ways: dict[int, set[int]] = {}
    for w in lock_ways:
        if not w.node_ids:
            continue
        for ref in (w.node_ids[0], w.node_ids[-1]):
            endpoint_ways.setdefault(ref, set()).add(w.osm_id)
    seen_way_ids: set[int] = set()
    flights: list[list[int]] = []  # each flight is a list of osm_way_ids
    for w in lock_ways:
        if w.osm_id in seen_way_ids or not w.node_ids:
            continue
        stack = [w.osm_id]
        seen_way_ids.add(w.osm_id)
        comp: list[int] = []
        while stack:
            wid = stack.pop()
            comp.append(wid)
            way = next(x for x in lock_ways if x.osm_id == wid)
            for ref in (way.node_ids[0], way.node_ids[-1]):
                for nb in endpoint_ways.get(ref, set()):
                    if nb not in seen_way_ids:
                        seen_way_ids.add(nb)
                        stack.append(nb)
        flights.append(comp)
    # id-less lock ways (Overpass dev path): each is its own flight.
    for w in lock_ways:
        if not w.node_ids and w.osm_id not in seen_way_ids:
            seen_way_ids.add(w.osm_id)
            flights.append([w.osm_id])

    # Index segment edges by osm_way_id.
    way_edges: dict[int, list[tuple[object, object, dict]]] = {}
    for u, v, d in g.edges(data=True):
        wid = d.get("osm_way_id")
        if wid is not None:
            way_edges.setdefault(wid, []).append((u, v, d))

    for flight in flights:
        # Collect this flight's ways in flight order, and their segment edges in
        # node order. For each way, sort its edges by segment index (the position
        # of the downstream node in the way's node_ids).
        flight_ways = [next(x for x in lock_ways if x.osm_id == wid) for wid in flight]
        # Per-way ordered segments: list of (way, u, v, d, downstream_ref)
        way_segments: list[tuple] = []
        for w in flight_ways:
            edges = list(way_edges.get(w.osm_id, []))
            if not edges or not w.node_ids:
                continue

            # Map each edge to its segment index via the downstream node's
            # osm_node_ids (the downstream node of segment i is node_ids[i+1]).
            def _seg_idx(edge, _w=w):
                u, v, d = edge
                v_ids = g.nodes[v].get("osm_node_ids", set())
                u_ids = g.nodes[u].get("osm_node_ids", set())
                downstream_ids = v_ids | u_ids
                idxs = [i + 1 for i, ref in enumerate(_w.node_ids) if str(ref) in downstream_ids]
                return min(idxs) if idxs else 0

            edges.sort(key=_seg_idx)
            for i, (u, v, d) in enumerate(edges):
                # downstream ref is node_ids[i+1] in the way's ordering.
                down_ref = w.node_ids[i + 1] if i + 1 < len(w.node_ids) else None
                way_segments.append((w, u, v, d, down_ref))
        # Set locks=1 on each segment whose downstream ref is a gate.
        lock_segments = []
        for w, u, v, d, down_ref in way_segments:
            if down_ref is not None and down_ref in gate_ids:
                d["locks"] = max(d.get("locks", 0), 1)
                lock_points = d.setdefault("lock_points", [])
                projection = project_point_to_edge(d.get("geometry", []), *gate_points[down_ref])
                if projection is not None and projection[1] <= tolerance_m:
                    point = projection[0]
                    if point not in lock_points:
                        lock_points.append(point)
                lock_segments.append((w.osm_id, u, v, d))
        # Floor: gateless flight -> 1 lock on the first segment of the first way.
        if not lock_segments and way_segments:
            w0, u0, v0, d0, _ = way_segments[0]
            d0["locks"] = max(d0.get("locks", 0), 1)
            d0.setdefault("lock_points", [])
            lock_segments.append((w0.osm_id, u0, v0, d0))
        # report: one lock_way_attached per flight way that has >=1 matched edge.
        attached_ways = {wid for wid, _, _, _ in lock_segments}
        for w in flight_ways:
            if w.osm_id in attached_ways:
                report["lock_ways_attached"] += 1
            else:
                report["orphan_lock_ways"].append(w.osm_id)

    # --- Lock nodes: nearest-edge attach with LOCK tie-break (§3.5) --------
    # snap to the nearest edge within tolerance, breaking ties by kind==LOCK
    # preferred, then shorter segment, then first-seen. A gate node that is
    # itself an OSM node of two coincident edges (a LOCK chamber and a canal spur
    # sharing the junction) is distance 0 to both; without the kind tie-break,
    # insertion order would decide and a coincident canal spur could spuriously
    # win locks=1.
    for node in features.nodes:
        if node.kind == NodeKind.LOCK_GATE:
            report["lock_gate_nodes"] += 1
            continue  # gates don't increment lock count
        if node.kind != NodeKind.LOCK:
            continue
        best_edge = None
        best_key = None
        for u, v, d in g.edges(data=True):
            projection = project_point_to_edge(d.get("geometry", []), node.lat, node.lon)
            if projection is None or projection[1] > tolerance_m:
                continue
            dist = projection[1]
            is_lock = d.get("kind") == WaterwayKind.LOCK
            key = (dist, 0 if is_lock else 1, d.get("length_m", math.inf))
            if best_key is None or key < best_key:
                best_key = key
                best_edge = (u, v, d, projection[0])
        if best_edge is not None:
            edge_data = best_edge[2]
            edge_data["locks"] = max(edge_data.get("locks", 0), 1)
            lock_points = edge_data.setdefault("lock_points", [])
            point = best_edge[3]
            if point not in lock_points:
                lock_points.append(point)
            report["lock_nodes_attached"] += 1
        else:
            report["orphan_lock_nodes"].append(node.osm_id)

    return g, report
