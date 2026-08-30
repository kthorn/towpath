"""WaterwayFeatures -> noded NetworkX graph (noded build, design §3.2-§3.5).

Every OSM node id along a routable way becomes a graph node; consecutive ids
become edges with per-segment haversine length and inherited way-level attrs.
Junctions collapse at emission via two cooperating indexes (OSM-id and
rounded-coordinate), so shared junctions — by OSM id, by coordinate, or both,
endpoint or internal — join for free, with NO contraction phase, NO
tolerance-snap pass, and NO overrides/curation. Closed-ring ways (first coord
== last) are area polygons, never routable, and are skipped.

Node keys are synthetic internal uids (a monotonic counter); lat/lon and
osm_node_ids (set of stringified OSM ids) are node attributes. id-less dev
ways (Overpass `out geom`) resolve-or-create via the coordinate index alone.
Edge collision (two ways producing the same node pair) merges attributes
(kind by specificity, dimensions union-tightened, name first non-None,
tunnel/movable-bridge OR-ed; on a LOCK-involving collision the merged edge
keeps the LOCK way's osm_way_id and gets locks=1 immediately).
"""

import itertools
import math

import networkx as nx

from pound.graph.locks import LOCK_SOURCE_TOLERANCE_M, project_point_to_edge
from pound.ingest.filters import extract_access_caveats, extract_dimensions
from pound.ingest.ir import NodeKind, WaterwayFeatures, WaterwayKind, WayDimensions

_ROUND = 7
_ROUTABLE = {WaterwayKind.CANAL, WaterwayKind.RIVER, WaterwayKind.FAIRWAY, WaterwayKind.LOCK}
# Edge-collision kind specificity (§3.3): LOCK > CANAL > RIVER > FAIRWAY.
# Calder-and-Hebble river-vs-canal dual-classification prefers CANAL (the
# stronger navigability signal for this project).
_KIND_RANK = {
    WaterwayKind.LOCK: 3,
    WaterwayKind.CANAL: 2,
    WaterwayKind.RIVER: 1,
    WaterwayKind.FAIRWAY: 0,
}


def _node_key(lat: float, lon: float) -> tuple[float, float]:
    return (round(lat, _ROUND), round(lon, _ROUND))


def _haversine_m(a, b) -> float:
    r = 6_371_000.0
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _min_nonnone(x: float | None, y: float | None) -> float | None:
    if x is None:
        return y
    if y is None:
        return x
    return min(x, y)


def _merge_dims(a: WayDimensions | None, b: WayDimensions | None) -> WayDimensions | None:
    if a is None:
        return b
    if b is None:
        return a
    return WayDimensions(
        max_beam_m=_min_nonnone(a.max_beam_m, b.max_beam_m),
        max_length_m=_min_nonnone(a.max_length_m, b.max_length_m),
        max_draft_m=_min_nonnone(a.max_draft_m, b.max_draft_m),
        max_height_m=_min_nonnone(a.max_height_m, b.max_height_m),
    )


def _sorted_union(existing: tuple, incoming: tuple) -> tuple:
    return tuple(sorted(set(existing) | set(incoming)))


def _tunnel_restrictions(way) -> tuple[tuple[int, str, str], ...]:
    if not way.has_tunnel:
        return ()
    pairs: set[tuple[int, str, str]] = set()
    for key, value in way.tags.items():
        if (
            (key in {"oneway", "oneway:boat"} and value != "no")
            or (key == "opening_hours" and value)
            or (key in {"access", "boat"} and value != "yes")
            or (key.endswith(":conditional") and value)
            or (key == "restriction" or key.startswith("restriction:"))
        ):
            pairs.add((way.osm_id, key, value))
    return tuple(sorted(pairs))


