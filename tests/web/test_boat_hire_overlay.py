from pathlib import Path
from typing import cast
from unittest.mock import patch

import networkx as nx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pound.graph.artifact import save_artifact
from pound.graph.spatial import GraphSpatialIndex
from pound.web.app import create_app
from pound.web.boat_hire import select_boat_hire_overlay
from pound.web.config import WebSettings
from tests.web.conftest import artifact_metadata, write_boat_hire_enrichment


def _two_component_graph(route_graph: nx.Graph) -> nx.Graph:
    graph = route_graph.copy()
    graph.add_node(
        5,
        lat=52.001,
        lon=-2.001,
        osm_node_ids={"5"},
        movable_bridge_ids=(),
        name="Omitted end",
        tags={"kind": "canal"},
    )
    edge = dict(graph.edges[1, 2])
    edge.update(
        osm_way_id=45,
        name="Omitted reach",
        geometry=[(52.0, -2.0), (52.001, -2.001)],
    )
    graph.add_edge(4, 5, **edge)
    return graph


def _settings(
    tmp_path: Path,
    graph: nx.Graph,
    *,
    rows: list[dict[str, str]] | None = None,
) -> WebSettings:
    artifact_path = tmp_path / "graph.pkl"
    save_artifact(graph, [], artifact_path, artifact_metadata("overlay-test"))
    return WebSettings(
        artifact_path=artifact_path,
        static_dir=tmp_path / "static",
        boat_hire_enrichment_path=write_boat_hire_enrichment(tmp_path / "boat-hire.csv", rows=rows),
    )


def test_overlay_filters_network_without_filtering_routing_graph(
    tmp_path: Path, route_graph: nx.Graph
):
    graph = _two_component_graph(route_graph)
    settings = _settings(tmp_path, graph)
    expected_nodes = set(graph.nodes)
    expected_edges = set(graph.edges)

    with (
        patch("pound.web.app.GraphSpatialIndex", wraps=GraphSpatialIndex) as build_index,
        patch(
            "pound.web.app.select_boat_hire_overlay",
            wraps=select_boat_hire_overlay,
        ) as select_overlay,
        TestClient(create_app(settings)) as client,
    ):
        app = cast(FastAPI, client.app)
        overlay = client.get("/api/canal-network")
        route = client.post(
            "/api/canal-route",
            json={
                "start_uid": 4,
                "end_uid": 5,
                "artifact_revision": "overlay-test",
                "hours_per_day": 6,
            },
        )

    assert overlay.status_code == 200
    coordinates = [
        coordinate for line in overlay.json()["lines"] for coordinate in line["coordinates"]
    ]
    assert [-1.0, 51.0] in coordinates
    assert [-2.001, 52.001] not in coordinates
    assert route.status_code == 200
    assert route.json()["geometry"]["coordinates"] == [[-2.0, 52.0], [-2.001, 52.001]]
    assert app.state.graph is app.state.artifact.graph
    assert set(app.state.graph.nodes) == expected_nodes
    assert set(app.state.graph.edges) == expected_edges
    build_index.assert_called_once_with(app.state.graph)
    assert select_overlay.call_args.args[0] is app.state.graph
    assert select_overlay.call_args.args[1] is app.state.spatial_index


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (
            [
                {
                    "source_provider_id": "test-provider",
                    "location_id": "base:test",
                    "latitude": "not-a-coordinate",
                    "longitude": "-1.0",
                    "osm_url": "https://www.openstreetmap.org/node/1",
                }
            ],
            "non-numeric coordinates",
        ),
        (
            [
                {
                    "source_provider_id": "test-provider",
                    "location_id": "base:test",
                    "latitude": "0.0",
                    "longitude": "0.0",
                    "osm_url": "https://www.openstreetmap.org/node/1",
                }
            ],
            "farther than 250 m",
        ),
    ],
)
def test_invalid_active_seeds_abort_startup(
    tmp_path: Path,
    route_graph: nx.Graph,
    rows: list[dict[str, str]],
    message: str,
):
    settings = _settings(tmp_path, route_graph, rows=rows)

    with pytest.raises(ValueError, match=message):
        with TestClient(create_app(settings)):
            pass


def test_all_excluded_overlay_is_unavailable_but_routing_remains_available(
    tmp_path: Path, route_graph: nx.Graph
):
    settings = _settings(
        tmp_path,
        route_graph,
        rows=[
            {
                "source_provider_id": "test-provider",
                "location_id": "base:test",
                "exclude": "true",
            }
        ],
    )

    with TestClient(create_app(settings)) as client:
        overlay = client.get("/api/canal-network")
        route = client.post(
            "/api/canal-route",
            json={
                "start_uid": 1,
                "end_uid": 3,
                "artifact_revision": "overlay-test",
                "hours_per_day": 6,
            },
        )

    assert overlay.status_code == 503
    assert overlay.json()["detail"] == {
        "code": "network_unavailable",
        "message": "The canal network overlay is unavailable.",
        "fields": [],
    }
    assert route.status_code == 200
