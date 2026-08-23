"""WaterwayFeatures IR — the intermediate representation the ingest pipeline emits.

Source-agnostic: both the Overpass reader (now) and the future pyosmium bulk
reader (design step 6) populate these types via the pure functions in
`pound.ingest.filters`. Graph build (step 2b) consumes them.

Geometry is stored as a list of (lat, lon) tuples. The Overpass `out geom`
reader fills `geometry` but leaves `node_ids` empty (it does not return node
refs); the pyosmium bulk reader fills both. Connectivity (shared node refs) is
therefore a bulk-path concern, not an Overpass-reader concern — consistent with
this plan stopping before graph build.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class WaterwayKind(StrEnum):
    CANAL = "canal"
    RIVER = "river"
    FAIRWAY = "fairway"
    LOCK = "lock"  # waterway=lock chamber way, or way/node with lock=yes


class NodeKind(StrEnum):
    LOCK = "lock"
    LOCK_GATE = "lock_gate"
    MOVABLE_BRIDGE = "movable_bridge"
    MOORING = "mooring"
    MARINA = "marina"  # forward-compat; amenities/marinas are design step 5, not this plan
    PLACE = "place"
    OTHER = "other"


class PoiCategory(StrEnum):
    CANAL_SERVICE = "canal_service"
    PROVISIONS = "provisions"
    TRANSPORT = "transport"
    PEDESTRIAN_ACCESS = "pedestrian_access"


class OsmElementType(StrEnum):
    NODE = "node"
    WAY = "way"
    RELATION = "relation"


class PoiCandidate(BaseModel):
    osm_type: OsmElementType
    osm_id: int = Field(gt=0)
    category: PoiCategory
    kind: str
    name: str | None
    tags: dict[str, str]
    geometry_wkt: str
    geometry_source: Literal["point", "area", "derived_path"]

    @property
    def identity(self) -> tuple[OsmElementType, int, str]:
        return self.osm_type, self.osm_id, self.kind


class PoiIngestReport(BaseModel):
    skipped_counts: dict[str, int] = Field(default_factory=dict)
    skipped_examples: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("skipped_counts")
    @classmethod
    def validate_counts(cls, counts: dict[str, int]) -> dict[str, int]:
        if any(count < 0 for count in counts.values()):
            raise ValueError("skip counts must be nonnegative")
        return counts

    @field_validator("skipped_examples")
    @classmethod
    def cap_examples(cls, examples: dict[str, list[str]]) -> dict[str, list[str]]:
        return {reason: sorted(set(values))[:5] for reason, values in examples.items()}


class PointOfInterest(BaseModel):
    osm_type: OsmElementType
    osm_id: int = Field(gt=0)
    category: PoiCategory
    kind: str
    name: str | None
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    source_tags: dict[str, str]
    geometry_source: Literal["point", "area", "derived_path"]
    nearest_waterway_distance_m: float = Field(ge=0)
    nearest_edge: tuple[int, int]
    nearest_node_uid: int = Field(ge=0)
    projected_lat: float = Field(ge=-90, le=90)
    projected_lon: float = Field(ge=-180, le=180)

    @field_validator("nearest_edge")
    @classmethod
    def validate_nearest_edge(cls, edge: tuple[int, int]) -> tuple[int, int]:
        if edge[0] < 0 or edge[0] >= edge[1]:
            raise ValueError("nearest edge must be a canonical pair of distinct nonnegative UIDs")
        return edge

    @property
    def identity(self) -> tuple[OsmElementType, int, str]:
        return self.osm_type, self.osm_id, self.kind


@dataclass(frozen=True, order=True)
class AccessCaveat:
    osm_way_id: int
    tag: Literal["boat", "access"]
    value: str
    kind: Literal["discouraged", "unknown"]


class WayDimensions(BaseModel):
    """Restrictive dimensions on a way (min along a segment becomes the edge limit)."""

    max_beam_m: float | None = None
    max_length_m: float | None = None
    max_draft_m: float | None = None
    max_height_m: float | None = None


class WaterwayWay(BaseModel):
    osm_id: int
    kind: WaterwayKind
    name: str | None
    tags: dict[str, str]
    node_ids: list[int]  # empty when source is Overpass `out geom`
    geometry: list[tuple[float, float]]  # (lat, lon)
    dimensions: WayDimensions
    has_tunnel: bool = False
    has_movable_bridge: bool = False


class WaterwayNode(BaseModel):
    osm_id: int
    lat: float
    lon: float
    tags: dict[str, str]
    kind: NodeKind


class WaterwayFeatures(BaseModel):
    ways: list[WaterwayWay]
    nodes: list[WaterwayNode]
    source: str  # "overpass" | "geofabrik"
    fetched_at: str  # ISO 8601 timestamp
    bbox: tuple[float, float, float, float] | None  # (south, west, north, east)
    poi_candidates: list[PoiCandidate] = Field(default_factory=list)
    poi_ingest_report: PoiIngestReport = Field(default_factory=PoiIngestReport)
