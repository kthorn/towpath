import pytest
from pound.catalog.metadata import NormalizedLink
from pound.catalog.models import CatalogAddress, CatalogMetadata, CatalogPlace
from pound.ingest.ir import OsmElementType
from pydantic import ValidationError


def _metadata() -> CatalogMetadata:
    return CatalogMetadata(
        name="The Navigation",
        links=[NormalizedLink(label="Website", url="https://example.test")],
    )


def test_catalog_place_is_strict_and_exposes_stable_identity():
    place = CatalogPlace(
        osm_type=OsmElementType.WAY,
        osm_id=42,
        kind="pub",
        name="The Navigation",
        lat=51.75,
        lon=-1.25,
        metadata=_metadata(),
        geometry_wkb=b"normalized-wkb",
        geometry_source="line",
    )

    assert place.identity == (OsmElementType.WAY, 42, "pub")
    assert place.metadata.links[0].url == "https://example.test"

    with pytest.raises(ValidationError):
        CatalogPlace.model_validate(
            {
                "osm_type": OsmElementType.WAY,
                "osm_id": 42,
                "kind": "pub",
                "name": "The Navigation",
                "lat": 51.75,
                "lon": -1.25,
                "metadata": _metadata(),
                "geometry_wkb": b"normalized-wkb",
                "geometry_source": "line",
                "unexpected": "must be rejected",
            }
        )


def test_catalog_place_rejects_invalid_identity_coordinates_and_geometry_source():
    values = {
        "osm_type": OsmElementType.NODE,
        "osm_id": 1,
        "kind": "cafe",
        "name": "Cafe",
        "lat": 51.0,
        "lon": 0.0,
        "metadata": _metadata(),
        "geometry_wkb": b"wkb",
        "geometry_source": "point",
    }
    for field, value in (("osm_id", 0), ("lat", 91), ("lon", -181), ("geometry_source", "bad")):
        with pytest.raises(ValidationError):
            CatalogPlace(**{**values, field: value})

    with pytest.raises(ValidationError):
        CatalogPlace(**{**values, "kind": "unknown"})


def test_catalog_metadata_forbids_raw_tags_and_validates_nested_address():
    metadata = CatalogMetadata(
        name="Shop",
        address=CatalogAddress(street="Canal Street", city="Oxford"),
        links=[],
        kind_details={"stock_hint": "provisions"},
    )
    assert metadata.address is not None
    assert metadata.address.city == "Oxford"
    assert metadata.kind_details["stock_hint"] == "provisions"

    with pytest.raises(ValidationError):
        CatalogMetadata.model_validate({"name": "Shop", "links": [], "source": "mapper-only"})


def test_catalog_contract_excludes_graph_and_commercial_provider_fields():
    forbidden_fields = {
        "google_place_id",
        "nearest_edge",
        "nearest_node_uid",
        "projected_lat",
        "projected_lon",
        "provider",
        "provider_id",
        "rating",
        "reviews",
    }

    assert forbidden_fields.isdisjoint(CatalogPlace.model_fields)
    assert forbidden_fields.isdisjoint(CatalogMetadata.model_fields)
