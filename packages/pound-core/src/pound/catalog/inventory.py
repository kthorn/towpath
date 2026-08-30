"""Tag-only inventory of user-facing records in the original OSM source."""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pound.catalog.manifest import CATALOG_KINDS


@dataclass(frozen=True)
class CatalogInventory:
    source: str
    scanned_objects: int
    candidate_objects: int
    counts_by_kind: dict[str, int]
    tag_coverage_by_kind: dict[str, dict[str, int]]
    excluded_counts: dict[str, int]


_CANDIDATE_TAGS: tuple[tuple[str, str, str], ...] = (
    ("amenity", "pub", "pub"),
    ("amenity", "cafe", "cafe"),
    ("amenity", "restaurant", "restaurant"),
    ("shop", "supermarket", "supermarket"),
    ("shop", "convenience", "convenience"),
    ("shop", "bakery", "bakery"),
    ("shop", "greengrocer", "greengrocer"),
    ("shop", "butcher", "butcher"),
    ("shop", "deli", "deli"),
    ("shop", "general", "general"),
    ("amenity", "sanitary_dump_station", "sanitary_disposal"),
    ("waterway", "sanitary_station", "sanitary_disposal"),
    ("amenity", "fuel", "fuel"),
    ("waterway", "fuel", "fuel"),
    ("waterway", "water_point", "water_point"),
    ("leisure", "marina", "marina"),
    ("tourism", "museum", "museum"),
    ("tourism", "gallery", "gallery"),
    ("leisure", "garden", "garden"),
    ("tourism", "botanical_garden", "garden"),
    ("tourism", "zoo", "wildlife_attraction"),
    ("tourism", "aquarium", "wildlife_attraction"),
    ("tourism", "wildlife_hide", "wildlife_attraction"),
    ("tourism", "attraction", "landmark"),
    ("tourism", "viewpoint", "landmark"),
    ("tourism", "theme_park", "landmark"),
    ("tourism", "water_park", "landmark"),
)
_HISTORIC_SITE_VALUES = frozenset(
    {
        "archaeological_site",
        "battlefield",
        "castle",
        "church",
        "city_gate",
        "fort",
        "manor",
        "memorial",
        "mine",
        "monument",
        "ruins",
        "tomb",
        "wayside_cross",
        "wreck",
    }
)
_TRANSPORT_TAGS = {
    ("amenity", "taxi"),
    ("highway", "bus_stop"),
    ("railway", "halt"),
    ("railway", "station"),
}
_PEDESTRIAN_TAGS = {
    ("highway", "footway"),
    ("highway", "path"),
    ("highway", "pedestrian"),
    ("highway", "steps"),
    ("barrier", "cycle_barrier"),
    ("barrier", "gate"),
    ("barrier", "kissing_gate"),
    ("barrier", "stile"),
}
_INACTIVE_KEYS = {"abandoned", "disused", "razed", "removed"}
_ARTWORK_KEYS = ("artist_name", "artwork_type")


def _build_catalog_tag_filter_expr() -> str:
    values_by_key: dict[str, list[str]] = {}
    for key, value, _kind in _CANDIDATE_TAGS:
        if value not in values_by_key.setdefault(key, []):
            values_by_key[key].append(value)
    lines = [f"nwr/{key}={','.join(values)}" for key, values in values_by_key.items()]
    lines.append("nwr/mooring")
    lines.append(f"nwr/historic={','.join(sorted(_HISTORIC_SITE_VALUES))}")
    return "\n".join(lines) + "\n"


CATALOG_TAG_FILTER_EXPR = _build_catalog_tag_filter_expr()


def inventory_pbf(path: Path) -> CatalogInventory:
    """Scan node, way, and relation tags from an original PBF or OSM XML file."""
    import osmium

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)

    counts: Counter[str] = Counter()
    coverage: dict[str, Counter[str]] = {}
    excluded: Counter[str] = Counter()
    seen_sources: set[tuple[str, int]] = set()
    scanned_objects = 0
    candidate_objects = 0

    for obj in osmium.FileProcessor(str(path)):
        scanned_objects += 1
        object_type = type(obj).__name__.lower()
        source_identity = (object_type, obj.id)
        if source_identity in seen_sources:
            excluded["duplicate"] += 1
            continue
        seen_sources.add(source_identity)

        tags = {tag.k: tag.v for tag in obj.tags}
        if _is_inactive(tags):
            excluded["inactive"] += 1
            continue
        if _is_artwork(tags):
            excluded["artwork"] += 1
            continue

        kind = _candidate_kind(tags)
        if kind is not None and kind in CATALOG_KINDS and tags.get("name", "").strip():
            candidate_objects += 1
            counts[kind] += 1
            kind_coverage = coverage.setdefault(kind, Counter())
            kind_coverage.update(tags.keys())
            continue

        if _is_transport(tags):
            excluded["transport"] += 1
        elif _is_pedestrian_access(tags):
            excluded["pedestrian_access"] += 1

    return CatalogInventory(
        source=str(path),
        scanned_objects=scanned_objects,
        candidate_objects=candidate_objects,
        counts_by_kind=dict(sorted(counts.items())),
        tag_coverage_by_kind={
            kind: dict(sorted(kind_counts.items()))
            for kind, kind_counts in sorted(coverage.items())
        },
        excluded_counts=dict(sorted(excluded.items())),
    )


def _is_artwork(tags: dict[str, str]) -> bool:
    return tags.get("tourism") == "artwork" or any(
        tags.get(key, "").strip() for key in _ARTWORK_KEYS
    )


def _candidate_kind(tags: dict[str, str]) -> str | None:
    if _is_artwork(tags):
        return None
    for key, value, kind in _CANDIDATE_TAGS:
        if tags.get(key) == value:
            return kind
    if tags.get("mooring", "").lower() not in {"", "no"}:
        return "mooring"
    if tags.get("historic") in _HISTORIC_SITE_VALUES:
        return "historic_site"
    return None


def _has_tag(tags: dict[str, str], candidates: set[tuple[str, str]]) -> bool:
    return any(tags.get(key) == value for key, value in candidates)


def _is_transport(tags: dict[str, str]) -> bool:
    if _has_tag(tags, _TRANSPORT_TAGS):
        return True
    return (
        tags.get("public_transport") in {"platform", "stop_position"} and tags.get("bus") == "yes"
    )


def _is_pedestrian_access(tags: dict[str, str]) -> bool:
    if _has_tag(tags, _PEDESTRIAN_TAGS):
        return True
    entrance = tags.get("entrance")
    return entrance is not None and entrance != "no"


def _is_inactive(tags: dict[str, str]) -> bool:
    if any(
        key in _INACTIVE_KEYS and value.lower() in {"yes", "true", "1"}
        for key, value in tags.items()
    ):
        return True
    return any(key.split(":", 1)[0] in _INACTIVE_KEYS for key in tags if ":" in key)
