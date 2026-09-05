from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pound.climate.artifact import (
    ClimateArtifact,
    ClimateSource,
    InvalidClimateArtifactError,
    load_climate,
    write_climate,
)
from pound_build.ingest.climate import build_climate


def _history(years: range) -> dict[int, dict]:
    return {
        year: {
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
                "temperature_2m_max": [20 + day for day in range(1, 8)],
                "temperature_2m_min": [8 + day for day in range(1, 8)],
            },
        }
        for year in years
    }


def _locations() -> list[dict]:
    return [{"id": "oxford", "name": "Oxford", "coordinate": {"lat": 51.75, "lon": -1.25}}]


def test_build_artifact_contains_both_periods_and_all_fixed_windows():
    artifact = build_climate(_locations(), 2025, {"oxford": _history(range(2001, 2026))})

    assert artifact.schema_version == 1
    assert artifact.end_year == 2025
    assert len(artifact.locations) == 1
    assert len(artifact.locations[0].weeks) == 18
    assert set(artifact.locations[0].weeks[0].high) == {"25", "5"}
    assert artifact.locations[0].weeks[0].high["25"].n_days == 175
    assert artifact.locations[0].weeks[0].high["5"].available is True
    assert artifact.locations[0].source_coordinate.lat == pytest.approx(51.75)


def test_write_and_load_climate_round_trip_is_strict_json(tmp_path: Path):
    artifact = build_climate(_locations(), 2025, {"oxford": _history(range(2001, 2026))})
    path = tmp_path / "climate.json"

    write_climate(artifact, path)
    loaded = load_climate(path)

    assert loaded == artifact
    assert json.loads(path.read_text())["schema_version"] == 1
    assert loaded.built_at.tzinfo is not None
    assert loaded.built_at.utcoffset() == UTC.utcoffset(loaded.built_at)


def test_revision_excludes_build_timestamp(tmp_path: Path):
    artifact = build_climate(_locations(), 2025, {"oxford": _history(range(2001, 2026))})
    moved_timestamp = artifact.model_copy(
        update={"built_at": datetime(2030, 1, 1, tzinfo=UTC)}
    )
    path = tmp_path / "timestamp.json"

    write_climate(moved_timestamp, path)

    loaded = load_climate(path)
    assert loaded.revision == artifact.revision
    assert loaded.built_at == datetime(2030, 1, 1, tzinfo=UTC)


def test_load_climate_rejects_corrupt_or_inconsistent_artifact(tmp_path: Path):
    path = tmp_path / "climate.json"
    artifact = build_climate(_locations(), 2025, {"oxford": _history(range(2001, 2026))})
    payload = artifact.model_dump(mode="json")
    payload["locations"][0]["weeks"].pop()
    path.write_text(json.dumps(payload))

    with pytest.raises(InvalidClimateArtifactError, match="weeks"):
        load_climate(path)


def test_load_climate_rejects_tampered_quantile_or_revision(tmp_path: Path):
    artifact = build_climate(_locations(), 2025, {"oxford": _history(range(2001, 2026))})
    payload = artifact.model_dump(mode="json")
    payload["locations"][0]["weeks"][0]["high"]["25"]["median"] += 1
    quantile_path = tmp_path / "quantile.json"
    quantile_path.write_text(json.dumps(payload))
    with pytest.raises(InvalidClimateArtifactError, match="quantile"):
        load_climate(quantile_path)

    payload = artifact.model_dump(mode="json")
    payload["revision"] = "tampered"
    revision_path = tmp_path / "revision.json"
    revision_path.write_text(json.dumps(payload))
    with pytest.raises(InvalidClimateArtifactError, match="revision"):
        load_climate(revision_path)


def test_climate_source_accepts_web_urls_and_rejects_other_schemes():
    artifact = build_climate(_locations(), 2025, {"oxford": _history(range(2001, 2026))})

    http_source = ClimateSource.model_validate(
        artifact.source.model_dump(mode="python") | {"url": "http://example.test/source"}
    )
    assert http_source.url.startswith("http://")

    with pytest.raises(ValueError, match=r"HTTP\(S\)"):
        ClimateSource.model_validate(
            artifact.source.model_dump(mode="python") | {"url": "javascript:alert(1)"}
        )


def test_load_climate_requires_explicit_schema_version(tmp_path: Path):
    artifact = build_climate(_locations(), 2025, {"oxford": _history(range(2001, 2026))})
    payload = artifact.model_dump(mode="json")
    payload.pop("schema_version")
    path = tmp_path / "missing-version.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(InvalidClimateArtifactError, match="schema_version"):
        load_climate(path)


def test_location_identity_fields_must_be_nonblank():
    with pytest.raises(ValueError, match="location id and name"):
        build_climate(
            [{"id": "", "name": "Oxford", "coordinate": {"lat": 51.75, "lon": -1.25}}],
            2025,
            {},
        )


def test_artifact_rejects_mismatched_period_end_year():
    artifact = build_climate(_locations(), 2025, {"oxford": _history(range(2001, 2026))})
    payload = artifact.model_dump(mode="json")
    payload["locations"][0]["weeks"][0]["high"]["25"]["end_year"] = 2024

    with pytest.raises(ValueError, match="n_years|end_year"):
        ClimateArtifact.model_validate(payload)


def test_unavailable_distribution_requires_missing_year_metadata():
    with pytest.raises(ValueError, match="missing_years"):
        from pound.climate.artifact import ClimateDistribution

        ClimateDistribution(
            available=False,
            missing_years=[],
            start_year=2021,
            end_year=2025,
            n_days=35,
            n_years=5,
            p10=None,
            median=None,
            p90=None,
            samples=[],
        )
