"""Shared core-test fixture paths and trusted runtime payload writers."""

import pickle
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import networkx as nx
from pound.artifact import ROUTING_ARTIFACT_SCHEMA_VERSION
from pound.catalog.artifact import CATALOG_SCHEMA_VERSION, OSM_ATTRIBUTION
from pound.models import WayDimensions


def oxford_fixture_path() -> Path:
    return Path(__file__).parent / "oxford_overpass_sample.json"


def staircase_fixture_path() -> Path:
    return Path(__file__).parent / "staircase_overpass_sample.json"


def write_runtime_artifact(
    graph: nx.Graph,
    pois: Iterable[object],
    path: Path,
    metadata: dict[str, object],
    *,
    gazetteer: dict[str, tuple[float, float]] | None = None,
) -> Path:
    payload_metadata = dict(metadata)
    payload_metadata.setdefault("artifact_schema_version", ROUTING_ARTIFACT_SCHEMA_VERSION)
    with Path(path).open("wb") as stream:
        pickle.dump(
            {
                "graph": graph,
                "pois": list(pois),
                "gazetteer": gazetteer or {},
                "metadata": payload_metadata,
            },
            stream,
        )
    return Path(path)


def write_catalog_payload(places: Iterable[object], path: Path, metadata: dict[str, Any]) -> Path:
    payload_metadata = dict(metadata)
    payload_metadata.setdefault("catalog_schema_version", CATALOG_SCHEMA_VERSION)
    payload_metadata.setdefault("catalog_revision", "test-catalog")
    payload_metadata.setdefault("attribution", OSM_ATTRIBUTION)
    with Path(path).open("wb") as stream:
        pickle.dump({"places": list(places), "metadata": payload_metadata}, stream)
    return Path(path)


def routing_test_graph() -> tuple[nx.Graph, dict[str, tuple[float, float]]]:
    graph = nx.Graph(fetched_at="2026-06-21T12:00:00Z")
    nodes = (
        (1, 51.750, -1.260, "Oxford"),
        (2, 51.752, -1.262, "Kidlington"),
        (3, 51.754, -1.264, "Thrupp"),
        (4, 51.756, -1.266, "Shipton"),
        (5, 51.758, -1.268, "Hayfield"),
    )
    for uid, lat, lon, name in nodes:
        graph.add_node(uid, lat=lat, lon=lon, name=name, movable_bridge_ids=())
    pairs = zip(nodes, nodes[1:], strict=False)
    for index, ((u, lat, lon, _), (v, next_lat, next_lon, _)) in enumerate(pairs):
        graph.add_edge(
            u,
            v,
            length_m=130.8,
            locks=int(index == 2),
            lock_points=[(lat, lon)] if index == 2 else [],
            dimensions=WayDimensions(max_beam_m=2.1),
            osm_way_id=100 + index,
            geometry=[(lat, lon), (next_lat, next_lon)],
            movable_bridge_ids=(),
            tunnel_restrictions=(),
            access_caveats=(),
        )
    gazetteer = {name: (lat, lon) for _, lat, lon, name in (nodes[0], nodes[-1])}
    graph.graph["gazetteer"] = gazetteer
    return graph, gazetteer
