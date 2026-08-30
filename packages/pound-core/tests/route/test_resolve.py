import networkx as nx
import pytest  # pyright: ignore[reportMissingImports]
from pound.artifact import RuntimeArtifact
from pound.graph.spatial import CandidateSpatialIndex
from pound.route.resolve import resolve_place


def _artifact_with_gazetteer(gaz: dict, *, edge: tuple[int, int] = (1, 2)):
    graph = nx.Graph()
    graph.add_node(edge[0], lat=51.0, lon=-1.0)
    graph.add_node(edge[1], lat=51.0, lon=-0.98)
    graph.add_edge(
        *edge,
        geometry=[
            (graph.nodes[edge[0]]["lat"], graph.nodes[edge[0]]["lon"]),
            (graph.nodes[edge[1]]["lat"], graph.nodes[edge[1]]["lon"]),
        ],
    )
    return RuntimeArtifact(graph=graph, pois=(), gazetteer=gaz, metadata={})


def test_resolve_place_projects_gazetteer_coordinate_to_compact_edge_midpoint():
    artifact = _artifact_with_gazetteer({"Oxford": (51.0, -0.99)})
    index = CandidateSpatialIndex(artifact.graph)

    handle = resolve_place("oXfOrD", artifact, index)

    assert handle.edge == (1, 2)
    assert handle.fraction == pytest.approx(0.5, abs=2e-6)


def test_resolve_place_rejects_gazetteer_coordinate_beyond_tolerance():
    artifact = _artifact_with_gazetteer({"Pub": (51.001, -1.0)})

    with pytest.raises(ValueError, match="not within 50.0 m"):
        resolve_place(  # pyright: ignore[reportCallIssue]
            "Pub",
            artifact,
            CandidateSpatialIndex(artifact.graph),  # pyright: ignore[reportCallIssue]
        )


def test_resolve_place_unknown_name_raises_with_count():
    artifact = _artifact_with_gazetteer({"Oxford": (51.0, -0.99)})

    with pytest.raises(ValueError, match="not found in gazetteer.*covers 1 places"):
        resolve_place(  # pyright: ignore[reportCallIssue]
            "Narnia",
            artifact,
            CandidateSpatialIndex(artifact.graph),  # pyright: ignore[reportCallIssue]
        )


def test_resolve_place_ambiguous_name_raises():
    artifact = _artifact_with_gazetteer({"Newton": [(52.0, -1.0), (53.0, -2.0)]})

    with pytest.raises(ValueError, match="matches 2 places"):
        resolve_place(  # pyright: ignore[reportCallIssue]
            "Newton",
            artifact,
            CandidateSpatialIndex(artifact.graph),  # pyright: ignore[reportCallIssue]
        )
