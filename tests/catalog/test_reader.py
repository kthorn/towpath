from pathlib import Path

from pound.catalog.reader import read_catalog
from pound.ingest.ir import OsmElementType

FIXTURE = Path("tests/fixtures/tiny_bulk.osm")


def test_read_catalog_emits_all_supported_geometry_records_deterministically():
    places = read_catalog(FIXTURE)

    assert [(place.kind, place.name) for place in places] == [
        ("water_point", "Canal Tap"),
        ("pub", "Towpath Arms"),
        ("supermarket", "Food"),
        ("museum", "Canal Museum"),
        ("fuel", "Fuel Island"),
        ("marina", "Basin"),
        ("cafe", "Concave Cafe"),
    ]
    assert [place.geometry_source for place in places] == [
        "point",
        "point",
        "point",
        "point",
        "area",
        "area",
        "area",
    ]
    assert all(len(place.geometry_wkb) > 0 for place in places)
    assert all(
        place.metadata.links[-1].url
        == f"https://www.openstreetmap.org/{place.osm_type.value}/{place.osm_id}"
        for place in places
    )
    assert len({place.identity for place in places}) == len(places)


def test_read_catalog_assembles_linear_way_geometry(tmp_path):
    source = tmp_path / "linear.osm"
    source.write_text(
        FIXTURE.read_text().replace(
            "</osm>",
            '<node id="9101" lat="51.7" lon="-1.2"/>'
            '<node id="9102" lat="51.71" lon="-1.21"/>'
            '<way id="9103"><nd ref="9101"/><nd ref="9102"/>'
            '<tag k="mooring" v="yes"/><tag k="name" v="Linear Mooring"/></way>'
            "</osm>",
        )
    )

    places = read_catalog(source)

    linear = next(place for place in places if place.osm_id == 9103)
    assert linear.geometry_source == "line"
    assert linear.kind == "mooring"


def test_read_catalog_rejects_transport_pedestrian_inactive_and_malformed_objects(tmp_path):
    source = tmp_path / "catalog.osm"
    source.write_text(
        FIXTURE.read_text().replace(
            "</osm>",
            '<node id="2002" lat="51.7501" lon="-1.2601">'
            '<tag k="amenity" v="pub"/><tag k="name" v="Towpath Arms"/></node>'
            '<node id="9001" lat="51.7" lon="-1.2">'
            '<tag k="amenity" v="pub"/><tag k="name" v="Towpath Arms"/></node>'
            '<node id="9002" lat="51.7" lon="-1.2">'
            '<tag k="amenity" v="pub"/><tag k="name" v="Closed Arms"/>'
            '<tag k="disused" v="yes"/></node>'
            '<node id="9003" lat="51.7" lon="-1.2">'
            '<tag k="amenity" v="pub"/><tag k="name" v="&lt;unsafe&gt;"/></node>'
            "</osm>",
        )
    )

    places = read_catalog(source)

    identities = {place.identity for place in places}
    assert (OsmElementType.NODE, 9001, "pub") in identities
    assert (OsmElementType.NODE, 9002, "pub") not in identities
    assert (OsmElementType.NODE, 9003, "pub") not in identities


def test_read_catalog_is_independent_of_graph_bound_poi_fields():
    place = read_catalog(FIXTURE)[0]

    assert not hasattr(place, "nearest_edge")
    assert not hasattr(place, "nearest_node_uid")
    assert not hasattr(place, "projected_lat")
    assert not hasattr(place, "projected_lon")
