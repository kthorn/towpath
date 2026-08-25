"""Startup-only boat-hire overlay seed parsing and component selection."""

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import networkx as nx

from pound.graph.spatial import GraphSpatialIndex

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


@dataclass(frozen=True)
class BoatHireSeed:
    source_provider_id: str
    location_id: str
    latitude: float
    longitude: float

    @property
    def identity(self) -> str:
        return f"{self.source_provider_id}/{self.location_id}"


def _is_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


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
        evidence_url = row["evidence_url"]
        if evidence_url and not _is_https_url(evidence_url):
            raise ValueError(
                f"Boat-hire enrichment CSV {path} row {row_number} ({identity}) "
                "evidence_url must be an absolute HTTPS URL"
            )
        if not (_is_https_url(row["osm_url"]) or _is_https_url(evidence_url)):
            raise ValueError(
                f"Boat-hire enrichment CSV {path} row {row_number} ({identity}) must "
                "provide an absolute HTTPS osm_url or evidence_url"
            )
        seeds.append(BoatHireSeed(provider, location, latitude, longitude))
    return tuple(seeds)


def select_boat_hire_overlay(
    graph: nx.Graph,
    spatial_index: GraphSpatialIndex,
    seeds: tuple[BoatHireSeed, ...],
) -> nx.Graph:
    """Return a node-induced view of every full-graph component containing a seed."""
    component_by_node = {
        node: component for component in nx.connected_components(graph) for node in component
    }
    selected_nodes: set[int] = set()
    for seed in seeds:
        try:
            edge, _projected, distance_m = spatial_index.project_to_nearest_edge(
                seed.latitude, seed.longitude
            )
        except ValueError as exc:
            raise ValueError(f"Could not project boat-hire seed {seed.identity}") from exc
        limit_m = BOAT_HIRE_OVERLAY_DISTANCE_EXCEPTIONS_M.get(
            seed.identity,
            BOAT_HIRE_OVERLAY_DISTANCE_M,
        )
        if not math.isfinite(distance_m) or distance_m > limit_m:
            raise ValueError(
                f"Boat-hire seed {seed.identity} is farther than {limit_m:g} m from a routing edge"
            )
        selected_nodes.update(component_by_node[edge[0]])
    return graph.subgraph(selected_nodes)
