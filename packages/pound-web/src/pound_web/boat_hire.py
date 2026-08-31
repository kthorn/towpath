"""Boat-hire seed parsing, anchoring, and reachability selection."""

import csv
import math
import re
from dataclasses import dataclass
from heapq import heappop, heappush
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlparse

import networkx as nx
from pound.models import WayDimensions  # pyright: ignore[reportMissingImports]
from pound.route.cost import (  # pyright: ignore[reportMissingImports]
    is_eligible,
    partial_traversal_time_min,
    traversal_time_min,
)
from pound.route.project import metric_edge_line  # pyright: ignore[reportMissingImports]
from pound.schemas import CanalPointHandle, Coordinate  # pyright: ignore[reportMissingImports]
from pyproj import Transformer  # pyright: ignore[reportMissingImports]
from shapely import transform
from shapely.ops import substring

BOAT_HIRE_ENRICHMENT_FIELDS: tuple[str, ...] = (
    "record_type",
    "source_provider_id",
    "source_provider_name",
    "source_provider_website",
    "operator_id",
    "operator_name",
    "location_id",
    "location_name",
    "location_area",
    "waterway",
    "review_identity",
    "review_rank",
    "osm_url",
    "latitude",
    "longitude",
    "source_url",
    "source_kind",
    "google_search_url",
    "existing_website",
    "official_location_name",
    "booking_url",
    "hire_type",
    "evidence_url",
    "phone",
    "email",
    "enrichment_status",
    "notes",
    "exclude",
)

BOAT_HIRE_OVERLAY_DISTANCE_M: float = 250.0
BOAT_HIRE_OVERLAY_DISTANCE_EXCEPTIONS_M: dict[str, float] = {
    "canal-holidays/base:62": 251.0,
}
_ALLOWED_EXCLUDE_VALUES = frozenset({"", "true", "false"})
_ALLOWED_RECORD_TYPES = frozenset({"company_base", "review_positive"})
_OSM_PATH = re.compile(r"^/(node|way|relation)/([1-9][0-9]*)$")
_TO_WGS84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)


@dataclass(frozen=True)
class OsmIdentity:
    osm_type: Literal["node", "way", "relation"]
    osm_id: int


@dataclass(frozen=True)
class BoatHireSeed:
    source_provider_id: str
    location_id: str
    latitude: float
    longitude: float
    source_provider_name: str = ""
    location_name: str = ""
    record_type: str = "company_base"
    source_provider_website: str = ""
    osm_url: str = ""
    evidence_url: str = ""
    booking_url: str = ""

    @property
    def is_public_place(self) -> bool:
        return self.record_type == "company_base"

    @property
    def osm_identity(self) -> OsmIdentity | None:
        return _parse_osm_identity(self.osm_url)

    @property
    def identity(self) -> str:
        return f"{self.source_provider_id}/{self.location_id}"

    @property
    def operator(self) -> str:
        return self.source_provider_name or self.source_provider_id

    @property
    def name(self) -> str:
        return self.location_name or self.location_id


@dataclass(frozen=True, slots=True)
class BoatHireAnchor:
    seed: BoatHireSeed
    handle: CanalPointHandle
    coordinate: Coordinate | None = None
    snap_distance_m: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.handle, CanalPointHandle):
            edge = tuple(sorted(self.handle))
            object.__setattr__(self, "handle", CanalPointHandle(edge=edge, fraction=0.0))
        if self.coordinate is None:
            object.__setattr__(
                self,
                "coordinate",
                Coordinate(lat=self.seed.latitude, lon=self.seed.longitude),
            )
        if self.snap_distance_m is None:
            object.__setattr__(self, "snap_distance_m", 0.0)

    @property
    def edge(self) -> tuple[int, int]:
        """Compatibility view of the canonical projected handle edge."""
        return cast(Any, self.handle).edge

    @property
    def projected(self) -> Coordinate:
        """Projected WGS84 coordinate retained for reporting and diagnostics."""
        return cast(Coordinate, self.coordinate)


