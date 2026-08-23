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
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import polygonize_full

from pound.ingest import filters
from pound.ingest.diagnostics import PoiDiagnostics
from pound.ingest.filters import filter_navigable_ways
from pound.ingest.ir import (
    OsmElementType,
    PoiCandidate,
    PoiIngestReport,
    WaterwayFeatures,
    WaterwayKind,
    WaterwayNode,
    WaterwayWay,
    WayDimensions,
)
from pound.ingest.pois import classify_poi, normalize_source_tags
from pound.ingest.prune import prune_non_navigable_infra

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
  node["bridge"="movable"]{b};
  way["bridge:movable"]{b};
  way["bridge"="movable"]{b};
  node["mooring"]{b};
  nwr["waterway"="water_point"]{b};
  nwr["waterway"~"^(sanitary_station|fuel)$"]{b};
  nwr["amenity"~"^(sanitary_dump_station|fuel|pub|cafe|restaurant|taxi)$"]{b};
  nwr["shop"~"^(supermarket|convenience|bakery|greengrocer|butcher|deli|general)$"]{b};
  nwr["leisure"="marina"]{b};
  nwr["mooring"]{b};
  nwr["railway"~"^(station|halt)$"]{b};
  nwr["public_transport"~"^(platform|stop_position)$"]["bus"="yes"]{b};
  nwr["highway"~"^(footway|path|pedestrian|steps|bus_stop)$"]{b};
  nwr["entrance"]{b};
  nwr["barrier"~"^(gate|stile|kissing_gate|cycle_barrier)$"]{b};
);
(._;>>;);
out geom;"""


def _coordinates(geometry: list[dict]) -> list[tuple[float, float]] | None:
    if not geometry:
        return None
    try:
        coordinates = [(point["lon"], point["lat"]) for point in geometry]
    except (KeyError, TypeError):
        return None
    return coordinates if all(None not in coordinate for coordinate in coordinates) else None


def _way_coordinates(
    element: dict, elements_by_key: dict[tuple[str, int], dict]
) -> list[tuple[float, float]] | None:
    coordinates = _coordinates(element.get("geometry", []))
    if coordinates is not None:
        return coordinates
    node_ids = element.get("nodes") or []
    if not node_ids:
        return None
    nodes = [elements_by_key.get(("node", node_id)) for node_id in node_ids]
    if any(node is None for node in nodes):
        return None
    try:
        return [(node["lon"], node["lat"]) for node in nodes]
    except (KeyError, TypeError):
        return None


def _way_geometry(
    element: dict,
    elements_by_key: dict[tuple[str, int], dict],
    *,
    derived_path: bool,
) -> tuple[object | None, str | None]:
    coordinates = _way_coordinates(element, elements_by_key)
    if coordinates is None:
        return None, "missing_area_geometry"
    if derived_path:
        if len(coordinates) < 2:
            return None, "invalid_geometry"
        return LineString(coordinates), None
    if len(coordinates) < 4 or coordinates[0] != coordinates[-1]:
        return None, "invalid_geometry"
    polygon = Polygon(coordinates)
    if polygon.is_empty:
        return None, "invalid_geometry"
    return polygon, None


def _relation_rings(
    relation: dict,
    elements_by_key: dict[tuple[str, int], dict],
    visited: frozenset[int],
) -> list[tuple[str, list[tuple[float, float]]]] | None:
    relation_id = relation.get("id")
    if relation_id in visited:
        return None
    members = relation.get("members") or []
    if not members:
        return None
    rings: list[tuple[str, list[tuple[float, float]]]] = []
    next_visited = visited | {relation_id}
    for member in members:
        role = member.get("role")
        if role not in ("outer", "inner"):
            return None
        member_type = member.get("type")
        if member_type == "way":
            coordinates = _coordinates(member.get("geometry", []))
            if coordinates is None:
                referenced = elements_by_key.get((member_type, member.get("ref")))
                if referenced is None:
                    return None
                coordinates = _way_coordinates(referenced, elements_by_key)
            if coordinates is None or len(coordinates) < 2:
                return None
            rings.append((role, coordinates))
        elif member_type == "relation":
            referenced = elements_by_key.get((member_type, member.get("ref")))
            if referenced is None:
                return None
            nested = _relation_rings(referenced, elements_by_key, next_visited)
            if nested is None:
                return None
            # The containing member role defines how the nested area participates.
            if role == "inner":
                nested = [
                    ("inner" if nested_role == "outer" else "outer", coords)
                    for nested_role, coords in nested
                ]
            rings.extend(nested)
        else:
            return None
    return rings


def _relation_geometry(
    relation: dict, elements_by_key: dict[tuple[str, int], dict]
) -> object | None:
    rings = _relation_rings(relation, elements_by_key, frozenset())
    if rings is None:
        return None
    outer_result = polygonize_full(
        [LineString(coords) for role, coords in rings if role == "outer"]
    )
    inner_result = polygonize_full(
        [LineString(coords) for role, coords in rings if role == "inner"]
    )
    outer_polygons, outer_cuts, outer_dangles, outer_invalid = outer_result
    inner_polygons, inner_cuts, inner_dangles, inner_invalid = inner_result
    if any(
        not remainder.is_empty
        for remainder in (
            outer_cuts,
            outer_dangles,
            outer_invalid,
            inner_cuts,
            inner_dangles,
            inner_invalid,
        )
    ):
        return None
    outers = list(outer_polygons.geoms)
    inners = list(inner_polygons.geoms)
    if not outers:
        return None
    holes: list[list[list[tuple[float, float]]]] = [[] for _ in outers]
    for inner in inners:
        containing = [index for index, outer in enumerate(outers) if outer.contains(inner)]
        if len(containing) != 1:
            return None
        holes[containing[0]].append(list(inner.exterior.coords))
    polygons = [Polygon(outer.exterior.coords, holes[index]) for index, outer in enumerate(outers)]
    if any(polygon.is_empty for polygon in polygons):
        return None
    return polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)


def _poi_geometry(
    element: dict, elements_by_key: dict[tuple[str, int], dict]
) -> tuple[object | None, str | None, str]:
    element_type = element["type"]
    if element_type == "node":
        try:
            return Point(element["lon"], element["lat"]), None, "point"
        except (KeyError, TypeError):
            return None, "missing_area_geometry", "point"
    if element_type == "relation":
        geometry = _relation_geometry(element, elements_by_key)
        return geometry, None if geometry is not None else "incomplete_relation_geometry", "area"
    tags = element.get("tags") or {}
    derived_path = tags.get("highway") in {"footway", "path", "pedestrian"}
    geometry, reason = _way_geometry(element, elements_by_key, derived_path=derived_path)
    return geometry, reason, "derived_path" if derived_path else "area"


def _parse_pois(elements: list[dict]) -> tuple[list[PoiCandidate], PoiIngestReport]:
    elements_by_key = {
        (element.get("type"), element.get("id")): element
        for element in elements
        if element.get("type") in {"node", "way", "relation"} and "id" in element
    }
    candidates: dict[tuple[OsmElementType, int, str], PoiCandidate] = {}
    diagnostics = PoiDiagnostics()

    seen_elements: set[tuple[str, int]] = set()
    decoded_elements: set[tuple[str, int]] = set()
    for element in elements:
        element_type = element.get("type")
        element_id = element.get("id")
        if element_type not in {"node", "way", "relation"} or not isinstance(element_id, int):
            continue
        source_identity = f"{element_type}/{element_id}"
        tags = element.get("tags") or {}
        classifications = classify_poi(tags)
        key = (element_type, element_id)
        if key not in seen_elements:
            for diagnostic in getattr(classifications, "skips", ()):
                diagnostics.record(
                    diagnostic.reason,
                    f"{source_identity}:{diagnostic.key}={diagnostic.value}",
                )
            seen_elements.add(key)
        if not classifications:
            continue
        geometry, reason, geometry_source = _poi_geometry(element, elements_by_key)
        if geometry is None:
            if key not in decoded_elements:
                diagnostics.record(reason or "invalid_geometry", source_identity)
                decoded_elements.add(key)
            continue
        decoded_elements.add(key)
        for classification in classifications:
            candidate = PoiCandidate(
                osm_type=OsmElementType(element_type),
                osm_id=element_id,
                category=classification.category,
                kind=classification.kind,
                name=tags.get("name"),
                tags=normalize_source_tags(tags, classification),
                geometry_wkt=geometry.wkt,
                geometry_source=geometry_source,
            )
            candidates.setdefault(candidate.identity, candidate)
    ordered = sorted(
        candidates.values(),
        key=lambda candidate: (
            candidate.osm_type.value,
            candidate.osm_id,
            candidate.category.value,
            candidate.kind,
        ),
    )
    return ordered, diagnostics.build_report()


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

    poi_candidates, poi_ingest_report = _parse_pois(elements)
    return WaterwayFeatures(
        ways=ways,
        nodes=nodes,
        source=source,
        fetched_at=osm_timestamp if osm_timestamp is not None else datetime.now(UTC).isoformat(),
        bbox=bbox,
        poi_candidates=poi_candidates,
        poi_ingest_report=poi_ingest_report,
    )


def fetch_oxford() -> WaterwayFeatures:
    """Live network: fetch the Oxford Canal extract, prune infra nodes on
    non-navigable ways, then filter navigable ways.

    Ordering: prune BEFORE filter. prune needs boat=no ways present to decide
    "all incidents non-navigable"; see the spec's load-bearing ordering note.
    """
    raw = fetch_raw(OXFORD_BBOX)
    osm_timestamp = raw.get("osm3s", {}).get("timestamp_osm_base")
    features = parse(raw["elements"], OXFORD_BBOX, osm_timestamp=osm_timestamp)
    # prune BEFORE filter: prune needs boat=no ways present to decide
    # "all incidents non-navigable"; see the spec's load-bearing ordering note.
    features = prune_non_navigable_infra(features)
    features = filter_navigable_ways(features)
    return features
