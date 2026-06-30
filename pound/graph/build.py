"""WaterwayFeatures -> noded NetworkX graph (design §4.2, Scope D OQ-D2).

THREE join phases, in order:

  1. NODE-REF AUTHORITY — two ways sharing an OSM node id at an endpoint are
     joined (the keys collapse to one), even if their coords differ slightly.
     Only applies when `WaterwayWay.node_ids` is populated (the pyosmium bulk
     reader fills it; the Overpass `out geom` reader leaves it empty).
  2. EXACT-COORDINATE AUTHORITY — two way-ends rounding to the same
     `_node_key` (7-decimal ≈ 11 mm coordinate) are the SAME graph node by
     construction. Works on hand-curated fixtures AND on Overpass-sourced
     features with no `node_ids`. This is the Scope C behaviour, preserved as a
     co-primary authority (NOT demoted to a snap candidate — see plan OQ-1).
  3. TOLERANCE-SNAP CANDIDATES — for each *dangling tip* (a graph node
     incident to exactly one edge, i.e. a way-end still unjoined to any
     neighbor after both authorities), the **nearest other graph node**
     (excluding the tip's sole neighbor) within `0 < distance <= tolerance_m`
     is a snap *candidate*. The other node may itself be a tip (a gap between
     two chain-ends) OR an already-connected junction (a spur that should tie
     into the main line but the OSM edit missed the node — the common
     real-world gap pattern). Two adjacent junctions near each other are
     correctly NOT candidates, since neither is a tip — that proximity is not
     a gap (parallel canals, a both-sides-connected aqueduct). A candidate is a
     *candidate generator, not an authority* (R3): false joins at aqueducts
     cannot be self-resolved, so candidates are reported
     (`graph.graph["tolerance_snaps_used"]` / ["tolerance_snaps_unresolved"])
     for manual curation via `pound/data/overrides.json`. A `split` override
     suppresses a candidate; a `join` override confirms (resolves) a built
     candidate and also bridges genuine beyond-tolerance gaps. A candidate
     that would duplicate an existing edge between already-adjacent nodes is
     recorded unresolved, not built.

Node key is `_node_key(lat, lon)` (rounded) — unchanged from Scope C. OSM node
ids are stored per graph node (`osm_node_ids`) for override resolution, but
are NOT the graph key. Empty `node_ids` is safe (Overpass path): only phase 1
is skipped for such ways; phases 2 and 3 still apply.
"""

import json
import math
from pathlib import Path

import networkx as nx

from pound.ingest.ir import WaterwayFeatures, WaterwayKind

_ROUND = 7
_ROUTABLE = {WaterwayKind.CANAL, WaterwayKind.RIVER, WaterwayKind.FAIRWAY, WaterwayKind.LOCK}


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


def load_overrides(path: Path) -> dict:
    """Parse pound/data/overrides.json into {"join": [...], "split": [...]}.

    join  : list of [node_id_a, node_id_b] (stringified in the dict) -> connect.
    split : list of [way_id_a,  way_id_b ]                            -> suppress a snap.
    Missing file => empty overrides. Malformed JSON or unknown top-level keys
    raise ValueError (loud failure — never a silent fallback).
    """
    path = Path(path)
    if not path.exists():
        return {"join": [], "split": []}
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"overrides.json: invalid JSON: {exc}") from exc
    if set(raw) - {"join", "split"}:
        raise ValueError(f"overrides.json: unknown keys {set(raw) - {'join', 'split'}}")
    return {
        "join": [tuple(str(x) for x in pair) for pair in raw.get("join", [])],
        "split": [tuple(str(x) for x in pair) for pair in raw.get("split", [])],
    }