@dataclass(frozen=True, slots=True)
class ReachabilityGeometry:
    """Immutable full-edge and clipped-source geometry selected for an overlay."""

    full_edge_keys: tuple[tuple[int, int], ...]
    clipped_lines: tuple[tuple[tuple[float, float], ...], ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "full_edge_keys", tuple(tuple(edge) for edge in self.full_edge_keys)
        )
        object.__setattr__(
            self,
            "clipped_lines",
            tuple(tuple(tuple(point) for point in line) for line in self.clipped_lines),
        )

    @property
    def edges(self) -> tuple[tuple[int, int], ...]:
        """Compatibility view used by callers that only inspect full edges."""
        return self.full_edge_keys

    @property
    def nodes(self) -> tuple[int, ...]:
        return tuple(sorted({uid for edge in self.full_edge_keys for uid in edge}))


def _is_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _parse_osm_identity(osm_url: str) -> OsmIdentity | None:
    if not osm_url:
        return None
    parsed = urlparse(osm_url)
    match = _OSM_PATH.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "www.openstreetmap.org"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or match is None
    ):
        return None
    return OsmIdentity(cast(Any, match.group(1)), int(match.group(2)))


def load_boat_hire_seeds(path: Path) -> tuple[BoatHireSeed, ...]:
    """Validate the enrichment CSV and return its non-excluded seeds in row order."""
    try:
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            rows = list(reader)
            fieldnames = reader.fieldnames
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"Could not read boat-hire enrichment CSV {path}") from exc
    if fieldnames is None:
        raise ValueError(f"Boat-hire enrichment CSV {path} is empty or unreadable")
    if fieldnames != list(BOAT_HIRE_ENRICHMENT_FIELDS):
        raise ValueError(
            f"Boat-hire enrichment CSV {path} header does not match the expected fields"
        )

    seeds: list[BoatHireSeed] = []
    seen_identities: set[tuple[str, str]] = set()
    for row_number, row in enumerate(rows, start=2):
        if None in row:
            raise ValueError(f"Boat-hire enrichment CSV {path} row {row_number} has surplus cells")
        provider = row["source_provider_id"]
        location = row["location_id"]
        identity = f"{provider}/{location}"
        if not provider or not location:
            raise ValueError(
                f"Boat-hire enrichment CSV {path} row {row_number} requires nonblank "
                "source_provider_id and location_id"
            )
        if (provider, location) in seen_identities:
            raise ValueError(
                f"Boat-hire enrichment CSV {path} row {row_number} duplicates "
                f"(source_provider_id, location_id) {identity!r}"
            )
        seen_identities.add((provider, location))
        exclude = row["exclude"]
        if exclude not in _ALLOWED_EXCLUDE_VALUES:
            raise ValueError(
                f"Boat-hire enrichment CSV {path} row {row_number} ({identity}) has "
                f"unsupported exclude value {exclude!r}"
            )
        record_type = row["record_type"]
        if record_type not in _ALLOWED_RECORD_TYPES:
            raise ValueError(
                f"Boat-hire enrichment CSV {path} row {row_number} ({identity}) has "
                f"unsupported record_type {record_type!r}"
            )
        if exclude == "true":
            continue
        try:
            latitude = float(row["latitude"])
            longitude = float(row["longitude"])
        except ValueError as exc:
            raise ValueError(
                f"Boat-hire enrichment CSV {path} row {row_number} ({identity}) has "
                "non-numeric coordinates"
            ) from exc
        if not math.isfinite(latitude):
            raise ValueError(
                f"Boat-hire enrichment CSV {path} row {row_number} ({identity}) "
                "latitude must be finite"
            )
        if not math.isfinite(longitude):
            raise ValueError(
                f"Boat-hire enrichment CSV {path} row {row_number} ({identity}) "
                "longitude must be finite"
            )
        if not -90.0 <= latitude <= 90.0:
            raise ValueError(
                f"Boat-hire enrichment CSV {path} row {row_number} ({identity}) "
                "latitude must be in [-90, 90]"
            )
        if not -180.0 <= longitude <= 180.0:
            raise ValueError(
                f"Boat-hire enrichment CSV {path} row {row_number} ({identity}) "
                "longitude must be in [-180, 180]"
            )
        if record_type == "company_base":
            for field in ("source_provider_website", "evidence_url", "booking_url"):
                value = row[field]
                if value and not _is_https_url(value):
                    raise ValueError(
                        f"Boat-hire enrichment CSV {path} row {row_number} ({identity}) "
                        f"{field} must be an absolute HTTPS URL"
                    )
            if not (_is_https_url(row["osm_url"]) or _is_https_url(row["evidence_url"])):
                raise ValueError(
                    f"Boat-hire enrichment CSV {path} row {row_number} ({identity}) must "
                    "provide an absolute HTTPS osm_url or evidence_url"
                )
            osm_url = row["osm_url"]
            if osm_url and _parse_osm_identity(osm_url) is None:
                raise ValueError(
                    f"Boat-hire enrichment CSV {path} row {row_number} ({identity}) "
                    "osm_url must be a canonical https://www.openstreetmap.org/"
                    "{node|way|relation}/{id} URL"
                )
        seeds.append(
            BoatHireSeed(
                provider,
                location,
                latitude,
                longitude,
                row["source_provider_name"],
                row["location_name"],
                record_type,
                row["source_provider_website"],
                row["osm_url"],
                row["evidence_url"],
                row["booking_url"],
            )
        )
    return tuple(seeds)


