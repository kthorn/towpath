import json
from pathlib import Path

import pytest
from pound.catalog.metadata import CatalogAddress, CatalogMetadata
from pound.catalog.models import CatalogPlace
from pound.models import OsmElementType
from pound_build.catalog.artifact import prepare_catalog, write_catalog
from shapely import wkb
from shapely.geometry import Point

from scripts.place_resolution_inventory import inventory_catalog, main


def _place(
    osm_id: int,
    name: str | None,
    *,
    alt_name: str | None = None,
    locality: str | None = None,
) -> CatalogPlace:
    return CatalogPlace(
        osm_type=OsmElementType.NODE,
        osm_id=osm_id,
        kind="museum" if name and "Bletchley" in name else "pub",
        name=name,
        lat=51.99 + osm_id / 100_000,
        lon=-0.73,
        metadata=CatalogMetadata(
            name=name,
            alt_name=alt_name,
            address=CatalogAddress(city=locality) if locality else None,
        ),
        geometry_wkb=wkb.dumps(Point(-0.73, 51.99 + osm_id / 100_000), output_dimension=2),
        geometry_source="point",
    )


def _catalog(path: Path) -> Path:
    artifact = prepare_catalog(
        [
            _place(1, "Bletchley Park", alt_name="The Mansion", locality="Milton Keynes"),
            _place(2, "Bletchley Park Visitor Centre", locality="Bletchley"),
            _place(3, None),
        ],
        {
            "source": "great-britain.osm.pbf",
            "fetched_at": "2026-09-01T00:00:00Z",
            "built_at": "2026-09-02T00:00:00Z",
            "inventory_summary": {"place_count": 3},
            "build_summary": {"emitted": 3},
        },
    )
    write_catalog(artifact, path)
    return path


def test_inventory_reports_coverage_and_bounded_national_search(tmp_path: Path):
    report = inventory_catalog(_catalog(tmp_path / "catalog.pkl"), warmups=0, iterations=2)

    assert report["record_count"] == 3
    assert report["extent"] == pytest.approx(
        {
        "lat_max": 51.99003,
        "lat_min": 51.99001,
        "lon_max": -0.73,
        "lon_min": -0.73,
        }
    )
    assert report["name_completeness"] == {"named": 2, "unnamed": 1, "fraction": 2 / 3}
    assert report["alias_completeness"] == {"records_with_alias": 1, "alias_values": 1}
    assert report["locality_completeness"] == {
        "records_with_locality": 2,
        "fraction": 2 / 3,
        "place": 0,
        "city": 2,
    }
    assert report["bletchley_matches"]["exact"]["match_count"] == 1
    assert report["bletchley_matches"]["partial"]["match_count"] == 2
    assert report["bletchley_matches"]["miss"]["match_count"] == 0
    for case in report["national_lookup_baseline"].values():
        assert case["examined_records"] == 3
        assert case["iterations"] == 2
        assert case["p50_ms"] >= 0
        assert case["p95_ms"] >= case["p50_ms"]


def test_cli_accepts_catalog_and_emits_json(tmp_path: Path, capsys):
    assert (
        main(
            [
                "--catalog",
                str(_catalog(tmp_path / "catalog.pkl")),
                "--warmups",
                "0",
                "--iterations",
                "2",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["catalog"]["path"].endswith("catalog.pkl")
    assert payload["national_lookup_baseline"]["miss"]["query"]
