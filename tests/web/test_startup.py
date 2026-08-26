import pickle
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import networkx as nx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pound.catalog.artifact import prepare_catalog, write_catalog
from pound.catalog.spatial import (
    MAX_CATALOG_QUERY_WORK,
    MAX_CATALOG_VIEWPORT_SPAN_DEGREES,
    CatalogSpatialIndex,
)
from pound.graph.artifact import InvalidArtifactError, load_artifact, save_artifact
from pound.graph.spatial import GraphSpatialIndex, PoiSpatialIndex
from pound.web.app import _load_web_artifact, create_app
from pound.web.config import WebSettings
from tests.web.conftest import artifact_metadata, catalog_place, write_boat_hire_enrichment


def _settings(artifact_path: Path, static_dir: Path) -> WebSettings:
    return WebSettings(
        artifact_path=artifact_path,
        static_dir=static_dir,
        boat_hire_enrichment_path=write_boat_hire_enrichment(
            artifact_path.with_name("boat-hire.csv"),
            rows=[
                {
                    "source_provider_id": "test-provider",
                    "location_id": "base:test",
                    "exclude": "true",
                }
            ],
        ),
    )


def _write_blob(path: Path, blob: object) -> None:
    with path.open("wb") as artifact_file:
        pickle.dump(blob, artifact_file)