def snap_boat_hire_bases(spatial_index, seeds):
    anchors = []
    candidate_index = getattr(spatial_index, "candidate_index", None)
    for seed in seeds:
        if candidate_index is not None:
            projected_result = candidate_index.nearest_projection(seed.latitude, seed.longitude)
            if projected_result is None:
                raise ValueError(f"Boat-hire seed {seed.identity} could not be projected")
            projected, distance_m = projected_result
            handle = projected.handle
            coordinate = projected.coordinate
        else:
            edge, projected, distance_m = spatial_index.project_to_nearest_edge(
                seed.latitude, seed.longitude
            )
            handle = CanalPointHandle(edge=tuple(sorted(edge)), fraction=0.0)
            coordinate = Coordinate(lat=float(projected.y), lon=float(projected.x))
        limit_m = BOAT_HIRE_OVERLAY_DISTANCE_EXCEPTIONS_M.get(
            seed.identity, BOAT_HIRE_OVERLAY_DISTANCE_M
        )
        if not math.isfinite(distance_m) or distance_m > limit_m:
            raise ValueError(
                f"Boat-hire seed {seed.identity} is farther than {limit_m:g} m from a routing edge"
            )
        anchors.append(BoatHireAnchor(seed, handle, coordinate, float(distance_m)))
    return tuple(anchors)


def _canonical_edge(edge: tuple[int, int]) -> tuple[int, int]:
    return min(edge[0], edge[1]), max(edge[0], edge[1])


def _partial_seed_cost(
    data: dict[str, Any],
    fraction: float,
    endpoint: int,
    graph: nx.Graph,
    bridge_delay_min: float,
) -> float:
    if fraction == 0:
        return 0.0
    return partial_traversal_time_min(
        data,
        fraction,
        graph.nodes[endpoint].get("movable_bridge_ids", ()),
        movable_bridge_delay_min=bridge_delay_min,
    )


def _reachable_side_fraction(
    data: dict[str, Any],
    side_fraction: float,
    endpoint: int,
    graph: nx.Graph,
    cutoff_min: float,
    bridge_delay_min: float,
) -> float:
    if side_fraction <= 0:
        return 0.0
    endpoint_cost = _partial_seed_cost(data, side_fraction, endpoint, graph, bridge_delay_min)
    if endpoint_cost <= cutoff_min + 1e-9:
        return side_fraction
    cruising_cost = partial_traversal_time_min(
        data, 1.0, (), movable_bridge_delay_min=bridge_delay_min
    )
    if cruising_cost <= 0:
        return 0.0
    fraction = min(side_fraction, cutoff_min / cruising_cost)
    if fraction >= side_fraction:
        return math.nextafter(side_fraction, 0.0)
    return max(0.0, fraction)


def _clipped_source_line(
    graph: nx.Graph,
    edge: tuple[int, int],
    fraction: float,
    data: dict[str, Any],
    cutoff_min: float,
    bridge_delay_min: float,
) -> tuple[tuple[float, float], ...] | None:
    if not data.get("geometry"):
        return None
    line = metric_edge_line(graph, edge)
    if line.length <= 0:
        return None
    low_reach = _reachable_side_fraction(
        data, fraction, edge[0], graph, cutoff_min, bridge_delay_min
    )
    high_reach = _reachable_side_fraction(
        data, 1.0 - fraction, edge[1], graph, cutoff_min, bridge_delay_min
    )
    low = max(0.0, fraction - low_reach) * line.length
    high = min(1.0, fraction + high_reach) * line.length
    if high - low <= 1e-9:
        return None
    clipped = substring(line, low, high)
    if clipped.is_empty or not hasattr(clipped, "coords"):
        return None
    wgs84 = transform(clipped, cast(Any, _TO_WGS84.transform), interleaved=False)
    return tuple((float(y), float(x)) for x, y in wgs84.coords)


