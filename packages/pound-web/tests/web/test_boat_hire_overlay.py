from pathlib import Path
from typing import cast
from unittest.mock import patch

import networkx as nx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pound.graph.spatial import GraphSpatialIndex
from pound_web.app import create_app
from pound_web.boat_hire import snap_boat_hire_bases
from pound_web.config import WebSettings

from .conftest import artifact_metadata, write_boat_hire_enrichment
from .fixtures import write_runtime_artifact as save_artifact


def _two_component_graph(route_graph: nx.Graph) -> nx.Graph:
    graph = route_graph.copy()
    graph.add_node(
        5,
        lat=52.001,
        lon=-2.001,
        osm_node_ids={"5"},
        movable_bridge_ids=(),
        turning_point=False,
        turning_max_length_m=None,
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


def _network_request(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {"days": 7, "hours_per_day": 6}
    payload.update(changes)
    return payload


def _active_row(
    provider: str,
    location: str,
    *,
    provider_name: str = "",
    location_name: str = "",
) -> dict[str, str]:
    return {
        "record_type": "company_base",
        "source_provider_id": provider,
        "source_provider_name": provider_name,
        "location_id": location,
        "location_name": location_name,
        "latitude": "51.0",
        "longitude": "-1.0",
        "osm_url": "https://www.openstreetmap.org/node/1",
        "exclude": "",
    }


def test_network_filters_display_without_filtering_routing_graph(
    tmp_path: Path, route_graph: nx.Graph
):
    graph = _two_component_graph(route_graph)
    settings = _settings(tmp_path, graph)
    expected_nodes = set(graph.nodes)
    expected_edges = set(graph.edges)

    with (
        patch("pound_web.app.GraphSpatialIndex", wraps=GraphSpatialIndex) as build_index,
        patch(
            "pound_web.app.snap_boat_hire_bases",
            wraps=snap_boat_hire_bases,
        ) as snap_bases,
        TestClient(create_app(settings)) as client,
    ):
        app = cast(FastAPI, client.app)
        overlay = client.post("/api/canal-network", json=_network_request())
        route = client.post(
            "/api/canal-route",
            json={
                "start": {"edge": [4, 5], "fraction": 0},
                "end": {"edge": [4, 5], "fraction": 1},
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
    assert build_index.call_count == 1
    assert snap_bases.call_count == 1
    assert app.state.boat_hire_anchors
    assert app.state.network_unavailable is False


def test_network_returns_active_bases_in_csv_order(tmp_path: Path, route_graph: nx.Graph):
    settings = _settings(
        tmp_path,
        route_graph,
        rows=[
            _active_row(
                "provider-a",
                "base:a",
                provider_name="Operator A",
                location_name="Base A",
            ),
            _active_row("provider-b", "base:b", provider_name="Operator B"),
        ],
    )

    with TestClient(create_app(settings)) as client:
        response = client.post("/api/canal-network", json=_network_request())

    assert response.status_code == 200
    assert response.json()["bases"] == [
        {
            "identity": "provider-a/base:a",
            "operator": "Operator A",
            "name": "Base A",
            "coordinate": {"lat": 51.0, "lon": -1.0},
        },
        {
            "identity": "provider-b/base:b",
            "operator": "Operator B",
            "name": "base:b",
            "coordinate": {"lat": 51.0, "lon": -1.0},
        },
    ]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (
            [
                {
                    "record_type": "company_base",
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
                    "record_type": "company_base",
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


def test_all_excluded_bases_are_unavailable_but_routing_remains_available(
    tmp_path: Path, route_graph: nx.Graph
):
    settings = _settings(
        tmp_path,
        route_graph,
        rows=[
            {
                "record_type": "company_base",
                "source_provider_id": "test-provider",
                "location_id": "base:test",
                "exclude": "true",
            }
        ],
    )

    with TestClient(create_app(settings)) as client:
        overlay = client.post("/api/canal-network", json=_network_request())
        route = client.post(
            "/api/canal-route",
            json={
                "start": {"edge": [1, 2], "fraction": 0},
                "end": {"edge": [2, 3], "fraction": 1},
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
