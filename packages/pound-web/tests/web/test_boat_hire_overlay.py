from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import networkx as nx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pound.graph.spatial import GraphSpatialIndex
from pound.models import WayDimensions
from pound.schemas import CanalPointHandle, Coordinate
from pound_web.app import create_app
from pound_web.boat_hire import (
    BoatHireAnchor,
    BoatHireSeed,
    select_boat_hire_reachability,
    snap_boat_hire_bases,
)
from pound_web.config import WebSettings
from pound_web.network import prepare_network_geometry

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


def _compact_overlay_graph() -> nx.Graph:
    graph = nx.Graph()
    graph.add_node(1, lat=51.0, lon=-1.0, movable_bridge_ids=())
    graph.add_node(2, lat=51.0, lon=-1.01, movable_bridge_ids=())
    graph.add_edge(
        1,
        2,
        length_m=1_000.0,
        locks=0,
        dimensions=WayDimensions(),
        movable_bridge_ids=(),
        geometry=[(51.0, -1.0), (51.0, -1.01)],
    )
    return graph


def _compact_anchor(fraction: float = 0.5) -> BoatHireAnchor:
    return cast(Any, BoatHireAnchor)(
        BoatHireSeed("provider", "base:one", 51.0, -1.005),
        CanalPointHandle(edge=(1, 2), fraction=fraction),
        Coordinate(lat=51.0, lon=-1.005),
        0.0,
    )


def test_reachability_clips_a_compact_source_edge_before_either_endpoint():
    graph = _compact_overlay_graph()

    reachability: Any = select_boat_hire_reachability(
        graph,
        (_compact_anchor(),),
        cutoff_min=4.0,
        boat_length_m=None,
        boat_beam_m=None,
        boat_draft_m=None,
        boat_height_m=None,
        movable_bridge_delay_min=5.0,
    )

    assert reachability.full_edge_keys == ()
    assert len(reachability.clipped_lines) == 1
    clipped = reachability.clipped_lines[0]
    assert len(clipped) >= 2
    assert -1.005 < clipped[0][1] < -1.0
    assert -1.01 < clipped[-1][1] < -1.005

    lines = prepare_network_geometry(graph, reachability.full_edge_keys, reachability.clipped_lines)
    assert lines
    assert (-1.0, 51.0) not in [coordinate for line in lines for coordinate in line.coordinates]


def test_reachability_seeds_each_endpoint_with_its_partial_cost():
    graph = _compact_overlay_graph()
    graph.add_node(3, lat=51.0, lon=-1.02, movable_bridge_ids=())
    graph.add_edge(
        2,
        3,
        length_m=100.0,
        locks=0,
        dimensions=WayDimensions(),
        movable_bridge_ids=(),
        geometry=[(51.0, -1.01), (51.0, -1.02)],
    )

    reachability: Any = select_boat_hire_reachability(
        graph,
        (_compact_anchor(),),
        cutoff_min=7.0,
        boat_length_m=None,
        boat_beam_m=None,
        boat_draft_m=None,
        boat_height_m=None,
        movable_bridge_delay_min=5.0,
    )

    assert reachability.full_edge_keys == ((1, 2),)
    assert reachability.clipped_lines == ()


def test_reachability_unions_clipped_lines_from_multiple_bases():
    graph = _compact_overlay_graph()
    graph.add_node(3, lat=52.0, lon=-2.0, movable_bridge_ids=())
    graph.add_node(4, lat=52.0, lon=-2.01, movable_bridge_ids=())
    graph.add_edge(
        3,
        4,
        length_m=1_000.0,
        locks=0,
        dimensions=WayDimensions(),
        movable_bridge_ids=(),
        geometry=[(52.0, -2.0), (52.0, -2.01)],
    )
    anchors = (
        _compact_anchor(),
        cast(Any, BoatHireAnchor)(
            BoatHireSeed("provider", "base:two", 52.0, -2.005),
            CanalPointHandle(edge=(3, 4), fraction=0.5),
            Coordinate(lat=52.0, lon=-2.005),
            0.0,
        ),
    )

    reachability: Any = select_boat_hire_reachability(
        graph,
        anchors,
        cutoff_min=4.0,
        boat_length_m=None,
        boat_beam_m=None,
        boat_draft_m=None,
        boat_height_m=None,
        movable_bridge_delay_min=5.0,
    )

    assert reachability.full_edge_keys == ()
    assert len(reachability.clipped_lines) == 2


def test_reachability_rejects_a_boat_that_cannot_use_the_source_edge():
    graph = _compact_overlay_graph()
    graph.edges[1, 2]["dimensions"] = WayDimensions(max_beam_m=2.0)

    reachability: Any = select_boat_hire_reachability(
        graph,
        (_compact_anchor(),),
        cutoff_min=20.0,
        boat_length_m=None,
        boat_beam_m=2.1,
        boat_draft_m=None,
        boat_height_m=None,
        movable_bridge_delay_min=5.0,
    )

    assert reachability.full_edge_keys == ()
    assert reachability.clipped_lines == ()


def test_reachability_charges_a_bridge_only_when_its_endpoint_is_reached():
    graph = _compact_overlay_graph()
    graph.nodes[2]["movable_bridge_ids"] = ("bridge:2",)

    delayed: Any = select_boat_hire_reachability(
        graph,
        (_compact_anchor(),),
        cutoff_min=6.3,
        boat_length_m=None,
        boat_beam_m=None,
        boat_draft_m=None,
        boat_height_m=None,
        movable_bridge_delay_min=5.0,
    )
    free: Any = select_boat_hire_reachability(
        graph,
        (_compact_anchor(),),
        cutoff_min=6.3,
        boat_length_m=None,
        boat_beam_m=None,
        boat_draft_m=None,
        boat_height_m=None,
        movable_bridge_delay_min=0.0,
    )

    assert delayed.full_edge_keys == ()
    assert free.full_edge_keys == ((1, 2),)


def test_reachability_does_not_mutate_graph_geometry_or_attributes():
    graph = _compact_overlay_graph()
    before_nodes = dict(graph.nodes(data=True))
    before_edges = {(u, v): data.copy() for u, v, data in graph.edges(data=True)}

    select_boat_hire_reachability(
        graph,
        (_compact_anchor(),),
        cutoff_min=4.0,
        boat_length_m=None,
        boat_beam_m=None,
        boat_draft_m=None,
        boat_height_m=None,
        movable_bridge_delay_min=5.0,
    )

    assert dict(graph.nodes(data=True)) == before_nodes
    assert {(u, v): data for u, v, data in graph.edges(data=True)} == before_edges


def test_snap_uses_projected_candidate_and_reports_snap_distance():
    point = Coordinate(lat=51.0, lon=-1.005)

    class _CandidateIndex:
        def nearest_projection(self, latitude: float, longitude: float):
            assert (latitude, longitude) == (51.0, -1.005)
            return (
                type(
                    "Projected",
                    (),
                    {
                        "handle": CanalPointHandle(edge=(1, 2), fraction=0.5),
                        "coordinate": point,
                    },
                )(),
                12.5,
            )

    class _SpatialIndex:
        candidate_index = _CandidateIndex()

    anchors = snap_boat_hire_bases(
        _SpatialIndex(),
        (BoatHireSeed("provider", "base:one", 51.0, -1.005),),
    )

    assert anchors[0].handle == CanalPointHandle(edge=(1, 2), fraction=0.5)
    assert anchors[0].coordinate == point
    assert anchors[0].snap_distance_m == 12.5


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
