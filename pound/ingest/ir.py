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

from enum import StrEnum

from pydantic import BaseModel


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
    OTHER = "other"


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
