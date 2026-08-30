"""Place -> graph node resolution (design §4 contract evolution, §6 CLI).

Ships the offline resolver only (a function, not a class — see OQ-3): dict-lookup
of the embedded `graph.graph["gazetteer"]` (built at build time by
pound.graph.gazetteer), then nearest-graph-node-within-tolerance if the place
coordinate isn't already a node. No network, no LLM, hermetic in this scope.

# future: GeocodeResolver (network) — a deferred scope will add a network
# geocoder behind the same resolve_place surface; do not pre-build a protocol
# here. The seam is this docstring + the resolve_place function.
#
# resolve_coord(lat, lon, graph) -> (uid, distance_m) now SHIPS here (was a
# # future seam earlier in PR2): snap a raw coordinate to the nearest node uid
# and report the distance, no tolerance gate. pound-locate and a future
# map-click UI both build on it.
"""

import math

import networkx as nx

from pound.geometry import haversine_m as _haversine_m
from pound.geometry import node_key as _node_key
from pound.graph.spatial import GraphSpatialIndex, nearest_node_distances

_DEFAULT_SNAP_TOLERANCE_M = 50.0


def resolve_place(
    name: str,
    graph: nx.Graph,
    *,
    gazetteer: dict | None = None,
    snap_tolerance_m: float = _DEFAULT_SNAP_TOLERANCE_M,
) -> int:
    """Resolve a place name to the uid of a graph node (offline only).

    Returns the graph's internal node handle (an int) so `plan_route` can consume
    it directly with no coord→uid mapping step. A future geography-first caller
    (map-click UI posting raw lat/lon) uses the deferred resolve_coord helper
    instead — both produce uids, keeping ResolvedConstraints uid-typed. Order:
      1. exact gazetteer hit (single tuple) -> the graph node whose
         `_node_key(nd["lat"], nd["lon"])` equals that tuple, if any; else the
         nearest node within snap_tolerance_m (haversine over node lat/lon attrs).
         Returns the matched node's uid.
      2. ambiguous (gazetteer entry is a list) -> raise ValueError.
      3. name absent -> raise ValueError citing N = len(gazetteer).

    Raises ValueError for unknown / ambiguous names (never KeyError).
    """
    gaz = graph.graph.get("gazetteer", {}) if gazetteer is None else gazetteer
    if name not in gaz:
        raise ValueError(
            f"{name!r} not found in gazetteer; this build covers {len(gaz)} places; "
            f"try a different name or wait for geocoding support"
        )
    entry = gaz[name]
    if isinstance(entry, list):
        raise ValueError(
            f"{name!r} matches {len(entry)} places; specify a nearby town or a more specific name"
        )
    target = entry
    # Exact match: a graph node whose rounded _node_key equals the gazetteer coord.
    for uid, nd in graph.nodes(data=True):
        if _node_key(nd["lat"], nd["lon"]) == target:
            return uid
    # Nearest graph node within tolerance (linear; R6: ms at England scale).
    best, best_d = None, math.inf
    for uid, nd in graph.nodes(data=True):
        node_coord = (nd["lat"], nd["lon"])
        d = _haversine_m(target, node_coord)
        if d < best_d:
            best, best_d = uid, d
    if best is None or best_d > snap_tolerance_m:
        raise ValueError(
            f"{name!r} at {target} is not within {snap_tolerance_m} m "
            f"of any graph node (nearest {best_d:.1f} m)"
        )
    return best


def resolve_coord(
    lat: float,
    lon: float,
    graph: nx.Graph,
    spatial_index: GraphSpatialIndex,
) -> tuple[int, float]:
    """Resolve a coordinate to the nearest graph node uid + distance (offline only).

    Geography-first entry (supersedes PR2's `# future: resolve_coord` seam).
    No tolerance gate: always returns the nearest node and its haversine distance
    in metres; the caller decides whether the distance is acceptable. A future
    map-click UI compares the distance to its own tolerance; `pound-locate`
    offers `--max-distance-m` for that scripting need.

    Raises ValueError for an empty graph (defensive; production graphs always
    have nodes). The caller supplies the immutable artifact-level spatial index
    so repeated request-time lookups reuse one STRtree.
    """
    ranked = nearest_node_distances(lat, lon, graph, spatial_index, limit=1)
    if not ranked:
        raise ValueError("no graph nodes to resolve against")
    distance, uid = ranked[0]
    return uid, distance