def select_boat_hire_reachability(
    graph: nx.Graph,
    anchors: tuple[BoatHireAnchor, ...],
    *,
    cutoff_min: float,
    boat_length_m: float | None,
    boat_beam_m: float | None,
    boat_draft_m: float | None,
    boat_height_m: float | None,
    movable_bridge_delay_min: float,
) -> ReachabilityGeometry:
    if not math.isfinite(cutoff_min) or cutoff_min < 0:
        raise ValueError("cutoff_min must be finite and non-negative")

    def edge_is_eligible(data: dict[str, Any]) -> bool:
        return is_eligible(
            boat_length_m,
            boat_beam_m,
            boat_draft_m,
            boat_height_m,
            data.get("dimensions", WayDimensions()),
        )[0]

    distances: dict[int, float] = {}
    queue: list[tuple[float, int]] = []
    sources: set[int] = set()
    source_edges: list[tuple[tuple[int, int], float, dict[str, Any]]] = []
    for anchor in anchors:
        handle: Any = anchor.handle
        edge = _canonical_edge(handle.edge)
        if not graph.has_edge(*edge):
            continue
        data = graph.edges[edge]
        if not edge_is_eligible(data):
            continue
        fraction = handle.fraction
        source_edges.append((edge, fraction, data))
        for endpoint, side_fraction in ((edge[0], fraction), (edge[1], 1.0 - fraction)):
            cost = _partial_seed_cost(
                data, side_fraction, endpoint, graph, movable_bridge_delay_min
            )
            if cost > cutoff_min + 1e-9:
                continue
            if cost < distances.get(endpoint, math.inf):
                distances[endpoint] = cost
                sources.add(endpoint)
                heappush(queue, (cost, endpoint))

    while queue:
        cost, node = heappop(queue)
        if cost != distances.get(node):
            continue
        for neighbor in sorted(graph.neighbors(node)):
            data = graph.edges[node, neighbor]
            if not edge_is_eligible(data):
                continue
            edge_cost = traversal_time_min(
                data,
                graph.nodes[neighbor].get("movable_bridge_ids", ()),
                movable_bridge_delay_min=movable_bridge_delay_min,
            )
            candidate = cost + edge_cost
            if candidate > cutoff_min + 1e-9:
                continue
            if candidate < distances.get(neighbor, math.inf):
                distances[neighbor] = candidate
                heappush(queue, (candidate, neighbor))

    full_edge_keys = tuple(
        sorted(
            edge
            for edge in {_canonical_edge((u, v)) for u, v in graph.edges}
            if edge[0] in distances and edge[1] in distances and edge_is_eligible(graph.edges[edge])
        )
    )
    overlay = graph.edge_subgraph(full_edge_keys).copy()
    eligible_degree = {
        node: sum(edge_is_eligible(graph.edges[node, neighbor]) for neighbor in graph[node])
        for node in overlay
    }
    protected = sources | {
        node
        for node, data in overlay.nodes(data=True)
        if (
            data.get("turning_point", False)
            and (
                boat_length_m is None
                or data.get("turning_max_length_m") is None
                or boat_length_m <= data["turning_max_length_m"]
            )
        )
        or eligible_degree[node] >= 3
    }
    leaves = [node for node in overlay if overlay.degree[node] <= 1 and node not in protected]
    while leaves:
        node = leaves.pop()
        if node not in overlay or node in protected or overlay.degree[node] > 1:
            continue
        neighbors = list(overlay.neighbors(node))
        overlay.remove_node(node)
        leaves.extend(
            neighbor
            for neighbor in neighbors
            if neighbor in overlay and neighbor not in protected and overlay.degree[neighbor] <= 1
        )
    full_edge_keys = tuple(sorted(_canonical_edge(edge) for edge in overlay.edges))
    full_edges = set(full_edge_keys)
    clipped_lines = tuple(
        clipped
        for edge, fraction, data in source_edges
        if edge not in full_edges
        if (
            clipped := _clipped_source_line(
                graph,
                edge,
                fraction,
                data,
                cutoff_min,
                movable_bridge_delay_min,
            )
        )
        is not None
    )
    return ReachabilityGeometry(full_edge_keys, clipped_lines)
