import pickle
from pathlib import Path

import networkx as nx
import pytest
from pound.artifact import ROUTING_ARTIFACT_SCHEMA_VERSION, load_artifact


def test_runtime_loader_checks_version_without_iterating_graph(tmp_path: Path):
    graph = nx.Graph()
    graph.add_edge(1, 2, geometry=[(51.0, -1.0), (51.1, -1.1)])
    payload = {
        "graph": graph,
        "pois": (),
        "gazetteer": {},
        "metadata": {
            "artifact_schema_version": ROUTING_ARTIFACT_SCHEMA_VERSION,
            "artifact_revision": "r1",
            "source": "fixture",
            "fetched_at": "2026-08-30",
            "built_at": "2026-08-30",
            "validation": {},
            "poi_summary": {},
        },
    }
    path = tmp_path / "graph.pkl"
    path.write_bytes(pickle.dumps(payload))

    loaded = load_artifact(path)
    assert loaded.graph is graph or list(loaded.graph.edges) == [(1, 2)]


def test_runtime_loader_rejects_old_payload_shape(tmp_path: Path):
    path = tmp_path / "old.pkl"
    path.write_bytes(pickle.dumps({"graph": nx.Graph(), "pois": (), "metadata": {}}))
    with pytest.raises(ValueError, match="top-level"):
        load_artifact(path)
