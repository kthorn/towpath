from pathlib import Path
from types import SimpleNamespace

from pound_build.review import cli
from pound_build.review.store import load_document

from .fixtures import catalog_with, place


def test_generate_command_writes_requested_path(tmp_path, monkeypatch):
    output = tmp_path / "review.json"
    loaded_graph_paths = []
    monkeypatch.setattr(
        cli,
        "load_catalog",
        lambda path: catalog_with(place("marina", "Canal Boat Hire", osm_id=1)),
    )
    monkeypatch.setattr(
        cli,
        "load_artifact",
        lambda path: (loaded_graph_paths.append(path), SimpleNamespace(graph=object()))[1],
    )
    monkeypatch.setattr(cli, "GraphSpatialIndex", lambda graph: SimpleNamespace(graph=graph))
    monkeypatch.setattr(cli, "filter_catalog_to_network", lambda catalog, index: catalog)

    assert (
        cli.main(
            [
                "generate",
                "--catalog",
                "catalog.pkl",
                "--graph",
                "graph.pkl",
                "--out",
                str(output),
            ]
        )
        == 0
    )
    assert loaded_graph_paths == [Path("graph.pkl")]
    assert load_document(output).records


def test_serve_command_uses_requested_host_and_port(tmp_path, monkeypatch):
    called = {}

    class FakeApp:
        def run(self, **kwargs):
            called.update(kwargs)

    monkeypatch.setattr("pound_build.review.cli.create_app", lambda path: FakeApp())

    assert (
        cli.main(["serve", "--review", "review.json", "--host", "127.0.0.1", "--port", "5050"]) == 0
    )
    assert called == {"host": "127.0.0.1", "port": 5050, "debug": False}
