"""Grid queries preserve daily sample semantics and isolate malformed artifacts."""

import json
import sqlite3

import pytest
from pound.climate.grid import ClimateGrid, InvalidClimateGridError
from pound.climate.statistics import summarize_distribution


@pytest.fixture
def grid_path(tmp_path):
    path = tmp_path / "grid.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE cells(id TEXT PRIMARY KEY,name TEXT,lat REAL,lon REAL,
          source_lat REAL,source_lon REAL,elevation REAL);
        CREATE TABLE distributions(cell_id TEXT,week_id INTEGER,metric TEXT,
          period_years INTEGER,payload TEXT,
          PRIMARY KEY(cell_id,week_id,metric,period_years));
        """)
        meta = dict(
            schema_version=1,
            revision="test-grid",
            end_year=2025,
            spacing_km=10,
            built_at="2026-09-06T00:00:00Z",
            source=dict(
                name="Synthetic",
                url="https://example.org",
                attribution="Test",
                timezone="Europe/London",
                model="era5_land",
            ),
            mask_source=dict(name="Synthetic", url="https://example.org", attribution="Test"),
            mask=dict(
                type="Polygon", coordinates=[[[-2, 51], [0, 51], [0, 53], [-2, 53], [-2, 51]]]
            ),
        )
        db.executemany(
            "INSERT INTO metadata VALUES (?,?)", [(k, json.dumps(v)) for k, v in meta.items()]
        )
        db.execute("INSERT INTO cells VALUES ('cell','Grid cell',52,-1,52,-1,10)")
        for week in range(18):
            for metric in ("high", "low"):
                for period in (5, 25):
                    values = {y: [29, 30, 30, 31, 32, 33, 34] for y in range(2026 - period, 2026)}
                    distribution = summarize_distribution(
                        values, start_year=2026 - period, end_year=2025
                    )
                    db.execute(
                        "INSERT INTO distributions VALUES (?,?,?,?,?)",
                        ("cell", week, metric, period, distribution.model_dump_json()),
                    )
    return path


def test_exceedance_is_strict_and_surface_has_no_samples(grid_path):
    grid = ClimateGrid(grid_path)
    surface = grid.surface(8, 5, "high_exceedance", 30)
    assert surface["cells"][0]["value"] == pytest.approx(4 / 7)
    assert surface["cells"][0]["n_days"] == 35
    assert surface["unit"] == "probability"
    assert "samples" not in json.dumps(surface)
    assert grid.surface(8, 25, "high_p90")["cells"][0]["value"] == 34
    detail = grid.detail("cell", 8)
    assert len(detail["high"]["25"]["samples"]) == 175
    assert len(detail["low"]["5"]["samples"]) == 35
    assert grid.detail("absent", 8) is None


def test_invalid_or_incomplete_grid_rejected(grid_path):
    with sqlite3.connect(grid_path) as db:
        db.execute("DELETE FROM distributions WHERE week_id=0")
    with pytest.raises(InvalidClimateGridError):
        ClimateGrid(grid_path)


@pytest.mark.parametrize(
    "args",
    [
        (18, 5, "high_p90"),
        (8, 10, "high_p90"),
        (8, 5, "nope"),
        (8, 5, "high_exceedance", float("nan")),
    ],
)
def test_grid_query_validation(grid_path, args):
    with pytest.raises(ValueError):
        ClimateGrid(grid_path).surface(*args)


def test_unavailable_cell_stays_a_hole(grid_path):
    with sqlite3.connect(grid_path) as db:
        distribution = summarize_distribution({}, start_year=2021, end_year=2025)
        db.execute(
            "UPDATE distributions SET payload=? WHERE week_id=8 AND period_years=5",
            (distribution.model_dump_json(),),
        )
    surface = ClimateGrid(grid_path).surface(8, 5, "high_exceedance", 30)
    assert surface["cells"][0]["value"] is None


def test_reader_does_not_create_missing_file(tmp_path):
    path = tmp_path / "absent.sqlite"
    with pytest.raises(InvalidClimateGridError):
        ClimateGrid(path)
    assert not path.exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE metadata SET value='123' WHERE key='built_at'",
        "UPDATE distributions SET week_id=1.5 WHERE week_id=0 AND metric='high' AND period_years=5",
        "UPDATE distributions SET week_id=NULL "
        "WHERE week_id=0 AND metric='high' AND period_years=5",
    ],
)
def test_malformed_metadata_and_null_keys_rejected(grid_path, mutation):
    with sqlite3.connect(grid_path) as db:
        db.execute(mutation)
    with pytest.raises(InvalidClimateGridError):
        ClimateGrid(grid_path)


def test_atomic_replacement_during_connection_is_rejected(grid_path, monkeypatch):
    import shutil

    grid = ClimateGrid(grid_path)
    real_connect = sqlite3.connect
    replacement = grid_path.with_suffix(".new")
    shutil.copyfile(grid_path, replacement)

    def replacing_connect(*args, **kwargs):
        replacement.replace(grid_path)
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", replacing_connect)
    with pytest.raises(InvalidClimateGridError):
        grid.surface(8, 5, "high_p90")


def test_grid_rejects_wrong_daily_timezone(grid_path):
    with sqlite3.connect(grid_path) as db:
        source = json.loads(
            db.execute("SELECT value FROM metadata WHERE key='source'").fetchone()[0]
        )
        source["timezone"] = "UTC"
        db.execute("UPDATE metadata SET value=? WHERE key='source'", (json.dumps(source),))
    with pytest.raises(InvalidClimateGridError):
        ClimateGrid(grid_path)
