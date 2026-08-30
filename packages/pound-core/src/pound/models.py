from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class WaterwayKind(StrEnum):
    CANAL = "canal"
    RIVER = "river"
    FAIRWAY = "fairway"
    LOCK = "lock"


class PoiCategory(StrEnum):
    CANAL_SERVICE = "canal_service"
    PROVISIONS = "provisions"
    TRANSPORT = "transport"
    PEDESTRIAN_ACCESS = "pedestrian_access"


class OsmElementType(StrEnum):
    NODE = "node"
    WAY = "way"
    RELATION = "relation"


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


@dataclass(frozen=True, slots=True)
class RuntimePoi:
    osm_type: OsmElementType
    osm_id: int
    category: PoiCategory
    kind: str
    name: str | None
    lat: float
    lon: float


POI_CORRIDOR_M = {
    PoiCategory.CANAL_SERVICE: 250.0,
    PoiCategory.PEDESTRIAN_ACCESS: 250.0,
    PoiCategory.PROVISIONS: 1000.0,
    PoiCategory.TRANSPORT: 1000.0,
}

RETAINED_POI_KINDS = frozenset(
    {
        "water_point",
        "sanitary_disposal",
        "fuel",
        "marina",
        "mooring",
        "pub",
        "cafe",
        "restaurant",
        "supermarket",
        "convenience",
        "bakery",
        "greengrocer",
        "butcher",
        "deli",
        "general",
        "rail_station",
        "rail_halt",
        "bus_stop",
        "taxi_rank",
        "entrance",
        "path_connection",
        "pedestrian_bridge",
        "steps",
        "gate",
        "stile",
        "kissing_gate",
        "cycle_barrier",
    }
)
