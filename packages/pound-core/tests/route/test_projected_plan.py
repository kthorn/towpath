import copy

import networkx as nx
import pytest
from pound.artifact import RuntimeArtifact
from pound.models import WayDimensions
from pound.route.cost import CRUISE_KMH, DEFAULT_MOVABLE_BRIDGE_DELAY_MIN
from pound.route.plan import plan_projected_route
from pound.route.project import project_handle
from pound.schemas import CanalPointHandle, ProjectedRouteConstraints


def _artifact(graph: nx.Graph) -> RuntimeArtifact:
    return RuntimeArtifact(
        graph=graph,
        pois=(),
        gazetteer={},
        metadata={"artifact_revision": "test", "fetched_at": "2026-08-30T00:00:00Z"},
    )


def _graph() -> nx.Graph:
    graph = nx.Graph()
    for uid, lon in ((1, -1.000), (2, -0.985), (3, -0.970), (4, -0.955)):
        graph.add_node(uid, lat=51.0, lon=lon, name=f"Node {uid}", movable_bridge_ids=())
    return graph


def _edge(
    graph: nx.Graph,
    u: int,
    v: int,
    *,
    length_m: float,
    way_id: int,
    candidate_eligible: bool = True,
    locks: int = 0,
) -> None:
    graph.add_edge(
        u,
        v,
        length_m=length_m,
        locks=locks,
        dimensions=WayDimensions(),
        osm_way_id=way_id,
        geometry=[
            (graph.nodes[u]["lat"], graph.nodes[u]["lon"]),
            (graph.nodes[v]["lat"], graph.nodes[v]["lon"]),
        ],
        movable_bridge_ids=(),
        tunnel_restrictions=(),
        access_caveats=(),
        candidate_eligible=candidate_eligible,
    )


def _constraints(
    start: tuple[int, int], start_fraction: float, end: tuple[int, int], end_fraction: float
):
    return ProjectedRouteConstraints(
        start=CanalPointHandle(edge=start, fraction=start_fraction),
        end=CanalPointHandle(edge=end, fraction=end_fraction),
    )


@pytest.mark.parametrize(
    ("start_fraction", "end_fraction"),
    [(0.2, 0.8), (0.8, 0.2)],
)
def test_same_edge_direct_route_preserves_both_orientations(start_fraction, end_fraction):
    graph = _graph()
    _edge(graph, 1, 2, length_m=1_000, way_id=12)
    constraints = _constraints((1, 2), start_fraction, (1, 2), end_fraction)

    response = plan_projected_route(constraints, artifact=_artifact(graph))

    start = project_handle(constraints.start, graph).coordinate
    end = project_handle(constraints.end, graph).coordinate
    assert response.route.total_km == pytest.approx(abs(end_fraction - start_fraction))
    assert response.geometry.coordinates[0] == pytest.approx((start.lon, start.lat), abs=3e-7)
    assert response.geometry.coordinates[-1] == pytest.approx((end.lon, end.lat), abs=3e-7)


def test_cheaper_leave_and_reenter_route_beats_same_edge_direct_geometry():
    graph = _graph()
    _edge(graph, 1, 2, length_m=1_000, way_id=12)
    _edge(graph, 1, 3, length_m=100, way_id=13)
    _edge(graph, 2, 3, length_m=100, way_id=23)

    response = plan_projected_route(
        _constraints((1, 2), 0.1, (1, 2), 0.9), artifact=_artifact(graph)
    )

    assert response.route.total_km == pytest.approx(0.4)
    assert (-0.970, 51.0) in response.geometry.coordinates


@pytest.mark.parametrize("start_endpoint,end_endpoint", [(1, 3), (1, 4), (2, 3), (2, 4)])
def test_each_endpoint_combination_can_win(start_endpoint, end_endpoint):
    graph = _graph()
    _edge(graph, 1, 2, length_m=100, way_id=12)
    _edge(graph, 3, 4, length_m=100, way_id=34)
    for u in (1, 2):
        for v in (3, 4):
            _edge(
                graph,
                u,
                v,
                length_m=10 if (u, v) == (start_endpoint, end_endpoint) else 1_000,
                way_id=u * 10 + v,
            )

    response = plan_projected_route(
        _constraints((1, 2), 0.5, (3, 4), 0.5), artifact=_artifact(graph)
    )

    assert response.route.total_km == pytest.approx(0.11)
    assert (
        graph.nodes[start_endpoint]["lon"],
        graph.nodes[start_endpoint]["lat"],
    ) in response.geometry.coordinates
    assert (
        graph.nodes[end_endpoint]["lon"],
        graph.nodes[end_endpoint]["lat"],
    ) in response.geometry.coordinates


def test_identical_handles_return_zero_route_and_two_equal_points():
    graph = _graph()
    _edge(graph, 1, 2, length_m=1_000, way_id=12)
    constraints = _constraints((1, 2), 0.5, (1, 2), 0.5)

    response = plan_projected_route(constraints, artifact=_artifact(graph))

    assert response.route.total_km == 0
    assert response.route.total_locks == 0
    assert response.route.total_minutes == 0
    assert response.route.legs == []
    assert response.route.days == []
    assert response.route.warnings == []
    assert response.geometry.coordinates == [response.geometry.coordinates[0]] * 2


def test_infrastructure_handles_allow_only_edge_endpoints():
    graph = _graph()
    _edge(graph, 1, 2, length_m=1_000, way_id=12, candidate_eligible=False, locks=1)
    artifact = _artifact(graph)

    response = plan_projected_route(_constraints((1, 2), 0, (1, 2), 1), artifact=artifact)

    assert response.route.total_locks == 1
    with pytest.raises(ValueError, match="interior"):
        plan_projected_route(_constraints((1, 2), 0.5, (1, 2), 1), artifact=artifact)


def test_partial_length_and_time_are_proportional_to_source_length():
    graph = _graph()
    _edge(graph, 1, 2, length_m=1_000, way_id=12)

    response = plan_projected_route(
        _constraints((1, 2), 0.1, (1, 2), 0.4), artifact=_artifact(graph)
    )

    assert response.route.total_km == pytest.approx(0.3)
    assert response.route.total_minutes == round(0.3 / CRUISE_KMH * 60)


def test_node_bridge_delay_is_full_on_arrival_and_absent_on_departure():
    graph = _graph()
    graph.nodes[2]["movable_bridge_ids"] = ("node:2",)
    _edge(graph, 1, 2, length_m=1_000, way_id=12)
    artifact = _artifact(graph)

    arrives = plan_projected_route(_constraints((1, 2), 0.5, (1, 2), 1), artifact=artifact)
    departs = plan_projected_route(_constraints((1, 2), 1, (1, 2), 0.5), artifact=artifact)

    assert (
        arrives.route.total_minutes - departs.route.total_minutes
        == DEFAULT_MOVABLE_BRIDGE_DELAY_MIN
    )


def test_projected_planning_does_not_mutate_graph_or_edge_dictionaries():
    graph = _graph()
    _edge(graph, 1, 2, length_m=1_000, way_id=12)
    _edge(graph, 2, 3, length_m=1_000, way_id=23)
    before = copy.deepcopy(graph)

    response = plan_projected_route(
        _constraints((1, 2), 0.3, (2, 3), 0.7), artifact=_artifact(graph)
    )

    assert response.route.graph_source_date == "2026-08-30T00:00:00Z"
    assert graph.nodes == before.nodes
    assert graph.edges == before.edges
