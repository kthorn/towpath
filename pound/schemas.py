"""Shared Pydantic models — the frozen contract Pound and the Agent Core both import.

Per design §6. Field names are the integration seam; do not rename without
coordinating with labyrinth-core / labyrinth-agent.
"""

from pydantic import BaseModel, Field


class CanalConstraints(BaseModel):
    start: str
    end: str | None = None  # None => ring / round trip
    days: int = Field(gt=0)
    hours_per_day: float = Field(gt=0, default=6.0)
    boat_length_m: float | None = None
    boat_beam_m: float | None = None
    boat_draft_m: float | None = None
    boat_height_m: float | None = None
    amenity_prefs: list[str] = []  # ["pub", "water_point", "shop", ...]
    allow_derelict: bool = False


class ResolvedConstraints(BaseModel):
    """The pure-routing input: resolved graph node uids, not place names.

    `start_uid`/`end_uid` are the graph's own synthetic internal node handles
    (what `nx.shortest_path` consumes) — not coordinates, not place names.
    Carrying uids means plan_route literally cannot need a name lookup or a
    coord→uid mapping step: it operates on the handles the graph already
    understands. The CLI / Agent Core obtain a ResolvedConstraints from a
    CanalConstraints via route.resolve.resolve_place; a future map-click UI
    obtains one via route.resolve.resolve_coord(lat, lon, graph). Request-scoped
    — built by a resolver with graph access, consumed immediately, never
    persisted across differently-built artifacts. (design §4 contract evolution.)
    """

    start_uid: int
    end_uid: int
    days: int = Field(gt=0)
    hours_per_day: float = Field(gt=0, default=6.0)
    boat_length_m: float | None = None
    boat_beam_m: float | None = None
    boat_draft_m: float | None = None
    boat_height_m: float | None = None
    allow_derelict: bool = False


class Amenity(BaseModel):
    kind: str  # "pub" | "water_point" | "marina" | ...
    name: str | None
    lat: float
    lon: float
    distance_m: float  # from route
    source: str  # "osm" | "crt"


class RouteLeg(BaseModel):
    from_place: str
    to_place: str
    distance_km: float
    locks: int
    est_minutes: int
    flagged_unknown_dims: bool = False  # edge(s) lacked dimension tags


class DayPlan(BaseModel):
    day: int
    legs: list[RouteLeg]
    end_near: str | None  # mooring/town the day ends at
    cruising_minutes: int


class RouteResult(BaseModel):
    start: str
    end: str | None
    is_ring: bool
    legs: list[RouteLeg]
    days: list[DayPlan]
    total_km: float
    total_locks: int
    total_minutes: int
    amenities: list[Amenity]
    warnings: list[str] = []  # e.g. "draft unknown on 3 segments"
    graph_source_date: str  # provenance from the artifact
