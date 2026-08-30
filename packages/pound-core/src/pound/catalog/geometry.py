"""Normalize catalog WKT into safe display coordinates and metric-query WKB."""

from __future__ import annotations

import math
from typing import Literal

from shapely import get_coordinates, wkb, wkt
from shapely.geometry.base import BaseGeometry
from shapely.validation import make_valid

from pound.schemas import Coordinate

GeometrySource = Literal["point", "line", "area"]
# WGS84 degrees: approximately one metre at England's latitude.  Retain the
# full normalized shape for distance queries while removing source noise.
SIMPLIFICATION_TOLERANCE_DEGREES = 1e-5

_EXPECTED_TYPES: dict[GeometrySource, frozenset[str]] = {
    "point": frozenset({"Point"}),
    "line": frozenset({"LineString", "MultiLineString"}),
    "area": frozenset({"Polygon", "MultiPolygon"}),
}


def _load_wkt(geometry_wkt: str) -> BaseGeometry:
    try:
        return wkt.loads(geometry_wkt)
    except Exception as exc:
        raise ValueError("invalid WKT geometry") from exc


def _has_only_finite_coordinates(geometry: BaseGeometry) -> bool:
    coordinates = get_coordinates(geometry)
    return bool(coordinates.size) and bool(all(math.isfinite(value) for value in coordinates.flat))


def normalize_catalog_geometry(
    geometry_wkt: str,
    *,
    source: GeometrySource,
) -> tuple[bytes, Coordinate]:
    """Return simplified normalized WKB and a representative WGS84 coordinate."""
    if source not in _EXPECTED_TYPES:
        raise ValueError(f"unknown geometry source: {source!r}")

    geometry = _load_wkt(geometry_wkt)
    supported_types = frozenset().union(*_EXPECTED_TYPES.values())
    if geometry.geom_type not in supported_types:
        raise ValueError(f"unsupported geometry type: {geometry.geom_type}")
    if geometry.geom_type not in _EXPECTED_TYPES[source]:
        raise ValueError(f"geometry type does not match source {source!r}")
    if geometry.is_empty or not _has_only_finite_coordinates(geometry):
        raise ValueError("geometry must be non-empty and finite")

    if source == "area" and not geometry.is_valid:
        geometry = make_valid(geometry)
        if geometry.geom_type not in _EXPECTED_TYPES[source]:
            raise ValueError("invalid area geometry cannot be repaired")

    normalized = geometry.simplify(
        SIMPLIFICATION_TOLERANCE_DEGREES,
        preserve_topology=source == "area",
    )
    if (
        normalized.is_empty
        or normalized.geom_type not in _EXPECTED_TYPES[source]
        or not _has_only_finite_coordinates(normalized)
    ):
        raise ValueError("geometry simplification produced unusable geometry")
    if source == "line" and normalized.length == 0:
        raise ValueError("line geometry must have nonzero length")
    if source == "area" and normalized.area == 0:
        raise ValueError("area geometry must have nonzero area")
    if source == "area" and not normalized.is_valid:
        raise ValueError("normalized area geometry is invalid")

    marker = normalized.representative_point()
    if marker.is_empty or not _has_only_finite_coordinates(marker):
        raise ValueError("geometry has no finite representative point")

    return wkb.dumps(normalized, output_dimension=2), Coordinate(lat=marker.y, lon=marker.x)
