"""Offline gazetteer + place snapping (design §5.1).

Built from PLACE nodes in the IR (place=* nodes). Network-free: the gazetteer
is a dict built once from the same features the graph was built from. A place
name maps to its coordinate, which is the graph node key (place nodes sit
exactly on way endpoints in the fixture; for bulk data a nearest-node-within-
tolerance step is needed and is deferred).
"""

from pound.graph.build import _node_key
from pound.ingest.ir import NodeKind, WaterwayFeatures


def build_gazetteer(features: WaterwayFeatures) -> dict[str, tuple[float, float]]:
    return {
        n.tags["name"]: _node_key(n.lat, n.lon)
        for n in features.nodes
        if n.kind == NodeKind.PLACE and "name" in n.tags
    }


def snap_place(name: str, gazetteer: dict, graph) -> tuple[float, float]:
    if name not in gazetteer:
        raise ValueError(f"unknown place: {name!r}")
    node = gazetteer[name]
    if node not in graph.nodes:
        raise ValueError(f"place {name!r} snaps to a node not in the graph")
    return node
