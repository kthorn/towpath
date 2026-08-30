from pathlib import Path

from pound_build.catalog.reader import read_catalog
from pound_build.ingest.ir import OsmElementType

FIXTURE = Path("packages/pound-core/tests/fixtures/tiny_bulk.osm")


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

    by_identity = {(place.osm_type, place.osm_id): place for place in places}
    assert by_identity[(OsmElementType.NODE, 2002)].geometry_source == "point"
    assert by_identity[(OsmElementType.RELATION, 2301)].geometry_source == "area"
    assert by_identity[(OsmElementType.WAY, 2101)].geometry_source == "area"


def test_read_catalog_excludes_artwork_metadata_tags(tmp_path):
    source = tmp_path / "artwork.osm"
    source.write_text(
        '<?xml version="1.0"?><osm version="0.6">'
        '<node id="1" lat="51.75" lon="-1.26">'
        '<tag k="tourism" v="artwork"/><tag k="name" v="Boat Sculpture"/>'
        "</node>"
        '<node id="2" lat="51.75" lon="-1.26">'
        '<tag k="tourism" v="attraction"/><tag k="artist_name" v="A. Artist"/>'
        '<tag k="name" v="Artist Attraction"/></node>'
        '<node id="3" lat="51.75" lon="-1.26">'
        '<tag k="tourism" v="attraction"/><tag k="artwork_type" v="sculpture"/>'
        '<tag k="name" v="Sculpture Attraction"/></node>'
        "</osm>"
    )

    places = read_catalog(source)

    assert not places
    assert places.report["excluded_by_reason"]["artwork"] == 3


def test_read_catalog_excludes_artwork_area_once(tmp_path):
    """A closed way tagged artwork must be excluded once, not twice (source + area)."""
    source = tmp_path / "artwork_area.osm"
    source.write_text(
        '<?xml version="1.0"?><osm version="0.6">'
        '<node id="2" lat="51.751" lon="-1.261"/>'
        '<node id="3" lat="51.752" lon="-1.26"/>'
        '<node id="4" lat="51.751" lon="-1.259"/>'
        '<way id="10">'
        '<nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="2"/>'
        '<tag k="tourism" v="artwork"/><tag k="name" v="Area Sculpture"/>'
        "</way>"
        "</osm>"
    )

    places = read_catalog(source)
    assert not places
    assert places.report["excluded_by_reason"]["artwork"] == 1


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


def test_read_catalog_reports_inactive_unnamed_duplicate_and_malformed_records(
    tmp_path,
):
    source = tmp_path / "catalog.osm"
    source.write_text(
        FIXTURE.read_text().replace(
            "</osm>",
            '<node id="2002" lat="51.7501" lon="-1.2601">'
            '<tag k="amenity" v="pub"/>'
            '<tag k="name" v="Towpath Arms"/></node>'
            '<node id="9001" lat="51.7" lon="-1.2">'
            '<tag k="amenity" v="pub"/></node>'
            '<node id="9002" lat="51.7" lon="-1.2">'
            '<tag k="amenity" v="pub"/>'
            '<tag k="name" v="Closed Arms"/>'
            '<tag k="disused" v="yes"/></node>'
            '<relation id="9003">'
            '<member type="way" ref="999999" role="outer"/>'
            '<tag k="type" v="multipolygon"/>'
            '<tag k="amenity" v="pub"/>'
            '<tag k="name" v="Broken Arms"/></relation>'
            "</osm>",
        )
    )

    places = read_catalog(source)
    report = places.report

    assert report["duplicate"] >= 1
    assert report["inactive"] >= 1
    assert report["malformed"] >= 1
    assert report["excluded_by_reason"]["unnamed"] >= 1
    assert all(
        place.metadata.links[-1].url == f"https://www.openstreetmap.org/"
        f"{place.osm_type.value}/{place.osm_id}"
        for place in places
    )


def test_read_catalog_is_independent_of_graph_bound_poi_fields():
    place = read_catalog(FIXTURE)[0]

    assert not hasattr(place, "nearest_edge")
    assert not hasattr(place, "nearest_node_uid")
    assert not hasattr(place, "projected_lat")
    assert not hasattr(place, "projected_lon")
