from pathlib import Path

import networkx as nx
from fastapi.testclient import TestClient
from pound.graph.artifact import save_artifact
from pound.web.app import create_app
from pound.web.config import WebSettings

from tests.web.conftest import artifact_metadata, write_boat_hire_enrichment


def _client(tmp_path: Path, static_dir: Path) -> TestClient:
    artifact = tmp_path / "graph.pkl"
    save_artifact(nx.Graph(), [], artifact, artifact_metadata("static-test"))
    return TestClient(
        create_app(
            WebSettings(
                artifact_path=artifact,
                static_dir=static_dir,
                boat_hire_enrichment_path=write_boat_hire_enrichment(
                    tmp_path / "boat-hire.csv",
                    rows=[
                        {
                            "source_provider_id": "test-provider",
                            "location_id": "base:test",
                            "exclude": "true",
                        }
                    ],
                ),
            )
        )
    )


def test_static_site_serves_index_assets_and_client_routes(tmp_path: Path):
    static_dir = tmp_path / "dist"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text("<h1>Pound map</h1>")
    (static_dir / "assets" / "app.js").write_text("console.log('map')")

    with _client(tmp_path, static_dir) as client:
        assert client.get("/").text == "<h1>Pound map</h1>"
        asset = client.get("/assets/app.js")
        assert asset.status_code == 200
        assert "javascript" in asset.headers["content-type"]
        assert client.get("/journeys/oxford").text == "<h1>Pound map</h1>"

        settings = client.get("/settings")
        assert settings.status_code == 200
        assert settings.text == "<h1>Pound map</h1>"
        assert settings.headers["content-type"].startswith("text/html")


def test_missing_static_assets_are_not_replaced_by_index(tmp_path: Path):
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<h1>Pound map</h1>")

    with _client(tmp_path, static_dir) as client:
        assert client.get("/assets/missing.js").status_code == 404
        assert client.get("/assets/missing").status_code == 404
        assert client.get("/favicon.ico").status_code == 404


def test_api_routes_take_precedence_over_spa_fallback(tmp_path: Path):
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<h1>Pound map</h1>")

    with _client(tmp_path, static_dir) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["artifact_revision"] == "static-test"
        missing = client.get("/api/not-a-route")
        assert missing.status_code == 404
        assert "Pound map" not in missing.text
        assert client.get("/api").status_code == 404


def test_static_files_cannot_shadow_api_namespace(tmp_path: Path):
    static_dir = tmp_path / "dist"
    (static_dir / "api").mkdir(parents=True)
    (static_dir / "index.html").write_text("<h1>Pound map</h1>")
    (static_dir / "api" / "leak").write_text("not an API response")

    with _client(tmp_path, static_dir) as client:
        response = client.get("/api/leak")
        assert response.status_code == 404
        assert "not an API response" not in response.text


def test_static_delivery_rejects_path_traversal(tmp_path: Path):
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<h1>Pound map</h1>")
    (tmp_path / "secret.txt").write_text("not public")

    with _client(tmp_path, static_dir) as client:
        response = client.get("/%2e%2e/secret.txt")
        assert response.status_code == 404
        assert "not public" not in response.text


def test_static_delivery_does_not_follow_index_symlink_outside_root(tmp_path: Path):
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    secret = tmp_path / "secret.html"
    secret.write_text("not public")
    (static_dir / "index.html").symlink_to(secret)

    with _client(tmp_path, static_dir) as client:
        response = client.get("/")
        assert response.status_code == 404
        assert "not public" not in response.text


def test_missing_static_directory_keeps_api_available(tmp_path: Path):
    with _client(tmp_path, tmp_path / "missing-dist") as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/").status_code == 404
