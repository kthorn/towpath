"""Overpass JSON reader — SCAFFOLDING.

Thin wrapper that builds an Overpass QL query, fetches JSON via `requests`, and
calls the pure functions in `pound.ingest.filters` to build a `WaterwayFeatures`
IR. Replaced by a pyosmium/osmium bulk reader over the Geofabrik GB PBF in
design step 6; the pure functions and IR survive that swap.

Network use is confined to `fetch_raw`/`fetch_oxford`. `parse()` is pure and
unit-tested against a committed fixture.
"""

from datetime import UTC, datetime

import requests

from pound.ingest import filters
from pound.ingest.ir import (
    WaterwayFeatures,
    WaterwayKind,
    WaterwayNode,
    WaterwayWay,
    WayDimensions,
)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Oxford Canal around Oxford: Duke's Cut (Thames junction) -> city -> up past
# the Hayfield/Isis lock flight toward Kidlington. (south, west, north, east).
OXFORD_BBOX = (51.70, -1.35, 51.80, -1.20)

# Ways we pull as routable/lock edges.
_WAY_WATERWAY_RE = "^(canal|river|fairway|lock)$"


def build_query(bbox: tuple[float, float, float, float]) -> str:
    s, w, n, e = bbox
    b = f"({s},{w},{n},{e})"
    return f"""[out:json][timeout:60];
(
  way["waterway"~"{_WAY_WATERWAY_RE}"]{b};
  way["lock"="yes"]{b};
  node["waterway"="lock_gate"]{b};
  node["lock"="yes"]{b};
  node["bridge:movable"]{b};
  way["bridge:movable"]{b};
  node["mooring"]{b};
);
out geom;"""


def fetch_raw(
    bbox: tuple[float, float, float, float] = OXFORD_BBOX,
    url: str = OVERPASS_URL,
    timeout: float = 120.0,
) -> dict:
    """Fetch raw Overpass JSON (live network). Returns the parsed `elements` container."""
    resp = requests.post(url, data={"data": build_query(bbox)}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def parse(
    elements: list[dict],
    bbox: tuple[float, float, float, float] | None,
    source: str = "overpass",
    osm_timestamp: str | None = None,
) -> WaterwayFeatures:
    """Pure: turn Overpass `elements` into a WaterwayFeatures IR via `filters`.

    Args:
        osm_timestamp: OSM base timestamp from `osm3s.timestamp_osm_base`, used
            for provenance. Falls back to the current time when not provided.
    """
    ways: list[WaterwayWay] = []
    nodes: list[WaterwayNode] = []
    for el in elements:
        el_type = el.get("type")
        tags = el.get("tags") or {}
        if el_type == "way":
            if filters.is_derelict(tags):
                continue
            kind = filters.classify_way(tags)
            if kind is None:
                continue  # not a waterway/lock way we keep (e.g. amenities are step 5)
            geometry = [(g["lat"], g["lon"]) for g in el.get("geometry", [])]
            dims: WayDimensions = filters.extract_dimensions(tags)
            ways.append(
                WaterwayWay(
                    osm_id=el["id"],
                    kind=kind,
                    name=tags.get("name"),
                    tags=tags,
                    node_ids=list(el.get("nodes", [])),  # empty under `out geom`
                    geometry=geometry,
                    dimensions=dims,
                    has_tunnel=tags.get("tunnel") == "yes",
                    has_movable_bridge=(
                        "bridge:movable" in tags or tags.get("bridge") == "movable"
                    ),
                )
            )
        elif el_type == "node":
            kind = filters.classify_node(tags)
            if kind is None:
                continue  # amenity POIs etc. dropped here (design step 5)
            nodes.append(
                WaterwayNode(
                    osm_id=el["id"],
                    lat=el["lat"],
                    lon=el["lon"],
                    tags=tags,
                    kind=kind,
                )
            )

    routable = {WaterwayKind.CANAL, WaterwayKind.RIVER, WaterwayKind.FAIRWAY}
    # ordering: routable ways first, then locks — stable for summarize/tests
    ways.sort(key=lambda w: (0 if w.kind in routable else 1, w.osm_id))

    return WaterwayFeatures(
        ways=ways,
        nodes=nodes,
        source=source,
        fetched_at=osm_timestamp if osm_timestamp is not None else datetime.now(UTC).isoformat(),
        bbox=bbox,
    )


def fetch_oxford() -> WaterwayFeatures:
    """Live network: fetch the Oxford Canal extract and parse it."""
    raw = fetch_raw(OXFORD_BBOX)
    osm_timestamp = raw.get("osm3s", {}).get("timestamp_osm_base")
    return parse(raw["elements"], OXFORD_BBOX, osm_timestamp=osm_timestamp)