def build_graph(
    features: WaterwayFeatures,
    *,
    tolerance_m: float = 10.0,
    overrides: dict | None = None,
) -> nx.Graph:
    """Build a noded graph from WaterwayFeatures with three-phase connectivity.

    See module docstring. `overrides` is the parsed dict from load_overrides.
    Safe to call with features whose `way.node_ids` are empty (Overpass path).
    """
    overrides = overrides or {"join": [], "split": []}
    join_pairs: set[tuple[str, str]] = {tuple(sorted(p)) for p in overrides["join"]}
    split_pairs: set[tuple[str, str]] = {tuple(sorted(p)) for p in overrides["split"]}
    overrides_applied = 0

    g = nx.Graph()
    g.graph["tolerance_snaps_used"] = []
    g.graph["tolerance_snaps_unresolved"] = []
    g.graph["overrides_applied"] = 0

    # --- Phase 1+2 emission: key every endpoint by _node_key(coord). Exact-coord
    # equality makes two ways sharing a rounded coord share a node for free
    # (phase 2). Record which OSM node ids map to each emitted key for the
    # node-ref authority (phase 1 unification) and for `join` overrides.
    id2keys: dict[str, set[tuple]] = {}  # osm node id (str) -> set of keys it appears at

    def _emit(key, osm_id):
        if key not in g:
            g.add_node(key, lat=key[0], lon=key[1], osm_node_ids=set())
        if osm_id is not None:
            # Store as string: load_overrides stringifies override ids, and
            # join/split resolution compares ids as strings (the common currency
            # for override lookup). Keeping osm_node_ids string-keyed too makes
            # _key_for_osm_id and join confirmation match consistently.
            sid = str(osm_id)
            g.nodes[key]["osm_node_ids"].add(sid)
            id2keys.setdefault(sid, set()).add(key)

    way_ends: list[tuple[int, tuple, tuple]] = []  # (osm_way_id, start_key, end_key)
    for way in features.ways:
        if way.kind not in _ROUTABLE:
            continue
        if len(way.geometry) < 2:
            continue
        a_raw = _node_key(*way.geometry[0])
        b_raw = _node_key(*way.geometry[-1])
        if a_raw == b_raw:
            # Closed-ring way (first == last coord): an area polygon — a
            # lock-chamber outline, basin, wetland, or water body — never a
            # routable edge. On real England data every closed ring is such an
            # area (locks, `natural=wetland` rivers, amusement rides, water
            # bodies); none is a navigable ring passage, because a navigable
            # ring trip is a graph cycle of distinct linear ways, not one
            # closed way. Skipping keeps the `self_loops == 0` gate honest
            # without an override and drops no routable geometry. A shared
            # coordinate still gets its node from any coincident linear way.
            continue
        a_osm = way.node_ids[0] if way.node_ids else None
        b_osm = way.node_ids[-1] if way.node_ids else None
        _emit(a_raw, a_osm)
        _emit(b_raw, b_osm)
        length_m = sum(
            _haversine_m(way.geometry[i], way.geometry[i + 1]) for i in range(len(way.geometry) - 1)
        )
        g.add_edge(
            a_raw,
            b_raw,
            osm_way_id=way.osm_id,
            name=way.name,
            kind=way.kind,
            length_m=length_m,
            dimensions=way.dimensions,
            has_tunnel=way.has_tunnel,
            has_movable_bridge=way.has_movable_bridge,
            locks=0,
            geometry=list(way.geometry),
        )
        way_ends.append((way.osm_id, a_raw, b_raw))

    # --- Phase 1 unification (node-ref authority): contract keys that share an
    # OSM node id into a single key. This joins ways whose shared node id sits
    # at *slightly* differing coords (well-noded but edited). Empty node_ids =>
    # no such ids => phase 1 is a no-op (phase 2 still joined exact-coord ends).
    snap_groups: list[set[tuple]] = []
    for keys in id2keys.values():
        if len(keys) > 1:
            snap_groups.append(set(keys))
    _contract(g, snap_groups, way_ends)

    # --- Phase 3: tolerance-snap candidates for dangling tips. A *tip* is a
    # graph node incident to exactly one edge (a way-end unjoined to any
    # neighbor after phases 1+2). For each tip, the nearest OTHER node
    # (excluding the tip's sole neighbor) within `0 < dist <= tolerance_m` is a
    # candidate. The other node may be a tip OR a connected junction (both are
    # real gap patterns). Two junctions near each other are NOT candidates.
    unresolved: list[tuple] = []
    used: list[tuple] = []

    def _incident_way_ids(key):
        return {d["osm_way_id"] for _, _, d in g.edges(key, data=True)}

    tips = [n for n in g.nodes() if g.degree(n) == 1]
    candidates: list[tuple[tuple, tuple, int, int]] = []  # (tip, target, tip_way, target_way)
    for tip in tips:
        nbr = next(iter(g[tip]))  # sole neighbor — never a snap target
        best, best_d, best_w = None, math.inf, -1
        for other in g.nodes():
            if other == tip or other == nbr:
                continue
            d = _haversine_m(tip, other)
            if d <= 0.0 or d > tolerance_m or d >= best_d:
                continue
            best, best_d, best_w = other, d, next(iter(_incident_way_ids(other)))
        if best is not None:
            candidates.append((tip, best, next(iter(_incident_way_ids(tip))), best_w))

    # Dedupe symmetric candidates (tip A's nearest is tip B, and vice versa).
    seen_pairs: set[tuple] = set()
    uniq = []
    for tip, target, wa, wb in candidates:
        pair = tuple(sorted((tip, target)))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        uniq.append((tip, target, wa, wb))

    for ka, kb, wa, wb in uniq:
        if tuple(sorted((str(wa), str(wb)))) in split_pairs:
            overrides_applied += 1
            continue  # suppressed -> neither built nor unresolved
        if g.has_edge(ka, kb):  # would duplicate an existing edge
            unresolved.append((ka, kb))
            continue
        # Build the snap by contracting the two keys into one.
        _contract(g, [{ka, kb}], [])
        used.append((ka, kb))
        survivor = ka if ka in g else kb
        ids = g.nodes[survivor].get("osm_node_ids", set())
        # A `join` override confirms the snap iff some (a,b) pair is entirely
        # inside the survivor's merged node-id set.
        confirmed = bool(ids) and any(ia in ids and ib in ids for ia, ib in join_pairs)
        if confirmed:
            overrides_applied += 1
        else:
            unresolved.append((ka, kb))

    # --- `join` overrides that did NOT arise from a candidate snap (genuine
    # beyond-tolerance gaps): connect their nodes directly.
    for a_id, b_id in overrides["join"]:
        ka = _key_for_osm_id(g, a_id)
        kb = _key_for_osm_id(g, b_id)
        if ka is None or kb is None or ka == kb or g.has_edge(ka, kb):
            continue
        dims_cls = type(features.ways[0].dimensions) if features.ways else None
        g.add_edge(
            ka,
            kb,
            osm_way_id=-1,
            name=None,
            kind=WaterwayKind.CANAL,
            length_m=_haversine_m(ka, kb),
            dimensions=dims_cls() if dims_cls else None,
            has_tunnel=False,
            has_movable_bridge=False,
            locks=0,
            geometry=[ka, kb],
        )
        overrides_applied += 1

    g.graph["tolerance_snaps_used"] = used
    g.graph["tolerance_snaps_unresolved"] = unresolved
    g.graph["overrides_applied"] = overrides_applied
    return g


