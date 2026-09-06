import pickle
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]
from pound.catalog.artifact import (  # pyright: ignore[reportMissingImports]
    InvalidCatalogError,
    load_catalog,
)
from pound.catalog.metadata import CatalogMetadata  # pyright: ignore[reportMissingImports]
from pound.catalog.models import CatalogPlace  # pyright: ignore[reportMissingImports]
from pound.models import OsmElementType  # pyright: ignore[reportMissingImports]
from pound_build.catalog.artifact import prepare_catalog, write_catalog
from shapely import wkb
from shapely.geometry import Point


def _place(*, osm_id: int = 1, kind: str = "pub") -> CatalogPlace:
    return CatalogPlace(
        osm_type=OsmElementType.NODE,
        osm_id=osm_id,
        kind=kind,
        name="The Navigation",
        lat=51.75,
        lon=-1.25,
        metadata=CatalogMetadata(name="The Navigation"),
        geometry_wkb=wkb.dumps(Point(-1.25, 51.75), output_dimension=2),
        geometry_source="point",
    )


def _metadata() -> dict:
    return {
        "source": "packages/pound-core/tests/fixtures/tiny_bulk.osm",
        "fetched_at": "2026-07-22T12:00:00+00:00",
        "built_at": "2026-07-22T12:01:00+00:00",
        "inventory_summary": {"counts_by_kind": {"pub": 1}},
        "build_summary": {"scanned": 1, "emitted": 1},
    }


def test_catalog_artifact_has_exact_payload_and_round_trips(tmp_path: Path):
    artifact = prepare_catalog([_place()], _metadata())
    path = tmp_path / "catalog.pkl"
    write_catalog(artifact, path)

    with path.open("rb") as stream:
        assert set(pickle.load(stream)) == {"places", "metadata"}

    loaded = load_catalog(path)
    assert loaded == artifact
    assert loaded.metadata["catalog_revision"] != ""
    assert loaded.metadata["catalog_schema_version"] == 3
    assert loaded.metadata["attribution"] == "© OpenStreetMap contributors"
    assert loaded.places[0].geometry_wkb == artifact.places[0].geometry_wkb
    assert loaded.places[0].metadata == artifact.places[0].metadata


def _write_catalog_payload(
    path: Path,
    artifact,
    **metadata_changes,
) -> None:
    metadata = {**artifact.metadata, **metadata_changes}
    with path.open("wb") as stream:
        pickle.dump({"places": list(artifact.places), "metadata": metadata}, stream)


@pytest.mark.parametrize("version", [1, 2, "3", True, 3.0])
def test_catalog_loader_rejects_incompatible_schema_versions(
    tmp_path: Path,
    version,
):
    artifact = prepare_catalog([_place()], _metadata())
    path = tmp_path / "incompatible.pkl"
    _write_catalog_payload(path, artifact, catalog_schema_version=version)

    with pytest.raises(InvalidCatalogError, match="catalog_schema_version"):
        load_catalog(path)


@pytest.mark.parametrize("version", [True, 3.0])
def test_catalog_builder_rejects_non_integer_schema_version(version):
    metadata = _metadata()
    metadata["catalog_schema_version"] = version

    with pytest.raises(InvalidCatalogError, match="catalog_schema_version"):
        prepare_catalog([_place()], metadata)


def test_catalog_loader_rejects_missing_schema_version(tmp_path: Path):
    artifact = prepare_catalog([_place()], _metadata())
    metadata = dict(artifact.metadata)
    metadata.pop("catalog_schema_version")
    path = tmp_path / "missing-version.pkl"
    with path.open("wb") as stream:
        pickle.dump({"places": list(artifact.places), "metadata": metadata}, stream)

    with pytest.raises(InvalidCatalogError, match="catalog_schema_version"):
        load_catalog(path)


@pytest.mark.parametrize("attribution", ["OpenStreetMap", "", None])
def test_catalog_builder_rejects_wrong_attribution(attribution):
    metadata = _metadata()
    metadata["attribution"] = attribution

    with pytest.raises(InvalidCatalogError, match="metadata.attribution"):
        prepare_catalog([_place()], metadata)


def test_catalog_artifact_rejects_bad_metadata_records_and_duplicate_identity(tmp_path):
    metadata = _metadata()
    metadata["catalog_revision"] = "independent-revision"
    with pytest.raises(InvalidCatalogError):
        prepare_catalog([_place(), _place()], metadata)

    bad_metadata = _metadata()
    bad_metadata["build_summary"] = {"peak_rss": float("nan")}
    with pytest.raises(InvalidCatalogError):
        prepare_catalog([_place()], bad_metadata)

    malformed = tmp_path / "malformed.pkl"
    with malformed.open("wb") as stream:
        pickle.dump(
            {
                "places": [{"kind": "pub"}],
                "metadata": {"catalog_revision": "x"},
            },
            stream,
        )
    with pytest.raises(InvalidCatalogError):
        load_catalog(malformed)


def test_catalog_artifact_does_not_require_graph_attachment_fields():
    artifact = prepare_catalog([_place()], _metadata())

    assert not hasattr(artifact.places[0], "nearest_edge")
    assert not hasattr(artifact.places[0], "nearest_node_uid")
    assert not hasattr(artifact.places[0], "projected_lat")