def build_graph(features: WaterwayFeatures) -> nx.Graph:
    """Build a noded graph from WaterwayFeatures keyed by synthetic internal uids.

    Every OSM node id on a routable way is a graph node keyed by a monotonic
    internal id (source-agnostic: survives OSM-id aliasing at one coord and
    future synthetic curator nodes). lat/lon and osm_node_ids are node attrs.
    Junctions collapse at emission via the osm-id and coordinate indexes.
    """
    g = nx.Graph()
    uid_counter = itertools.count()
    osm_idx: dict[str, int] = {}  # str(osm id) -> uid
    coord_idx: dict[tuple, int] = {}  # rounded coord -> uid

    def _resolve_or_create(osm_id, lat, lon):
        sid = str(osm_id) if osm_id is not None else None
        coord = _node_key(lat, lon)
        uid = None
        if sid is not None and sid in osm_idx:
            uid = osm_idx[sid]
        if uid is None and coord in coord_idx:
            uid = coord_idx[coord]
        if uid is None:
            uid = next(uid_counter)
            g.add_node(
                uid,
                lat=coord[0],
                lon=coord[1],
                osm_node_ids=set(),
                movable_bridge_ids=(),
                turning_point=False,
                turning_max_length_m=None,
            )
            coord_idx[coord] = uid
        if sid is not None:
            osm_idx[sid] = uid
            coord_idx.setdefault(coord, uid)
            g.nodes[uid]["osm_node_ids"].add(sid)
        return uid

    def _merge_edge(
        u, v, way, length_m, seg_geom, movable_bridge_ids, tunnel_restrictions, access_caveats
    ):
        d = g[u][v]
        existed_lock = d["kind"] == WaterwayKind.LOCK
        new_lock = way.kind == WaterwayKind.LOCK
        # kind: more-specific wins (LOCK>CANAL>RIVER>FAIRWAY; CANAL>RIVER for the
        # dual-classified case).
        if _KIND_RANK[way.kind] > _KIND_RANK[d["kind"]]:
            d["kind"] = way.kind
        # osm_way_id: keep the LOCK way's id when exactly one party is LOCK
        # (so attach_locks finds the merged LOCK edge by osm_way_id); else keep
        # the existing (first-emitted) id.
        if new_lock and not existed_lock:
            d["osm_way_id"] = way.osm_id
        # dimensions: union-tighten (min non-None per axis).
        d["dimensions"] = _merge_dims(d["dimensions"], way.dimensions)
        # name: keep first non-None.
        if d.get("name") is None and way.name is not None:
            d["name"] = way.name
        # tunnel / movable bridge: logical OR.
        d["has_tunnel"] = bool(d.get("has_tunnel") or way.has_tunnel)
        d["has_movable_bridge"] = bool(d.get("has_movable_bridge") or way.has_movable_bridge)
        d["movable_bridge_ids"] = _sorted_union(d["movable_bridge_ids"], movable_bridge_ids)
        d["tunnel_restrictions"] = _sorted_union(d["tunnel_restrictions"], tunnel_restrictions)
        # length_m: coincident endpoints => equal by construction; keep existing.
        # locks: a LOCK-involving collision sets max(existing, 1) at merge time.
        if existed_lock or new_lock:
            d["locks"] = max(d.get("locks", 0), 1)
        # geometry: keep the existing 2-point segment (coincident by construction).
        d["access_caveats"] = tuple(sorted(set(d["access_caveats"]) | set(access_caveats)))

    for way in features.ways:
        if way.kind not in _ROUTABLE:
            continue
        if len(way.geometry) < 2:
            continue
        # Closed-ring way: an area polygon (lock-chamber outline, basin, wetland,
        # water body), never a routable edge. A navigable ring is a graph cycle
        # of DISTINCT linear ways, not one closed way. Skipping keeps the
        # self_loops==0 gate honest and drops no routable geometry.
        if _node_key(*way.geometry[0]) == _node_key(*way.geometry[-1]):
            continue
        # resolve-or-create one graph node per OSM node id (id-less ways: per coord)
        uids = [
            _resolve_or_create(
                way.node_ids[i] if way.node_ids else None,
                way.geometry[i][0],
                way.geometry[i][1],
            )
            for i in range(len(way.geometry))
        ]
        access_caveats = extract_access_caveats(way.osm_id, way.tags)
        emittable_indexes = [i for i in range(len(uids) - 1) if uids[i] != uids[i + 1]]
        bridge_segment_index = None
        if way.has_movable_bridge and emittable_indexes:
            has_matching_bridge_node = False
            for node in features.nodes:
                if node.kind != NodeKind.MOVABLE_BRIDGE:
                    continue
                if node.osm_id in way.node_ids:
                    has_matching_bridge_node = True
                    break
                for source_index in range(len(way.geometry) - 1):
                    projection = project_point_to_edge(
                        [way.geometry[source_index], way.geometry[source_index + 1]],
                        node.lat,
                        node.lon,
                    )
                    if projection is not None and projection[1] <= LOCK_SOURCE_TOLERANCE_M:
                        has_matching_bridge_node = True
                        break
                if has_matching_bridge_node:
                    break
            if not has_matching_bridge_node:
                bridge_segment_index = emittable_indexes[(len(emittable_indexes) - 1) // 2]
        tunnel_restrictions = _tunnel_restrictions(way)
        for i in emittable_indexes:
            u, v = uids[i], uids[i + 1]
            length_m = _haversine_m(way.geometry[i], way.geometry[i + 1])
            seg_geom = [way.geometry[i], way.geometry[i + 1]]
            movable_bridge_ids = (f"way:{way.osm_id}",) if i == bridge_segment_index else ()
            if g.has_edge(u, v):
                _merge_edge(
                    u,
                    v,
                    way,
                    length_m,
                    seg_geom,
                    movable_bridge_ids,
                    tunnel_restrictions,
                    access_caveats,
                )
            else:
                g.add_edge(
                    u,
                    v,
                    osm_way_id=way.osm_id,
                    name=way.name,
                    kind=way.kind,
                    length_m=length_m,
                    dimensions=way.dimensions,
                    has_tunnel=way.has_tunnel,
                    has_movable_bridge=way.has_movable_bridge,
                    locks=0,
                    geometry=seg_geom,
                    movable_bridge_ids=movable_bridge_ids,
                    tunnel_restrictions=tunnel_restrictions,
                    access_caveats=access_caveats,
                )

    for node in features.nodes:
        if node.kind != NodeKind.TURNING_POINT:
            continue
        uid = osm_idx.get(str(node.osm_id))
        if uid is None:
            uid = coord_idx.get(_node_key(node.lat, node.lon))
        if uid is None:
            continue
        data = g.nodes[uid]
        data["turning_point"] = True
        maximum = extract_dimensions(node.tags).max_length_m
        data["turning_max_length_m"] = _min_nonnone(data["turning_max_length_m"], maximum)

    for node in features.nodes:
        if node.kind != NodeKind.MOVABLE_BRIDGE:
            continue
        bridge_id = f"node:{node.osm_id}"
        node_coord = _node_key(node.lat, node.lon)
        matched_uid = next(
            (
                uid
                for uid, data in g.nodes(data=True)
                if str(node.osm_id) in data["osm_node_ids"]
                or _node_key(data["lat"], data["lon"]) == node_coord
            ),
            None,
        )
        if matched_uid is not None:
            data = g.nodes[matched_uid]
            data["movable_bridge_ids"] = _sorted_union(data["movable_bridge_ids"], (bridge_id,))
            continue
        best_edge = None
        best_key = None
        for u, v, edge_data in g.edges(data=True):
            projection = project_point_to_edge(edge_data["geometry"], node.lat, node.lon)
            if projection is None or projection[1] > LOCK_SOURCE_TOLERANCE_M:
                continue
            key = (projection[1], edge_data["length_m"], *sorted((u, v)))
            if best_key is None or key < best_key:
                best_key = key
                best_edge = edge_data
        if best_edge is not None:
            best_edge["movable_bridge_ids"] = _sorted_union(
                best_edge["movable_bridge_ids"], (bridge_id,)
            )
    return g
