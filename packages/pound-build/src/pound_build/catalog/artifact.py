"""Validate and atomically publish independent OSM place catalogs."""

from __future__ import annotations

import math
import os
import pickle
from collections.abc import Iterable
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4

from pound.catalog.artifact import (
    CATALOG_SCHEMA_VERSION,
    OSM_ATTRIBUTION,
    CatalogArtifact,
    InvalidCatalogError,
)
from pound.catalog.metadata import CatalogAddress, CatalogMetadata, NormalizedLink
from pound.catalog.models import CatalogPlace
from pydantic import ValidationError
from shapely import get_coordinates, wkb

_METADATA_FIELDS = {
    "attribution",
    "build_summary",
    "built_at",
    "catalog_revision",
    "catalog_schema_version",
    "fetched_at",
    "inventory_summary",
    "source",
}
_GEOMETRY_TYPES = {
    "point": {"Point"},
    "line": {"LineString", "MultiLineString"},
    "area": {"Polygon", "MultiPolygon"},
}


def _invalid(field: str, value: Any, problem: str) -> InvalidCatalogError:
    return InvalidCatalogError(f"Invalid catalog {field}={value!r}: {problem}")


def _supported_metadata(value: Any, *, field: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _invalid(field, value, "expected finite numeric values")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _supported_metadata(item, field=f"{field}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise _invalid(field, key, "mapping keys must be non-empty strings")
            _supported_metadata(item, field=f"{field}.{key}")
        return
    raise _invalid(field, value, "expected JSON-compatible metadata types")


def _validate_metadata(metadata: Any) -> dict[str, Any]:
    if type(metadata) is not dict:
        raise _invalid("metadata", metadata, "expected a mapping")
    fields = set(metadata)
    if fields != _METADATA_FIELDS:
        missing = sorted(_METADATA_FIELDS - fields)
        unexpected = sorted(fields - _METADATA_FIELDS)
        raise _invalid(
            "metadata keys",
            sorted(fields),
            f"expected exactly {sorted(_METADATA_FIELDS)}; "
            f"missing={missing}, unexpected={unexpected}",
        )
    version = metadata["catalog_schema_version"]
    if type(version) is not int or version != CATALOG_SCHEMA_VERSION:
        raise _invalid(
            "metadata.catalog_schema_version",
            version,
            f"expected supported version {CATALOG_SCHEMA_VERSION}",
        )
    if metadata["attribution"] != OSM_ATTRIBUTION:
        raise _invalid(
            "metadata.attribution",
            metadata["attribution"],
            f"expected exactly {OSM_ATTRIBUTION!r}",
        )
    for field in ("catalog_revision", "source", "fetched_at", "built_at"):
        value = metadata[field]
        if type(value) is not str or not value.strip():
            raise _invalid(f"metadata.{field}", value, "expected a non-empty string")
    for field in ("inventory_summary", "build_summary"):
        if type(metadata[field]) is not dict:
            raise _invalid(f"metadata.{field}", metadata[field], "expected a mapping")
        _supported_metadata(metadata[field], field=f"metadata.{field}")
    return dict(metadata)


def _metadata_values(raw: Any, *, field: str) -> CatalogMetadata:
    if isinstance(raw, CatalogMetadata):
        values = raw.model_dump()
    elif isinstance(raw, dict):
        values = dict(raw)
    else:
        raise _invalid(field, raw, "expected CatalogMetadata")

    expected = set(CatalogMetadata.model_fields)
    if set(values) != expected:
        raise _invalid(
            f"{field} keys",
            sorted(values),
            f"expected exactly {sorted(expected)}",
        )
    links = values["links"]
    if not isinstance(links, list):
        raise _invalid(f"{field}.links", links, "expected a list")
    try:
        values["links"] = [
            link if isinstance(link, NormalizedLink) else NormalizedLink(**link) for link in links
        ]
        address = values["address"]
        if isinstance(address, dict):
            values["address"] = CatalogAddress(**address)
        return CatalogMetadata(**values)
    except (TypeError, ValueError, ValidationError) as exc:
        raise _invalid(field, raw, "invalid normalized metadata") from exc


def _parse_place(raw: Any, *, index: int) -> CatalogPlace:
    if isinstance(raw, CatalogPlace):
        values = raw.model_dump()
    elif isinstance(raw, dict):
        values = dict(raw)
    else:
        raise _invalid(f"places[{index}]", raw, "expected a CatalogPlace mapping")

    expected = set(CatalogPlace.model_fields)
    if set(values) != expected:
        raise _invalid(
            f"places[{index}] keys",
            sorted(values),
            f"expected exactly {sorted(expected)}",
        )
    values["metadata"] = _metadata_values(values["metadata"], field=f"places[{index}].metadata")
    try:
        place = CatalogPlace(**values)
    except (TypeError, ValueError, ValidationError) as exc:
        raise _invalid(f"places[{index}]", values, "invalid normalized place") from exc

    if not place.identity[0] or not place.identity[2].strip():
        raise _invalid(f"places[{index}].identity", place.identity, "identity is not empty")
    if not all(math.isfinite(value) for value in (place.lat, place.lon)):
        raise _invalid(f"places[{index}] coordinates", (place.lat, place.lon), "must be finite")
    try:
        geometry = wkb.loads(place.geometry_wkb)
    except Exception as exc:
        raise _invalid(f"places[{index}].geometry_wkb", place.geometry_wkb, "invalid WKB") from exc
    if geometry.is_empty or geometry.geom_type not in _GEOMETRY_TYPES[place.geometry_source]:
        raise _invalid(
            f"places[{index}].geometry_wkb",
            geometry.geom_type,
            f"invalid geometry for source {place.geometry_source!r}",
        )
    coordinates = get_coordinates(geometry)
    if not coordinates.size or not all(math.isfinite(value) for value in coordinates.flat):
        raise _invalid(f"places[{index}].geometry_wkb", "non-finite coordinates", "invalid WKB")
    return place


def _parse_places(raw_places: Any) -> tuple[CatalogPlace, ...]:
    if not isinstance(raw_places, (list, tuple)):
        raise _invalid("places", raw_places, "expected a list or tuple")
    places = tuple(_parse_place(raw, index=index) for index, raw in enumerate(raw_places))
    identities = [place.identity for place in places]
    if len(set(identities)) != len(identities):
        raise _invalid("places.identity", identities, "identities must be unique")
    return places


def prepare_catalog(places: Iterable[CatalogPlace], metadata: dict[str, Any]) -> CatalogArtifact:
    """Validate catalog records and metadata before trusted local serialization."""
    complete_metadata = dict(metadata)
    complete_metadata.setdefault("catalog_revision", str(uuid4()))
    complete_metadata.setdefault("catalog_schema_version", CATALOG_SCHEMA_VERSION)
    complete_metadata.setdefault("attribution", OSM_ATTRIBUTION)
    return CatalogArtifact(
        places=_parse_places(tuple(places)),
        metadata=_validate_metadata(complete_metadata),
    )


def write_catalog(artifact: CatalogArtifact, path: Path) -> None:
    """Atomically publish one independently validated catalog payload."""
    if not isinstance(artifact, CatalogArtifact):
        raise _invalid("artifact", artifact, "expected CatalogArtifact")
    artifact = prepare_catalog(artifact.places, artifact.metadata)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("wb", dir=path.parent, delete=False) as stream:
        pickle.dump(  # pi-lens-ignore: python-pickle
            {"places": list(artifact.places), "metadata": artifact.metadata}, stream
        )
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(stream.name, path)
