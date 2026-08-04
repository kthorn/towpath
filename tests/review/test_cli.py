from pound.review.cli import main
from pound.review.store import load_document
from tests.review.fixtures import catalog_with, place


def test_generate_command_writes_requested_path(tmp_path, monkeypatch):
    output = tmp_path / "review.json"
    monkeypatch.setattr(
        "pound.review.cli.load_catalog",
        lambda path: catalog_with(place("marina", "Canal Boat Hire", osm_id=1)),
    )

    assert main(["generate", "--catalog", "catalog.pkl", "--out", str(output)]) == 0
    assert load_document(output).records


def test_serve_command_uses_requested_host_and_port(tmp_path, monkeypatch):
    called = {}

    class FakeApp:
        def run(self, **kwargs):
            called.update(kwargs)

    monkeypatch.setattr("pound.review.cli.create_app", lambda path: FakeApp())

    assert main(["serve", "--review", "review.json", "--host", "127.0.0.1", "--port", "5050"]) == 0
    assert called == {"host": "127.0.0.1", "port": 5050, "debug": False}
