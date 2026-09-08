from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pound_build.ingest.climate_grid as climate_grid
import pytest
from pound.climate.artifact import ClimateSource
from pound.climate.grid import ClimateGrid
from pound_build.ingest.climate import _season_bounds
from pound_build.ingest.climate_grid import (
    DEFAULT_WEIGHTED_CALLS_PER_REQUEST,
    GRID_SPACING_METRES,
    ClimateGridBudgetExceeded,
    ClimateGridImporter,
    build_climate_grid,
    generate_grid_cells,
)
from pyproj import Transformer
from shapely.geometry import MultiPolygon, Point, box, mapping, shape
from shapely.ops import transform

from scripts.build_climate_grid import main


def _wgs84_box_for_one_projected_cell() -> dict:
    to_wgs84 = Transformer.from_crs(3035, 4326, always_xy=True).transform
    cell = box(4321000, 3210000, 4321000 + GRID_SPACING_METRES, 3210000 + GRID_SPACING_METRES)
    return mapping(transform(to_wgs84, cell))


def _payload(year: int) -> dict:
    return {
        "latitude": 52.0,
        "longitude": 10.0,
        "elevation": 100.0,
        "timezone": "Europe/London",
        "daily_units": {"temperature_2m_max": "°C", "temperature_2m_min": "°C"},
        "daily": {
            "time": [f"{year}-05-{day:02d}" for day in range(1, 8)],
            "temperature_2m_max": [20.0] * 7,
            "temperature_2m_min": [10.0] * 7,
        },
    }


def _cache_all(cache: Path, location_id: str, end_year: int = 2025) -> None:
    request_base = {
        "endpoint": "https://archive-api.open-meteo.com/v1/archive",
        "location_id": location_id,
        "latitude": 52.0,
        "longitude": 10.0,
        "daily": "temperature_2m_max,temperature_2m_min",
        "temperature_unit": "celsius",
        "timezone": "Europe/London",
        "models": "era5_land",
    }
    for year in range(end_year - 24, end_year + 1):
        request = request_base | {
            "start_date": _season_bounds(year)[0],
            "end_date": _season_bounds(year)[1],
        }
        target = cache / location_id / f"{year}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"request": request, "response": _payload(year)}))


def test_generate_grid_cells_keeps_partial_cells_and_points_on_land():
    mask = mapping(box(-0.2, 51.8, 0.2, 52.2))
    cells = generate_grid_cells(mask)

    assert cells
    assert all(cell["id"].startswith("uk10_e") for cell in cells)
    assert all(-90 <= cell["coordinate"]["lat"] <= 90 for cell in cells)
    assert all(-180 <= cell["coordinate"]["lon"] <= 180 for cell in cells)
    land = shape(mask)
    assert all(
        land.covers(Point(cell["coordinate"]["lon"], cell["coordinate"]["lat"])) for cell in cells
    )


def test_generate_grid_cells_rejects_non_contract_spacing():
    with pytest.raises(ValueError, match="10 km"):
        generate_grid_cells(mapping(box(-0.2, 51.8, 0.2, 52.2)), spacing_km=20)


def test_display_mask_repairs_invalid_topology_after_reprojection(monkeypatch):
    # Two valid projected components become coincident after this deliberately
    # folding transform, reproducing the topology failure seen with the ONS
    # boundary after EPSG:3035 -> WGS84 conversion.
    monkeypatch.setattr(climate_grid, "_TO_GRID", lambda x, y: (x, y))
    monkeypatch.setattr(climate_grid, "_TO_WGS84", lambda x, y: (abs(x), y))
    projected_mask = MultiPolygon([box(-2, 51, -1, 52), box(1, 51, 2, 52)])

    display = shape(climate_grid._display_mask(projected_mask, 0))

    assert display.is_valid


def test_grid_importer_stops_before_exceeding_weighted_budget(tmp_path: Path):
    calls: list[tuple[str, int]] = []

    def fetcher(location_id, coordinate, year):
        calls.append((location_id, year))
        return _payload(year)

    importer = ClimateGridImporter(
        cache_dir=tmp_path / "cache",
        fetcher=fetcher,
        request_interval_seconds=0,
        max_weighted_calls=9,
        weighted_calls_per_request=9,
    )
    locations = [
        {"id": "one", "name": "One", "coordinate": {"lat": 52.0, "lon": 10.0}},
        {"id": "two", "name": "Two", "coordinate": {"lat": 52.0, "lon": 10.0}},
    ]

    with pytest.raises(ClimateGridBudgetExceeded, match="weighted call budget"):
        importer.fetch_limited(locations, 2025)

    assert calls == [("one", 2025 - 24)]
    assert importer.weighted_calls == 9


def test_grid_importer_reserves_budget_for_retries(tmp_path: Path):
    calls: list[int] = []

    def fetcher(location_id, coordinate, year):
        calls.append(year)
        return _payload(year)

    importer = ClimateGridImporter(
        cache_dir=tmp_path / "cache",
        fetcher=fetcher,
        request_interval_seconds=0,
        max_weighted_calls=9,
        weighted_calls_per_request=9,
        retries=2,
    )
    with pytest.raises(ClimateGridBudgetExceeded, match="weighted call budget"):
        importer.fetch_limited(
            [{"id": "one", "name": "One", "coordinate": {"lat": 52.0, "lon": 10.0}}], 2025
        )
    assert calls == []
    assert importer.weighted_calls == 0


