"""Build-time comprehensive place gazetteer + node-name attachment (design §4).

`build_gazetteer` extracts EVERY `place=*` node in the extract (~30k for
England) into {name -> node_key}. Duplicate place names are real (multiple
"Newton"s); a colliding name maps to a *list* of candidate node keys, surfaced
by `ambiguous_place_names` for curation and errored on lookup by the resolver
(PR2). `attach_node_names` writes a `name` node attribute onto every waterway
node coincident with a `place=*` node — pure data preservation so legs render
"Oxford -> ..." from the graph alone. No network.
"""

from collections import defaultdict

import networkx as nx

from pound.graph.build import _node_key
from pound.ingest.ir import NodeKind, WaterwayFeatures


def build_gazetteer(features: WaterwayFeatures):
    """name -> node_key (rounded) for unambiguous names; list[node_key] for duplicates.

    `place=*` nodes without a `name` tag are skipped (they still count toward
    `place_nodes_seen` in validate_graph).
    """
    by_name: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for n in features.nodes:
        if n.kind != NodeKind.PLACE:
            continue
        name = n.tags.get("name")
        if not name:
            continue
        by_name[name].append(_node_key(n.lat, n.lon))
    gaz: dict = {}
    for name, keys in by_name.items():
        unique = list(dict.fromkeys(keys))  # preserve order, dedupe
        gaz[name] = unique[0] if len(unique) == 1 else unique
    return gaz


def ambiguous_place_names(gaz: dict) -> list[str]:
    return sorted([name for name, v in gaz.items() if isinstance(v, list)])


def attach_node_names(graph: nx.Graph, features: WaterwayFeatures) -> int:
    """Set `name` on graph nodes coincident with a named place node. Returns count."""
    place_coords: dict[tuple[float, float], str] = {}
    for n in features.nodes:
        if n.kind != NodeKind.PLACE:
            continue
        name = n.tags.get("name")
        if name:
            place_coords[_node_key(n.lat, n.lon)] = name
    count = 0
    for key in graph.nodes():
        if key in place_coords and "name" not in graph.nodes[key]:
            graph.nodes[key]["name"] = place_coords[key]
            count += 1
    return count
