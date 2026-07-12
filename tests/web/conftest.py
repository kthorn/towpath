from pathlib import Path

import networkx as nx
import pytest
from fastapi.testclient import TestClient

from pound.graph.artifact import save_artifact
from pound.ingest.ir import WayDimensions
from pound.web.app import create_app
from pound.web.config import WebSettings


@pytest.fixture
def route_graph() -> nx.Graph:
    graph = nx.Graph(fetched_at="2026-07-11T00:00:00Z", marker={"stable": True})
    graph.add_node(1, lat=51.0, lon=-1.0, name="Start", tags={"kind": "canal"})
    graph.add_node(2, lat=51.001, lon=-1.001, name="Middle", tags={"kind": "canal"})
    graph.add_node(3, lat=51.002, lon=-1.002, name="End", tags={"kind": "canal"})
    graph.add_node(4, lat=52.0, lon=-2.0, name="Island", tags={"kind": "canal"})
    dimensions = WayDimensions(max_beam_m=3.0)
    graph.add_edge(
        1,
        2,
        length_m=100.0,
        locks=0,
        dimensions=dimensions,
        osm_way_id=12,
        geometry=[(51.0, -1.0), (51.001, -1.001)],
        tags={"stable": True},
    )
    graph.add_edge(
        2,
        3,
        length_m=100.0,
        locks=1,
        dimensions=dimensions,
        osm_way_id=23,
        geometry=[(51.001, -1.001), (51.002, -1.002)],
        tags={"stable": True},
    )
    return graph


@pytest.fixture
def web_client(tmp_path: Path, route_graph: nx.Graph) -> TestClient:
    artifact_path = tmp_path / "graph.pkl"
    save_artifact(route_graph, artifact_path, {"artifact_revision": "revision-test"})
    settings = WebSettings(
        artifact_path=artifact_path,
        static_dir=tmp_path / "static",
        candidate_pool_size=3,
        google_destination_limit=2,
        minimum_candidate_spacing_m=0,
    )
    with TestClient(create_app(settings)) as client:
        yield client
