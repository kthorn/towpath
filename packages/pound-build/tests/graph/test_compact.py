from typing import Any, cast

import networkx as nx
import pytest  # pyright: ignore[reportMissingImports]
from pound.models import WaterwayKind, WayDimensions  # pyright: ignore[reportMissingImports]
from pound_build.graph.compact import (  # pyright: ignore[reportMissingModuleSource]
    _emit_chain,
    compact_graph,
)
from pyproj import Transformer  # pyright: ignore[reportMissingImports]
from shapely import transform
from shapely.geometry import LineString

_TO_BNG = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)


def _edge(graph, u, v, *, osm_way_id=1, length_m=10.0, geometry=None, **overrides):
    attrs = {
        "osm_way_id": osm_way_id,
        "name": None,
        "kind": WaterwayKind.CANAL,
        "length_m": length_m,
        "dimensions": WayDimensions(max_beam_m=2.0),
        "has_tunnel": False,
        "has_movable_bridge": False,
        "locks": 0,
        "geometry": geometry or [graph.nodes[u]["coord"], graph.nodes[v]["coord"]],
        "movable_bridge_ids": (),
        "tunnel_restrictions": (),
        "access_caveats": (),
    }
    attrs.update(overrides)
    graph.add_edge(u, v, **attrs)


def _node(graph, uid, lat, lon, **attrs):
    graph.add_node(uid, lat=lat, lon=lon, coord=(lat, lon), movable_bridge_ids=(), **attrs)


def _without_coords(graph):
    for _, data in graph.nodes(data=True):
        data.pop("coord", None)


def _metric_line(geometry):
    return transform(
        LineString([(lon, lat) for lat, lon in geometry]),
        cast(Any, _TO_BNG.transform),
        interleaved=False,
    )


def test_straight_chain_contracts_and_keeps_source_length_and_endpoints():
    source = nx.Graph()
    _node(source, 0, 51.7500, -1.2600)
    _node(source, 1, 51.7505, -1.2600)
    _node(source, 2, 51.7510, -1.2600)
    _edge(source, 0, 1, length_m=17.25)
    _edge(source, 1, 2, length_m=18.75)
    _without_coords(source)

    compact = compact_graph(source)

    assert compact.number_of_nodes() == 2
    assert compact.number_of_edges() == 1
    edge = compact.edges[0, 2]
    assert edge["length_m"] == pytest.approx(36.0)
    assert edge["geometry"][0] == (51.7500, -1.2600)
    assert edge["geometry"][-1] == (51.7510, -1.2600)


def test_curved_chain_simplification_stays_within_metric_bound():
    source = nx.Graph()
    geometry = [
        (51.7500, -1.2600),
        (51.7504, -1.2599),
        (51.7508, -1.2601),
        (51.7512, -1.2600),
    ]
    for uid, point in enumerate(geometry):
        _node(source, uid, *point)
    for uid in range(len(geometry) - 1):
        _edge(source, uid, uid + 1, length_m=20.0, geometry=[geometry[uid], geometry[uid + 1]])
    _without_coords(source)

    compact = compact_graph(source)
    compact_line = _metric_line(compact.edges[0, 3]["geometry"])
    source_line = _metric_line(geometry)

    assert compact.number_of_nodes() == 2
    assert compact.edges[0, 3]["length_m"] == pytest.approx(60.0)
    assert compact_line.hausdorff_distance(source_line) <= 1.0


def test_attribute_boundary_and_junction_are_retained():
    source = nx.Graph()
    for uid, point in enumerate(
        [(51.75, -1.26), (51.7505, -1.26), (51.751, -1.26), (51.7505, -1.259)]
    ):
        _node(source, uid, *point)
    _edge(source, 0, 1, osm_way_id=10)
    _edge(source, 1, 2, osm_way_id=11)
    _edge(source, 1, 3, osm_way_id=12)
    _without_coords(source)

    compact = compact_graph(source)

    assert compact.number_of_nodes() == 4
    assert compact.number_of_edges() == 3
    assert compact.has_edge(0, 1)
    assert compact.has_edge(1, 2)
    assert compact.has_edge(1, 3)


def test_lock_and_movable_bridge_edges_are_not_candidate_eligible():
    source = nx.Graph()
    for uid, point in enumerate(
        [(51.75, -1.26), (51.7505, -1.26), (51.751, -1.26), (51.7515, -1.26)]
    ):
        _node(source, uid, *point)
    _edge(source, 0, 1, osm_way_id=10)
    _edge(source, 1, 2, osm_way_id=11, kind=WaterwayKind.LOCK, locks=1)
    _edge(
        source,
        2,
        3,
        osm_way_id=12,
        has_movable_bridge=True,
        movable_bridge_ids=("way:12",),
    )
    _without_coords(source)

    compact = compact_graph(source)

    assert compact.number_of_edges() == 3
    assert compact.edges[0, 1]["candidate_eligible"] is True
    assert compact.edges[1, 2]["candidate_eligible"] is False
    assert compact.edges[2, 3]["candidate_eligible"] is False


