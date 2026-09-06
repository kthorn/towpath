from __future__ import annotations

import json
from pathlib import Path

import pytest
from pound.climate.artifact import load_climate
from pound_build.ingest.climate import ClimateImporter, build_climate, normalize_history_payload

from scripts.build_climate import main


def _payload(year: int = 2025) -> dict:
    return {
        "latitude": 51.75,
        "longitude": -1.25,
        "elevation": 70.0,
        "timezone": "Europe/London",
        "daily_units": {
            "temperature_2m_max": "°C",
            "temperature_2m_min": "°C",
        },
        "daily": {
            "time": [f"{year}-05-{day:02d}" for day in range(1, 8)],
            "temperature_2m_max": [20.0] * 7,
            "temperature_2m_min": [10.0] * 7,
        },
    }


def test_normalize_history_payload_rejects_duplicate_dates_and_bad_temperature_pair():
    duplicate = _payload()
    duplicate["daily"]["time"][1] = duplicate["daily"]["time"][0]
    with pytest.raises(ValueError, match="duplicate"):
        normalize_history_payload(duplicate, expected_year=2025)

    inverted = _payload()
    inverted["daily"]["temperature_2m_min"][0] = 21.0
    with pytest.raises(ValueError, match="minimum"):
        normalize_history_payload(inverted, expected_year=2025)

    wrong_timezone = _payload()
    wrong_timezone["timezone"] = "UTC"
    with pytest.raises(ValueError, match="timezone"):
        normalize_history_payload(wrong_timezone, expected_year=2025)

    wrong_units = _payload()
    wrong_units["daily_units"]["temperature_2m_max"] = "°F"
    with pytest.raises(ValueError, match="Celsius"):
        normalize_history_payload(wrong_units, expected_year=2025)

    missing_units = _payload()
    missing_units.pop("daily_units")
    with pytest.raises(ValueError, match="daily_units"):
        normalize_history_payload(missing_units, expected_year=2025)


def test_importer_uses_cached_year_before_fetching(tmp_path: Path):
    cache = tmp_path / "cache"
    cache_path = cache / "oxford" / "2025.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(
        json.dumps(
            {
                "request": {
                    "endpoint": "https://archive-api.open-meteo.com/v1/archive",
                    "location_id": "oxford",
                    "latitude": 51.75,
                    "longitude": -1.25,
                    "start_date": "2025-05-01",
                    "end_date": "2025-09-03",
                    "daily": "temperature_2m_max,temperature_2m_min",
                    "temperature_unit": "celsius",
                    "timezone": "Europe/London",
                    "models": "era5_land",
                },
                "response": _payload(),
            }
        )
    )

    def fail_fetch(*args, **kwargs):
        raise AssertionError("cached payload should avoid network")

    importer = ClimateImporter(cache_dir=cache, fetcher=fail_fetch)

    result = importer.fetch_year("oxford", {"lat": 51.75, "lon": -1.25}, 2025)

    assert result["daily"]["time"][0] == "2025-05-01"


def test_importer_refetches_cache_when_requested_coordinate_changes(tmp_path: Path):
    cache = tmp_path / "cache"
    calls: list[int] = []

    def fetcher(location_id, coordinate, year):
        calls.append(year)
        return _payload(year)

    importer = ClimateImporter(cache_dir=cache, fetcher=fetcher, request_interval_seconds=0)
    importer.fetch_year("oxford", {"lat": 51.75, "lon": -1.25}, 2025)
    importer.fetch_year("oxford", {"lat": 51.76, "lon": -1.25}, 2025)

    assert calls == [2025, 2025]


