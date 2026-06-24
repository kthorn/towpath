"""Shared test fixture paths."""

from pathlib import Path


def oxford_fixture_path() -> Path:
    return Path(__file__).parent / "oxford_overpass_sample.json"