def test_named_and_node_bridge_events_remain_anchors():
    source = nx.Graph()
    for uid, point in enumerate([(51.75, -1.26), (51.7505, -1.26), (51.751, -1.26)]):
        _node(source, uid, *point)
    source.nodes[1]["name"] = "Bridge"
    source.nodes[1]["movable_bridge_ids"] = ("node:99",)
    _edge(source, 0, 1)
    _edge(source, 1, 2)
    _without_coords(source)

    compact = compact_graph(source)

    assert compact.number_of_nodes() == 3
    assert compact.has_node(1)
    assert compact.nodes[1]["name"] == "Bridge"
    assert compact.nodes[1]["movable_bridge_ids"] == ("node:99",)


def test_parallel_alternative_keeps_one_deterministic_anchor():
    source = nx.Graph()
    for uid, point in enumerate(
        [(51.75, -1.26), (51.7505, -1.259), (51.751, -1.26), (51.7505, -1.261)]
    ):
        _node(source, uid, *point)
    _edge(source, 0, 2, osm_way_id=10)
    _edge(source, 0, 1, osm_way_id=11)
    _edge(source, 1, 2, osm_way_id=11)
    _edge(source, 0, 3, osm_way_id=12)
    _edge(source, 3, 2, osm_way_id=12)
    _without_coords(source)

    compact = compact_graph(source)

    assert compact.number_of_nodes() == 4
    assert compact.number_of_edges() == 5
    assert compact.has_node(1)
    assert compact.has_node(3)
    assert compact.has_edge(0, 2)
    assert compact.edges[0, 1]["osm_way_id"] == 11
    assert compact.edges[1, 2]["osm_way_id"] == 11
    assert compact.edges[0, 3]["osm_way_id"] == 12
    assert compact.edges[2, 3]["osm_way_id"] == 12


def test_shorter_parallel_path_keeps_alternate_anchor_attributes():
    source = nx.Graph()
    coordinates = {
        0: (51.7500, -1.2600),
        1: (51.7504, -1.2598),
        2: (51.7507, -1.2598),
        10: (51.7510, -1.2600),
        20: (51.7495, -1.2600),
        30: (51.7515, -1.2600),
    }
    for uid, coordinate in coordinates.items():
        _node(source, uid, *coordinate)
    _edge(source, 0, 1, osm_way_id=10)
    _edge(source, 1, 2, osm_way_id=10)
    _edge(source, 2, 10, osm_way_id=10)
    _edge(source, 0, 10, osm_way_id=10)
    _edge(source, 0, 20, osm_way_id=20)
    _edge(source, 10, 30, osm_way_id=30)
    _without_coords(source)

    compact = compact_graph(source)

    assert compact.nodes[1]["lat"] == coordinates[1][0]
    assert compact.nodes[1]["lon"] == coordinates[1][1]


def test_reversed_chain_path_keeps_canonical_edge_geometry():
    source = nx.Graph()
    _node(source, 2, 51.7500, -1.2600)
    _node(source, 3, 51.7510, -1.2600)
    _edge(source, 2, 3, geometry=[(51.7500, -1.2600), (51.7510, -1.2600)])
    _without_coords(source)
    compact = nx.Graph()

    _emit_chain(compact, source, (3, 2), 1.0)

    assert compact.edges[2, 3]["geometry"][0] == (51.7500, -1.2600)
    assert compact.edges[2, 3]["geometry"][-1] == (51.7510, -1.2600)


def test_malformed_chain_join_is_rejected():
    source = nx.Graph()
    _node(source, 0, 51.7500, -1.2600)
    _node(source, 1, 51.7510, -1.2600)
    _node(source, 2, 51.7520, -1.2600)
    _edge(source, 0, 1, geometry=[(51.7500, -1.2600), (51.7600, -1.2600)])
    _edge(source, 1, 2)
    _without_coords(source)

    with pytest.raises(ValueError, match="does not meet node 1"):
        compact_graph(source)


def test_node_bridge_id_is_preserved_as_edge_endpoint_state():
    source = nx.Graph()
    _node(source, 0, 51.75, -1.26)
    _node(source, 1, 51.7505, -1.26)
    source.nodes[1]["movable_bridge_ids"] = ("node:7",)
    _edge(source, 0, 1, osm_way_id=7)
    _without_coords(source)

    compact = compact_graph(source)

    assert compact.nodes[1]["movable_bridge_ids"] == ("node:7",)
    assert compact.edges[0, 1]["candidate_eligible"] is True


def test_turning_point_remains_a_runtime_node():
    source = nx.Graph()
    _node(source, 0, 51.75, -1.26, turning_point=False, turning_max_length_m=None)
    _node(source, 1, 51.7505, -1.26, turning_point=True, turning_max_length_m=21.5)
    _node(source, 2, 51.751, -1.26, turning_point=False, turning_max_length_m=None)
    _edge(source, 0, 1)
    _edge(source, 1, 2)
    _without_coords(source)

    compact = compact_graph(source)

    assert set(compact) == {0, 1, 2}
    assert compact.nodes[1]["turning_point"] is True
    assert compact.nodes[1]["turning_max_length_m"] == 21.5