def test_importer_writes_successful_year_atomically_and_resumes(tmp_path: Path):
    calls: list[int] = []

    def fetcher(location_id, coordinate, year):
        calls.append(year)
        return _payload(year)

    importer = ClimateImporter(cache_dir=tmp_path / "cache", fetcher=fetcher)

    first = importer.fetch_year("oxford", {"lat": 51.75, "lon": -1.25}, 2024)
    second = importer.fetch_year("oxford", {"lat": 51.75, "lon": -1.25}, 2024)

    assert first == second
    assert calls == [2024]
    assert (tmp_path / "cache" / "oxford" / "2024.json").is_file()
    envelope = json.loads((tmp_path / "cache" / "oxford" / "2024.json").read_text())
    assert envelope["fetched_at"].endswith("+00:00")


def test_importer_can_read_a_complete_cached_history_without_network(tmp_path: Path):
    cache = tmp_path / "cache"
    for year in range(2001, 2026):
        path = cache / "oxford" / f"{year}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "request": {
                        "endpoint": "https://archive-api.open-meteo.com/v1/archive",
                        "location_id": "oxford",
                        "latitude": 51.75,
                        "longitude": -1.25,
                        "start_date": f"{year}-05-01",
                        "end_date": f"{year}-09-03",
                        "daily": "temperature_2m_max,temperature_2m_min",
                        "temperature_unit": "celsius",
                        "timezone": "Europe/London",
                        "models": "era5_land",
                    },
                    "response": _payload(year),
                }
            )
        )

    importer = ClimateImporter(cache_dir=cache, fetcher=lambda *_: pytest.fail("network"))
    histories = importer.load_cached_histories(
        [{"id": "oxford", "name": "Oxford", "coordinate": {"lat": 51.75, "lon": -1.25}}],
        end_year=2025,
    )

    assert sorted(histories["oxford"]) == list(range(2001, 2026))


def test_build_climate_cli_reads_cache_without_fetching(tmp_path: Path):
    cache = tmp_path / "cache"
    manifest = tmp_path / "locations.json"
    manifest.write_text(
        json.dumps(
            [{"id": "oxford", "name": "Oxford", "coordinate": {"lat": 51.75, "lon": -1.25}}]
        )
    )
    for year in range(2001, 2026):
        path = cache / "oxford" / f"{year}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "request": {
                        "endpoint": "https://archive-api.open-meteo.com/v1/archive",
                        "location_id": "oxford",
                        "latitude": 51.75,
                        "longitude": -1.25,
                        "start_date": f"{year}-05-01",
                        "end_date": f"{year}-09-03",
                        "daily": "temperature_2m_max,temperature_2m_min",
                        "temperature_unit": "celsius",
                        "timezone": "Europe/London",
                        "models": "era5_land",
                    },
                    "response": _payload(year),
                }
            )
        )

    out = tmp_path / "climate.json"
    assert main(
        [
            "--locations",
            str(manifest),
            "--cache-dir",
            str(cache),
            "--end-year",
            "2025",
            "--out",
            str(out),
        ]
    ) == 0
    assert load_climate(out).end_year == 2025


def test_build_climate_rejects_source_grid_changes_between_years():
    first = _payload(2024)
    second = _payload(2025)
    second["latitude"] = 51.8
    locations = [{"id": "oxford", "name": "Oxford", "coordinate": {"lat": 51.75, "lon": -1.25}}]

    with pytest.raises(ValueError, match="source coordinates"):
        build_climate(locations, 2025, {"oxford": {2024: first, 2025: second}})


@pytest.mark.parametrize("field", ["latitude", "longitude"])
def test_build_climate_rejects_missing_provider_source_coordinates(field: str):
    payload = _payload(2025)
    payload.pop(field)
    locations = [{"id": "oxford", "name": "Oxford", "coordinate": {"lat": 51.75, "lon": -1.25}}]

    with pytest.raises(ValueError, match="source coordinates"):
        build_climate(locations, 2025, {"oxford": {2025: payload}})


def test_build_climate_rejects_location_without_provider_history():
    locations = [{"id": "oxford", "name": "Oxford", "coordinate": {"lat": 51.75, "lon": -1.25}}]

    with pytest.raises(ValueError, match="source coordinates"):
        build_climate(locations, 2025, {"oxford": {}})
