"""Strict normalized catalog place records."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pound.catalog.manifest import CATALOG_KINDS
from pound.catalog.metadata import CatalogAddress, CatalogMetadata, NormalizedLink
from pound.models import OsmElementType

__all__ = ["CatalogAddress", "CatalogMetadata", "CatalogPlace", "NormalizedLink"]


class CatalogPlace(BaseModel):
    """An immutable-in-practice OSM catalog record suitable for serialization."""

    model_config = ConfigDict(extra="forbid", strict=True)

    osm_type: OsmElementType
    osm_id: int = Field(gt=0)
    kind: str
    name: str | None
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    metadata: CatalogMetadata
    geometry_wkb: bytes
    geometry_source: Literal["point", "line", "area"]

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, kind: str) -> str:
        if kind not in CATALOG_KINDS:
            raise ValueError(f"unknown catalog kind: {kind}")
        return kind

    @field_validator("lat", "lon")
    @classmethod
    def validate_coordinate(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("coordinates must be finite")
        return value

    @property
    def identity(self) -> tuple[OsmElementType, int, str]:
        return self.osm_type, self.osm_id, self.kind
