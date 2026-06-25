"""WaterwayFeatures -> noded NetworkX graph (design §4.2).

Nodes are (lat, lon) tuples rounded to 7 decimals (~11 mm) — the key two
way-ends must share to be joined. The Overpass `out geom` reader leaves
`node_ids` empty (see ir.py docstring), so connectivity is derived from
shared endpoint COORDINATES, not shared node refs. This works on hand-curated
fixtures with matched endpoints; bulk/raw data needs tolerance-snap and is
deferred to the scale scope.
"""

import math

import networkx as nx

from pound.ingest.ir import WaterwayFeatures, WaterwayKind

_ROUND = 7
_ROUTABLE = {WaterwayKind.CANAL, WaterwayKind.RIVER, WaterwayKind.FAIRWAY, WaterwayKind.LOCK}


def _node_key(lat: float, lon: float) -> tuple[float, float]:
    return (round(lat, _ROUND), round(lon, _ROUND))


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in metres between two (lat, lon) points."""
    r = 6_371_000.0
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def build_graph(features: WaterwayFeatures) -> nx.Graph:
    """Build a noded, connected graph from WaterwayFeatures.

    Each way becomes one edge between its first and last geometry point.
    Intermediate geometry is preserved on the edge for later amenity buffers.
    Derelict ways are excluded (already dropped by filters; re-confirmed here).
    """
    g = nx.Graph()
    for way in features.ways:
        if way.kind not in _ROUTABLE:
            continue  # defensive: filters already dropped derelict
        if len(way.geometry) < 2:
            continue  # degenerate; validate.py reports, build skips
        a = _node_key(*way.geometry[0])
        b = _node_key(*way.geometry[-1])
        length_m = sum(
            _haversine_m(way.geometry[i], way.geometry[i + 1]) for i in range(len(way.geometry) - 1)
        )
        for node in (a, b):
            if node not in g:
                g.add_node(node, lat=node[0], lon=node[1])
        g.add_edge(
            a,
            b,
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
    return g
