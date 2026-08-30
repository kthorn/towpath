"""Restricted runtime loader for the independent OSM place catalog."""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pound.catalog.models import CatalogPlace

CATALOG_SCHEMA_VERSION = 3
OSM_ATTRIBUTION = "© OpenStreetMap contributors"

_PAYLOAD_FIELDS = {"places", "metadata"}
_ALLOWED_GLOBALS = {
    ("pound.catalog.models", "CatalogPlace"),
    ("pound.catalog.metadata", "CatalogAddress"),
    ("pound.catalog.metadata", "CatalogMetadata"),
    ("pound.catalog.metadata", "NormalizedLink"),
    ("pound.models", "OsmElementType"),
}


class _CatalogUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str) -> Any:
        if (module, name) not in _ALLOWED_GLOBALS:
            raise pickle.UnpicklingError(f"catalog pickle global is not allowed: {module}.{name}")
        return super().find_class(module, name)


class InvalidCatalogError(ValueError):
    """A catalog pickle does not satisfy the runtime compatibility contract."""


@dataclass(frozen=True, slots=True)
class CatalogArtifact:
    places: tuple[CatalogPlace, ...]
    metadata: dict[str, Any]


def _invalid(problem: str) -> InvalidCatalogError:
    return InvalidCatalogError(f"Invalid catalog: {problem}")


def load_catalog(path: Path) -> CatalogArtifact:
    """Load a trusted catalog with restricted globals and compatibility checks only."""
    try:
        with Path(path).open("rb") as stream:
            payload = _CatalogUnpickler(stream).load()  # pi-lens-ignore: python-pickle
    except Exception as exc:
        raise _invalid(f"could not load catalog: {exc}") from exc
    if type(payload) is not dict or set(payload) != _PAYLOAD_FIELDS:
        raise _invalid("invalid top-level catalog shape")
    metadata = payload["metadata"]
    if type(metadata) is not dict:
        raise _invalid("invalid metadata section type")
    if metadata.get("catalog_schema_version") != CATALOG_SCHEMA_VERSION:
        raise _invalid("unsupported catalog_schema_version")
    if not isinstance(metadata.get("catalog_revision"), str) or not metadata["catalog_revision"]:
        raise _invalid("catalog revision is required")
    if not isinstance(payload["places"], (list, tuple)):
        raise _invalid("invalid places section type")
    return CatalogArtifact(tuple(payload["places"]), metadata)
