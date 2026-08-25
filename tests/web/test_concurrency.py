import copy
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient


def test_concurrent_routes_are_deterministic_and_do_not_mutate_graph(web_client: TestClient):
    graph = web_client.app.state.graph
    before_graph = copy.deepcopy(graph.graph)
    before_nodes = copy.deepcopy(dict(graph.nodes(data=True)))
    before_edges = copy.deepcopy({(u, v): data for u, v, data in graph.edges(data=True)})
    payloads = [
        {
            "start_uid": 1,
            "end_uid": 3,
            "artifact_revision": "revision-test",
            "hours_per_day": 6,
            "boat_beam_m": beam,
        }
        for beam in (2.0, 4.0, 2.0, 4.0, 2.0, 4.0)
    ]

    def route(payload: dict) -> tuple[int, dict]:
        response = web_client.post("/api/canal-route", json=payload)
        return response.status_code, response.json()

    expected_by_beam = {
        beam: route(next(payload for payload in payloads if payload["boat_beam_m"] == beam))
        for beam in {payload["boat_beam_m"] for payload in payloads}
    }

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(route, payloads))

    assert results == [expected_by_beam[payload["boat_beam_m"]] for payload in payloads]

    successes = [body for status, body in results if status == 200]
    failures = [body for status, body in results if status == 422]
    assert len(successes) == len(failures) == 3
    assert all(body == successes[0] for body in successes)
    assert all(body == failures[0] for body in failures)
    assert all(body["route"]["access_segments"] == [] for body in successes)
    assert successes[0]["route"]["warnings"] == []
    assert failures[0]["detail"]["code"] == "route_unavailable"
    assert graph.graph == before_graph
    assert dict(graph.nodes(data=True)) == before_nodes
    assert {(u, v): data for u, v, data in graph.edges(data=True)} == before_edges


def test_concurrent_candidates_share_and_do_not_mutate_spatial_index(
    web_client: TestClient,
):
    spatial_index = web_client.app.state.spatial_index
    before = (
        spatial_index.node_uids,
        spatial_index.node_points,
        spatial_index.node_tree,
        spatial_index.edge_keys,
        spatial_index.edge_lines,
        spatial_index.edge_tree,
    )
    payloads = [{"lat": 51.0 + offset, "lon": -1.0} for offset in (0, 0.001) * 3]

    def candidates(payload: dict[str, float]) -> tuple[int, dict]:
        response = web_client.post("/api/canal-candidates", json=payload)
        return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(candidates, payloads))

    assert all(status == 200 for status, _ in results)
    assert spatial_index is web_client.app.state.spatial_index
    assert before == (
        spatial_index.node_uids,
        spatial_index.node_points,
        spatial_index.node_tree,
        spatial_index.edge_keys,
        spatial_index.edge_lines,
        spatial_index.edge_tree,
    )
