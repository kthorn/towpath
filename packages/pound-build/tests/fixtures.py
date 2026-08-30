"""Shared fixture paths for build-package tests."""

from pathlib import Path

_FIXTURES = Path("packages/pound-core/tests/fixtures")


def oxford_fixture_path() -> Path:
    return _FIXTURES / "oxford_overpass_sample.json"


def staircase_fixture_path() -> Path:
    return _FIXTURES / "staircase_overpass_sample.json"


def poi_fixture_path() -> Path:
    return _FIXTURES / "poi_overpass_sample.json"