def test_settings_from_env_requires_artifact_path(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("POUND_ARTIFACT_PATH", raising=False)

    with pytest.raises(RuntimeError, match="POUND_ARTIFACT_PATH"):
        WebSettings.from_env()


def test_settings_from_env_requires_boat_hire_enrichment_path(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("POUND_ARTIFACT_PATH", "/tmp/graph.pkl")
    monkeypatch.delenv("POUND_BOAT_HIRE_ENRICHMENT_PATH", raising=False)

    with pytest.raises(RuntimeError, match="POUND_BOAT_HIRE_ENRICHMENT_PATH"):
        WebSettings.from_env()


def test_settings_from_env_reads_paths_and_tuning(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("POUND_ARTIFACT_PATH", "/tmp/graph.pkl")
    monkeypatch.setenv("POUND_STATIC_DIR", "/tmp/client")
    monkeypatch.setenv("POUND_BOAT_HIRE_ENRICHMENT_PATH", "/tmp/boat-hire.csv")
    monkeypatch.setenv("POUND_CANDIDATE_POOL_SIZE", "30")
    monkeypatch.setenv("POUND_GOOGLE_DESTINATION_LIMIT", "12")
    monkeypatch.setenv("POUND_MINIMUM_CANDIDATE_SPACING_M", "125.5")
    monkeypatch.setenv("POUND_CATALOG_PATH", "/tmp/catalog.pkl")
    monkeypatch.setenv("POUND_CATALOG_MAX_KINDS", "4")
    monkeypatch.setenv("POUND_CATALOG_MAX_VIEWPORT_SPAN_DEG", "3.5")
    monkeypatch.setenv("POUND_CATALOG_MAX_RADIUS_M", "1500")
    monkeypatch.setenv("POUND_CATALOG_MAX_ROUTE_VERTICES", "2000")
    monkeypatch.setenv("POUND_CATALOG_QUERY_WORK_BUDGET", "5000")

    settings = WebSettings.from_env()

    assert settings == WebSettings(
        artifact_path=Path("/tmp/graph.pkl"),
        static_dir=Path("/tmp/client"),
        boat_hire_enrichment_path=Path("/tmp/boat-hire.csv"),
        catalog_path=Path("/tmp/catalog.pkl"),
        candidate_pool_size=30,
        google_destination_limit=12,
        minimum_candidate_spacing_m=125.5,
        catalog_max_kinds=4,
        catalog_max_viewport_span_deg=3.5,
        catalog_max_radius_m=1500,
        catalog_max_route_vertices=2000,
        catalog_query_work_budget=5000,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidate_pool_size", 0),
        ("google_destination_limit", -1),
        ("minimum_candidate_spacing_m", -0.1),
        ("catalog_max_kinds", 0),
        ("catalog_max_viewport_span_deg", 0),
        ("catalog_max_viewport_span_deg", MAX_CATALOG_VIEWPORT_SPAN_DEGREES + 0.1),
        ("catalog_max_radius_m", -1),
        ("catalog_max_route_vertices", 0),
        ("catalog_query_work_budget", 0),
        ("catalog_query_work_budget", MAX_CATALOG_QUERY_WORK + 1),
    ],
)
def test_settings_reject_invalid_tuning(field: str, value: int | float, tmp_path: Path):
    values: dict[str, Any] = {
        "artifact_path": tmp_path / "graph.pkl",
        "static_dir": tmp_path / "static",
        "boat_hire_enrichment_path": write_boat_hire_enrichment(tmp_path / "boat-hire.csv"),
    }
    values[field] = value

    with pytest.raises(ValueError, match=field):
        WebSettings(**values)


def test_startup_reports_missing_artifact_path(tmp_path: Path):
    artifact = tmp_path / "missing.pkl"

    with pytest.raises(RuntimeError, match=str(artifact)) as exc_info:
        _load_web_artifact(_settings(artifact, tmp_path / "missing-static"))

    assert isinstance(exc_info.value.__cause__, InvalidArtifactError)
    assert isinstance(exc_info.value.__cause__.__cause__, FileNotFoundError)


def test_startup_reports_invalid_pickle(tmp_path: Path):
    artifact = tmp_path / "invalid.pkl"
    artifact.write_text("not a pickle")

    with pytest.raises(RuntimeError, match=str(artifact)) as exc_info:
        _load_web_artifact(_settings(artifact, tmp_path / "missing-static"))

    assert exc_info.value.__cause__ is not None


def test_startup_reports_malformed_artifact_wrapper(tmp_path: Path):
    artifact = tmp_path / "malformed.pkl"
    _write_blob(artifact, ["not", "an", "artifact", "mapping"])

    with pytest.raises(RuntimeError) as exc_info:
        _load_web_artifact(_settings(artifact, tmp_path / "missing-static"))

    assert str(artifact) in str(exc_info.value)
    assert "load" in str(exc_info.value).lower()
    assert "rebuild" in str(exc_info.value).lower()
    assert isinstance(exc_info.value.__cause__, InvalidArtifactError)


@pytest.mark.parametrize(
    ("blob", "missing"),
    [
        ({"metadata": {"artifact_revision": "rev"}}, "graph"),
        ({"graph": nx.Graph()}, "metadata"),
    ],
)
def test_startup_rejects_incomplete_artifact(tmp_path: Path, blob: dict[str, object], missing: str):
    artifact = tmp_path / "incomplete.pkl"
    _write_blob(artifact, blob)

    with pytest.raises(RuntimeError, match=rf"{artifact}.*{missing}.*[Rr]ebuild"):
        _load_web_artifact(_settings(artifact, tmp_path / "missing-static"))


@pytest.mark.parametrize("revision", [None, ""])
def test_startup_rejects_missing_or_falsey_revision(tmp_path: Path, revision: str | None):
    artifact = tmp_path / "revisionless.pkl"
    metadata = artifact_metadata("temporary")
    metadata["artifact_revision"] = revision
    _write_blob(artifact, {"graph": nx.Graph(), "pois": [], "metadata": metadata})

    with pytest.raises(RuntimeError, match=rf"{artifact}.*artifact_revision.*[Rr]ebuild"):
        _load_web_artifact(_settings(artifact, tmp_path / "missing-static"))


def test_startup_attaches_artifact_state_and_loads_once(tmp_path: Path):
    artifact = tmp_path / "graph.pkl"
    graph = nx.Graph(marker={"stable": True})
    save_artifact(graph, [], artifact, artifact_metadata("revision-7"))
    settings = _settings(artifact, tmp_path / "missing-static")
    app = create_app(settings)

    with (
        patch("pound.web.app.load_artifact", wraps=load_artifact) as load,
        patch("pound.web.app.GraphSpatialIndex", wraps=GraphSpatialIndex) as build_index,
        patch("pound.web.app.PoiSpatialIndex", wraps=PoiSpatialIndex) as build_poi_index,
    ):
        with TestClient(app) as client:
            assert app.state.graph.nodes == graph.nodes
            assert app.state.artifact.graph is app.state.graph
            assert not app.state.artifact.pois
            assert app.state.pois is app.state.artifact.pois
            assert app.state.metadata["source"] == "test"
            assert app.state.metadata is app.state.artifact.metadata
            assert app.state.artifact_revision == "revision-7"
            assert app.state.settings is settings
            assert app.state.boat_hire_anchors == ()
            assert app.state.network_unavailable is True
            assert isinstance(app.state.spatial_index, GraphSpatialIndex)
            assert isinstance(app.state.poi_spatial_index, PoiSpatialIndex)
            assert client.get("/api/health").json() == {
                "status": "healthy",
                "artifact_revision": "revision-7",
                "catalog_revision": None,
                "catalog_status": "unavailable",
            }
            client.get("/api/health")

    load.assert_called_once_with(artifact)
    build_index.assert_called_once_with(app.state.graph)
    build_poi_index.assert_called_once_with(app.state.pois)
    assert app.state.catalog_status == "unavailable"
    assert app.state.catalog_revision is None
    assert app.state.catalog_spatial_index is None


def test_startup_loads_catalog_after_routing_artifact(tmp_path: Path):
    artifact_path = tmp_path / "graph.pkl"
    catalog_path = tmp_path / "catalog.pkl"
    save_artifact(nx.Graph(), [], artifact_path, artifact_metadata("route-revision"))
    catalog = prepare_catalog(
        (catalog_place("pub", 1, 51.0, -1.0),),
        {
            "source": "catalog-test",
            "fetched_at": "2026-07-11T00:00:00Z",
            "built_at": "2026-07-12T00:00:00Z",
            "inventory_summary": {},
            "build_summary": {},
        },
    )
    write_catalog(catalog, catalog_path)
    settings = WebSettings(
        artifact_path=artifact_path,
        static_dir=tmp_path / "static",
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
        catalog_path=catalog_path,
    )

    with TestClient(create_app(settings)) as client:
        app = cast(FastAPI, client.app)
        assert app.state.catalog_status == "available"
        assert app.state.catalog_revision == catalog.metadata["catalog_revision"]
        assert isinstance(app.state.catalog_spatial_index, CatalogSpatialIndex)
        assert client.get("/api/health").json() == {
            "status": "healthy",
            "artifact_revision": "route-revision",
            "catalog_revision": catalog.metadata["catalog_revision"],
            "catalog_status": "available",
        }


def test_incompatible_catalog_schema_degrades_without_breaking_startup(
    tmp_path: Path,
):
    artifact_path = tmp_path / "graph.pkl"
    catalog_path = tmp_path / "catalog.pkl"
    save_artifact(
        nx.Graph(),
        [],
        artifact_path,
        artifact_metadata("route-revision"),
    )
    catalog = prepare_catalog(
        (catalog_place("pub", 1, 51.0, -1.0),),
        {
            "source": "catalog-test",
            "fetched_at": "2026-07-11T00:00:00Z",
            "built_at": "2026-07-12T00:00:00Z",
            "inventory_summary": {},
            "build_summary": {},
        },
    )
    _write_blob(
        catalog_path,
        {
            "places": list(catalog.places),
            "metadata": {
                **catalog.metadata,
                "catalog_schema_version": 1,
            },
        },
    )
    settings = WebSettings(
        artifact_path=artifact_path,
        static_dir=tmp_path / "static",
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
        catalog_path=catalog_path,
    )

    with TestClient(create_app(settings)) as client:
        app = cast(FastAPI, client.app)
        assert client.get("/api/health").json() == {
            "status": "degraded",
            "artifact_revision": "route-revision",
            "catalog_revision": None,
            "catalog_status": "unavailable",
        }
        assert app.state.graph.number_of_nodes() == 0


def test_corrupt_catalog_degrades_health_without_breaking_routing_startup(tmp_path: Path):
    artifact_path = tmp_path / "graph.pkl"
    catalog_path = tmp_path / "catalog.pkl"
    save_artifact(nx.Graph(), [], artifact_path, artifact_metadata("route-revision"))
    catalog_path.write_text("not a catalog")
    settings = WebSettings(
        artifact_path=artifact_path,
        static_dir=tmp_path / "static",
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
        catalog_path=catalog_path,
    )

    with TestClient(create_app(settings)) as client:
        app = cast(FastAPI, client.app)
        assert app.state.artifact_revision == "route-revision"
        assert app.state.catalog_status == "unavailable"
        assert app.state.catalog_revision is None
        assert client.get("/api/health").json() == {
            "status": "degraded",
            "artifact_revision": "route-revision",
            "catalog_revision": None,
            "catalog_status": "unavailable",
        }


def test_missing_catalog_degrades_health_without_breaking_routing_startup(tmp_path: Path):
    artifact_path = tmp_path / "graph.pkl"
    catalog_path = tmp_path / "missing-catalog.pkl"
    save_artifact(nx.Graph(), [], artifact_path, artifact_metadata("route-revision"))
    settings = WebSettings(
        artifact_path=artifact_path,
        static_dir=tmp_path / "static",
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
        catalog_path=catalog_path,
    )

    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health").json()["status"] == "degraded"
        assert client.get("/api/health").json()["catalog_status"] == "unavailable"


def test_startup_does_not_mutate_loaded_artifact_fields(tmp_path: Path):
    artifact_path = tmp_path / "graph.pkl"
    graph = nx.Graph(marker={"stable": True})
    metadata = artifact_metadata("revision-immutable")
    save_artifact(graph, [], artifact_path, metadata)
    loaded = load_artifact(artifact_path)

    with patch("pound.web.app.load_artifact", return_value=loaded):
        with TestClient(create_app(_settings(artifact_path, tmp_path / "static"))):
            pass

    assert loaded.graph.graph == {"marker": {"stable": True}}
    assert loaded.metadata == metadata
    assert not loaded.pois
