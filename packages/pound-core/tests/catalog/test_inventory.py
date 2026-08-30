from pathlib import Path

from pound.catalog.inventory import CATALOG_TAG_FILTER_EXPR, inventory_pbf
from pound.catalog.manifest import (
    CATALOG_KINDS,
    CATALOG_METADATA_KEYS,
    MAX_CATALOG_KINDS,
    MAX_CATALOG_RADIUS_M,
)


def test_inventory_reports_user_facing_kinds_and_exclusions():
    report = inventory_pbf(Path("packages/pound-core/tests/fixtures/tiny_bulk.osm"))

    assert report.counts_by_kind == {
        "cafe": 1,
        "fuel": 1,
        "marina": 1,
        "museum": 1,
        "pub": 1,
        "supermarket": 1,
        "water_point": 1,
    }
    assert report.excluded_counts["transport"] == 2
    assert report.excluded_counts["pedestrian_access"] == 3
    assert report.excluded_counts["inactive"] == 1
    assert report.candidate_objects == 7
    assert "bakery" not in report.counts_by_kind
    assert "restaurant" not in report.counts_by_kind
    assert report.tag_coverage_by_kind["pub"] == {
        "amenity": 1,
        "name": 1,
        "opening_hours": 1,
    }
    assert report.tag_coverage_by_kind["supermarket"] == {
        "name": 1,
        "shop": 1,
    }
    assert report.tag_coverage_by_kind["museum"] == {
        "name": 1,
        "tourism": 1,
    }
    assert report.tag_coverage_by_kind["water_point"] == {
        "drinking_water": 1,
        "name": 1,
        "toilets": 1,
        "waterway": 1,
    }


def test_inventory_excludes_artwork_candidates(tmp_path):
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

    report = inventory_pbf(source)

    assert report.candidate_objects == 0
    assert report.excluded_counts["artwork"] == 3
    assert "artwork" not in CATALOG_TAG_FILTER_EXPR


def test_manifest_covers_the_approved_catalog_scope_and_budgets():
    assert CATALOG_KINDS == frozenset(
        {
            "pub",
            "cafe",
            "restaurant",
            "supermarket",
            "convenience",
            "bakery",
            "greengrocer",
            "butcher",
            "deli",
            "general",
            "marina",
            "mooring",
            "fuel",
            "water_point",
            "sanitary_disposal",
            "museum",
            "gallery",
            "historic_site",
            "garden",
            "wildlife_attraction",
            "landmark",
        }
    )
    assert {
        "name",
        "addr:housenumber",
        "addr:street",
        "addr:city",
        "addr:postcode",
        "opening_hours",
        "access",
        "fee",
        "wheelchair",
        "phone",
        "contact:phone",
        "email",
        "contact:email",
        "description",
        "website",
        "contact:website",
        "wikidata",
        "wikipedia",
        "osm_url",
    } <= CATALOG_METADATA_KEYS
    assert MAX_CATALOG_KINDS == 16
    assert MAX_CATALOG_RADIUS_M == 2_000.0


def test_inventory_classifies_every_approved_kind(tmp_path):
    tag_by_kind = {
        "pub": ("amenity", "pub"),
        "cafe": ("amenity", "cafe"),
        "restaurant": ("amenity", "restaurant"),
        "supermarket": ("shop", "supermarket"),
        "convenience": ("shop", "convenience"),
        "bakery": ("shop", "bakery"),
        "greengrocer": ("shop", "greengrocer"),
        "butcher": ("shop", "butcher"),
        "deli": ("shop", "deli"),
        "general": ("shop", "general"),
        "marina": ("leisure", "marina"),
        "mooring": ("mooring", "yes"),
        "fuel": ("amenity", "fuel"),
        "water_point": ("waterway", "water_point"),
        "sanitary_disposal": ("amenity", "sanitary_dump_station"),
        "museum": ("tourism", "museum"),
        "gallery": ("tourism", "gallery"),
        "historic_site": ("historic", "castle"),
        "garden": ("leisure", "garden"),
        "wildlife_attraction": ("tourism", "zoo"),
        "landmark": ("tourism", "attraction"),
    }
    nodes = []
    for index, (kind, (key, value)) in enumerate(sorted(tag_by_kind.items()), start=1):
        nodes.append(
            f'<node id="{index}" lat="51.75" lon="-1.26">'
            f'<tag k="{key}" v="{value}"/><tag k="name" v="{kind}"/></node>'
        )
    source = tmp_path / "approved-kinds.osm"
    source.write_text('<?xml version="1.0"?><osm version="0.6">' + "".join(nodes) + "</osm>")

    report = inventory_pbf(source)

    assert set(report.counts_by_kind) == CATALOG_KINDS
    assert report.counts_by_kind == dict.fromkeys(sorted(CATALOG_KINDS), 1)
    assert report.candidate_objects == len(CATALOG_KINDS)


def test_inventory_deduplicates_duplicate_source_object(tmp_path):
    source = tmp_path / "duplicate.osm"
    source.write_text(
        Path("packages/pound-core/tests/fixtures/tiny_bulk.osm")
        .read_text()
        .replace(
            "</osm>",
            '<node id="2002" lat="51.7501000" lon="-1.2601000">'
            '<tag k="amenity" v="pub"/><tag k="name" v="Towpath Arms"/>'
            "</node></osm>",
        )
    )

    report = inventory_pbf(source)

    assert report.counts_by_kind["pub"] == 1
    assert report.excluded_counts["duplicate"] == 1


def test_inventory_rejects_missing_source():
    import pytest

    with pytest.raises(FileNotFoundError):
        inventory_pbf(Path("packages/pound-core/tests/fixtures/missing.osm.pbf"))


def test_inventory_cli_writes_sorted_json_and_rejects_repo_data_output(tmp_path):
    import json

    import pytest

    from scripts.catalog_inventory import main

    output = tmp_path / "inventory.json"
    assert (
        main(["--pbf", "packages/pound-core/tests/fixtures/tiny_bulk.osm", "--out", str(output)])
        == 0
    )
    payload = json.loads(output.read_text())
    assert list(payload["counts_by_kind"]) == [
        "cafe",
        "fuel",
        "marina",
        "museum",
        "pub",
        "supermarket",
        "water_point",
    ]
    assert payload["candidate_objects"] == 7

    with pytest.raises(ValueError, match="repository data or artifact directory"):
        main(
            [
                "--pbf",
                "packages/pound-core/tests/fixtures/tiny_bulk.osm",
                "--out",
                "packages/pound-core/src/pound/data/inventory.json",
            ]
        )

    missing_output = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError):
        main(
            [
                "--pbf",
                "packages/pound-core/tests/fixtures/missing.osm.pbf",
                "--out",
                str(missing_output),
            ]
        )
    assert not missing_output.exists()