def _contract(g: nx.Graph, groups: list[set[tuple]], way_ends: list) -> None:
    """Contract each group of keys into one representative (smallest by (lat,lon)),
    merging edges + osm_node_ids. Mutates `g` (and optionally rewrites way_ends
    in place so later phases see the contracted keys).
    """
    if not groups:
        return
    old_to_new: dict[tuple, tuple] = {}
    for group in groups:
        rep = min(group)
        for k in group:
            old_to_new[k] = rep
    for old in sorted(old_to_new, reverse=True):
        new = old_to_new[old]
        if old == new or old not in g:
            continue
        g.nodes[new]["osm_node_ids"] |= g.nodes[old].get("osm_node_ids", set())
        for _, nbr, d in list(g.edges(old, data=True)):
            target = old_to_new.get(nbr, nbr)
            if new == target:
                continue
            if g.has_edge(new, target):
                continue
            g.add_edge(new, target, **d)
        g.remove_node(old)
    if way_ends:
        for i, (wid, a, b) in enumerate(way_ends):
            way_ends[i] = (
                wid,
                old_to_new.get(a, a),
                old_to_new.get(b, b),
            )


def _key_for_osm_id(g, osm_id):
    osm_id = str(osm_id)
    for key, data in g.nodes(data=True):
        if osm_id in data.get("osm_node_ids", set()):
            return key
    return None


# (osm_node_ids are stored as strings; see _emit.)