def test_build_grid_writes_mask_metadata_and_exact_72_rows(tmp_path: Path):
    manifest = [{"id": "cell", "name": "Grid cell", "coordinate": {"lat": 52.0, "lon": 10.0}}]
    mask = _wgs84_box_for_one_projected_cell()
    cache = tmp_path / "cache"
    _cache_all(cache, "cell")
    out = tmp_path / "grid.sqlite"
    source = ClimateSource(
        name="Test",
        url="https://example.test/climate",
        attribution="Test",
        timezone="Europe/London",
        model="era5_land",
    )

    build_climate_grid(
        manifest,
        mask,
        cache,
        2025,
        out,
        source=source,
        mask_source={"name": "ONS", "url": "https://example.test/mask", "attribution": "ONS"},
        built_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    with sqlite3.connect(out) as db:
        assert db.execute("select count(*) from cells").fetchone()[0] == 1
        assert db.execute("select count(*) from distributions").fetchone()[0] == 72
        metadata = dict(db.execute("select key,value from metadata"))
        assert json.loads(metadata["spacing_km"]) == 10
        assert json.loads(metadata["mask_source"])["name"] == "ONS"
        assert json.loads(metadata["built_at"]).endswith("+00:00")
        assert json.loads(metadata["revision"])
    loaded = ClimateGrid(out)
    assert len(loaded.surface(8, 25, "high_p90")["cells"]) == 1


def test_grid_revision_excludes_built_timestamp(tmp_path: Path):
    manifest = [{"id": "cell", "name": "Grid cell", "coordinate": {"lat": 52.0, "lon": 10.0}}]
    mask = _wgs84_box_for_one_projected_cell()
    cache = tmp_path / "cache"
    _cache_all(cache, "cell")
    first = tmp_path / "one.sqlite"
    second = tmp_path / "two.sqlite"
    kwargs = dict(
        source=ClimateSource(
            name="Test",
            url="https://example.test/climate",
            attribution="Test",
            timezone="Europe/London",
            model="era5_land",
        ),
        mask_source={"name": "ONS", "url": "https://example.test/mask", "attribution": "ONS"},
    )
    build_climate_grid(
        manifest, mask, cache, 2025, first, built_at=datetime(2026, 1, 1, tzinfo=UTC), **kwargs
    )
    build_climate_grid(
        manifest, mask, cache, 2025, second, built_at=datetime(2027, 1, 1, tzinfo=UTC), **kwargs
    )
    with sqlite3.connect(first) as db:
        revision_one = json.loads(
            db.execute("select value from metadata where key='revision'").fetchone()[0]
        )
    with sqlite3.connect(second) as db:
        revision_two = json.loads(
            db.execute("select value from metadata where key='revision'").fetchone()[0]
        )
    assert revision_one == revision_two


def test_grid_cli_prepare_and_estimate_are_bounded(tmp_path: Path, capsys):
    mask_path = tmp_path / "mask.json"
    mask_path.write_text(json.dumps(_wgs84_box_for_one_projected_cell()))
    manifest_path = tmp_path / "manifest.json"

    assert main(["prepare", "--mask", str(mask_path), "--manifest", str(manifest_path)]) == 0
    prepared = json.loads(manifest_path.read_text())
    assert len(prepared) >= 1
    capsys.readouterr()

    assert (
        main(
            [
                "estimate",
                "--manifest",
                str(manifest_path),
                "--end-year",
                "2025",
                "--cache-dir",
                str(tmp_path / "cache"),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["weighted_calls"] == (len(prepared) * 25 * DEFAULT_WEIGHTED_CALLS_PER_REQUEST)


def test_grid_cli_acquire_requires_explicit_budget(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps([{"id": "cell", "name": "Grid cell", "coordinate": {"lat": 52.0, "lon": 10.0}}])
    )
    with pytest.raises(SystemExit):
        main(["acquire-limited", "--manifest", str(manifest_path)])


def test_grid_cli_build_reads_only_annual_cache(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps([{"id": "cell", "name": "Grid cell", "coordinate": {"lat": 52.0, "lon": 10.0}}])
    )
    mask_path = tmp_path / "mask.json"
    mask_path.write_text(json.dumps(_wgs84_box_for_one_projected_cell()))
    cache = tmp_path / "cache"
    _cache_all(cache, "cell")
    out = tmp_path / "grid.sqlite"

    assert (
        main(
            [
                "build",
                "--manifest",
                str(manifest_path),
                "--mask",
                str(mask_path),
                "--cache-dir",
                str(cache),
                "--end-year",
                "2025",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    assert ClimateGrid(out).detail("cell", 0)["location"]["id"] == "cell"


def test_custom_endpoint_cache_is_reused_by_estimate_and_build(tmp_path: Path):
    manifest = [{"id": "cell", "name": "Grid cell", "coordinate": {"lat": 52.0, "lon": 10.0}}]
    mask = _wgs84_box_for_one_projected_cell()
    cache = tmp_path / "cache"
    _cache_all(cache, "cell")
    endpoint = "https://example.test/archive"
    for path in (cache / "cell").glob("*.json"):
        envelope = json.loads(path.read_text())
        envelope["request"]["endpoint"] = endpoint
        path.write_text(json.dumps(envelope))
    importer = ClimateGridImporter(
        cache_dir=cache, endpoint=endpoint, fetcher=lambda *_: pytest.fail("network")
    )
    assert importer.estimate_weighted_calls(manifest, 2025)["missing_requests"] == 0
    out = tmp_path / "grid.sqlite"
    build_climate_grid(manifest, mask, cache, 2025, out, endpoint=endpoint)
    assert ClimateGrid(out).detail("cell", 0) is not None
