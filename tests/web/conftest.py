from collections.abc import Generator
from pathlib import Path

import networkx as nx
import pytest
from fastapi.testclient import TestClient

from pound.graph.artifact import save_artifact
from pound.ingest.ir import OsmElementType, PoiCategory, PointOfInterest, WayDimensions
from pound.web.app import create_app
from pound.web.config import WebSettings


def artifact_metadata(revision: str, *, source: str = "test") -> dict:
    return {
        "artifact_revision": revision,
        "source": source,
        "fetched_at": "2026-07-11T00:00:00Z",
        "built_at": "2026-07-12T00:00:00Z",
        "validation": {},
        "poi_summary": {},
    }


@pytest.fixture
def route_graph() -> nx.Graph:
    graph = nx.Graph(fetched_at="2026-07-11T00:00:00Z", marker={"stable": True})
    graph.add_node(1, lat=51.0, lon=-1.0, osm_node_ids={"1"}, name="Start", tags={"kind": "canal"})
    graph.add_node(
        2,
        lat=51.001,
        lon=-1.001,
        osm_node_ids={"2"},
        name="Middle",
        tags={"kind": "canal"},
    )
    graph.add_node(
        3, lat=51.002, lon=-1.002, osm_node_ids={"3"}, name="End", tags={"kind": "canal"}
    )
    graph.add_node(4, lat=52.0, lon=-2.0, osm_node_ids={"4"}, name="Island", tags={"kind": "canal"})
    dimensions = WayDimensions(max_beam_m=3.0)
    graph.add_edge(
        1,
        2,
        length_m=100.0,
        locks=0,
        dimensions=dimensions,
        osm_way_id=12,
        name="First reach",
        kind="canal",
        geometry=[(51.0, -1.0), (51.001, -1.001)],
        has_tunnel=False,
        has_movable_bridge=False,
        tags={"stable": True},
    )
    graph.add_edge(
        2,
        3,
        length_m=100.0,
        locks=1,
        dimensions=dimensions,
        osm_way_id=23,
        name="Second reach",
        kind="canal",
        geometry=[(51.001, -1.001), (51.002, -1.002)],
        has_tunnel=False,
        has_movable_bridge=False,
        tags={"stable": True},
    )
    return graph


def fixture_pois() -> tuple[PointOfInterest, ...]:
    return (
        PointOfInterest(
            osm_type=OsmElementType.NODE,
            osm_id=101,
            category=PoiCategory.PROVISIONS,
            kind="pub",
            name="The Test Pub",
            lat=51.0,
            lon=-1.0,
            source_tags={"amenity": "pub"},
            geometry_source="point",
            nearest_waterway_distance_m=0,
            nearest_edge=(1, 2),
            nearest_node_uid=1,
            projected_lat=51.0,
            projected_lon=-1.0,
        ),
        PointOfInterest(
            osm_type=OsmElementType.NODE,
            osm_id=102,
            category=PoiCategory.PROVISIONS,
            kind="shop",
            name="The Test Shop",
            lat=51.001,
            lon=-1.001,
            source_tags={"shop": "general"},
            geometry_source="point",
            nearest_waterway_distance_m=0,
            nearest_edge=(1, 2),
            nearest_node_uid=2,
            projected_lat=51.001,
            projected_lon=-1.001,
        ),
    )


@pytest.fixture
def web_client(tmp_path: Path, route_graph: nx.Graph) -> Generator[TestClient, None, None]:
    artifact_path = tmp_path / "graph.pkl"
    save_artifact(route_graph, fixture_pois(), artifact_path, artifact_metadata("revision-test"))
    settings = WebSettings(
        artifact_path=artifact_path,
        static_dir=tmp_path / "static",
        candidate_pool_size=3,
        google_destination_limit=2,
        minimum_candidate_spacing_m=0,
    )
    with TestClient(create_app(settings)) as client:
        yield client
