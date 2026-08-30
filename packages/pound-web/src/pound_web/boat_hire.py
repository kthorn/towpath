"""Boat-hire seed parsing, anchoring, and reachability selection."""

import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlparse

import networkx as nx
from pound.route.cost import is_eligible, traversal_time_min

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


@dataclass(frozen=True)
class BoatHireAnchor:
    seed: BoatHireSeed
    edge: tuple[int, int]


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
    for seed in seeds:
        edge, _projected, distance_m = spatial_index.project_to_nearest_edge(
            seed.latitude, seed.longitude
        )
        limit_m = BOAT_HIRE_OVERLAY_DISTANCE_EXCEPTIONS_M.get(
            seed.identity, BOAT_HIRE_OVERLAY_DISTANCE_M
        )
        if not math.isfinite(distance_m) or distance_m > limit_m:
            raise ValueError(
                f"Boat-hire seed {seed.identity} is farther than {limit_m:g} m from a routing edge"
            )
        anchors.append(BoatHireAnchor(seed, edge))
    return tuple(anchors)


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
) -> nx.Graph:
    def edge_is_eligible(edge) -> bool:
        return is_eligible(
            boat_length_m,
            boat_beam_m,
            boat_draft_m,
            boat_height_m,
            edge["dimensions"],
        )[0]

    sources = {
        endpoint
        for anchor in anchors
        if edge_is_eligible(graph.edges[anchor.edge])
        for endpoint in anchor.edge
    }
    if not sources:
        return graph.edge_subgraph(())

    def weight(u, v, data):
        if not edge_is_eligible(data):
            return None
        return traversal_time_min(
            data,
            graph.nodes[v]["movable_bridge_ids"],
            movable_bridge_delay_min=movable_bridge_delay_min,
        )

    distances = nx.multi_source_dijkstra_path_length(
        graph,
        sources,
        cutoff=cutoff_min,
        weight=weight,
    )
    reached_edges = [
        (u, v)
        for u, v, data in graph.edges(data=True)
        if u in distances and v in distances and edge_is_eligible(data)
    ]
    overlay = graph.edge_subgraph(reached_edges).copy()
    eligible_degree = {
        node: sum(edge_is_eligible(graph.edges[node, neighbor]) for neighbor in graph[node])
        for node in overlay
    }
    protected = sources | {
        node
        for node, data in overlay.nodes(data=True)
        if (
            data["turning_point"]
            and (
                boat_length_m is None
                or data["turning_max_length_m"] is None
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
    return overlay
