from shapely import wkb
from shapely.geometry import Point

from pound.catalog.artifact import prepare_catalog
from pound.catalog.metadata import CatalogMetadata, NormalizedLink
from pound.catalog.models import CatalogPlace
from pound.ingest.ir import OsmElementType
from pound.review.models import ReviewDocument, ReviewLink, ReviewRecord


def place(
    kind,
    name,
    *,
    operator=None,
    osm_id=None,
    website=None,
    lat=51.0,
    lon=-1.0,
):
    osm_id = osm_id or 1000 + sum(map(ord, name))
    osm_url = f"https://www.openstreetmap.org/node/{osm_id}"
    links = [NormalizedLink(label="OpenStreetMap", url=osm_url)]
    if website:
        links.insert(0, NormalizedLink(label="Website", url=website))
    return CatalogPlace(
        osm_type=OsmElementType.NODE,
        osm_id=osm_id,
        kind=kind,
        name=name,
        lat=lat,
        lon=lon,
        metadata=CatalogMetadata(name=name, operator=operator, links=links),
        geometry_wkb=wkb.dumps(Point(lon, lat), output_dimension=2),
        geometry_source="point",
    )


def catalog_with(*places):
    return prepare_catalog(
        places,
        {
            "source": "test-catalog",
            "fetched_at": "2026-08-03T00:00:00Z",
            "built_at": "2026-08-03T00:00:00Z",
            "inventory_summary": {},
            "build_summary": {},
        },
    )


def sample_record(*, decision=None):
    return ReviewRecord(
        identity="node/1/marina",
        osm_type="node",
        osm_id=1,
        kind="marina",
        name="Test Marina",
        lat=51.0,
        lon=-1.0,
        metadata={"operator": "Test Operator"},
        links=[ReviewLink(label="OpenStreetMap", url="https://www.openstreetmap.org/node/1")],
        website_urls=[],
        osm_url="https://www.openstreetmap.org/node/1",
        likelihood_score=10,
        rank=1,
        likelihood_reasons=["marina kind prior"],
        decision=decision,
        reviewed_at=None,
    )


def sample_document(*, decision=None):
    return ReviewDocument(
        format_version=1,
        source_artifact="test-catalog.pkl",
        catalog_revision="catalog-test",
        generated_at="2026-08-03T00:00:00Z",
        records=[sample_record(decision=decision)],
    )
