"""Shared fixture paths for build-package tests.

The tracked fixture data is shared with core tests and intentionally remains in
``packages/pound-core/tests/fixtures``; callers should use these helpers rather
than constructing package-relative paths.
"""

from pathlib import Path

_FIXTURES = Path("packages/pound-core/tests/fixtures")


def oxford_fixture_path() -> Path:
    return _FIXTURES / "oxford_overpass_sample.json"


def staircase_fixture_path() -> Path:
    return _FIXTURES / "staircase_overpass_sample.json"


def tiny_bulk_fixture_path() -> Path:
    return _FIXTURES / "tiny_bulk.osm"


def poi_fixture_path() -> Path:
    return _FIXTURES / "poi_overpass_sample.json"
