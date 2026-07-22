"""Pure, source-neutral classification for canal-relevant OSM POIs."""

from dataclasses import dataclass
from typing import Literal

from pound.ingest.ir import PoiCategory

OPERATIONAL_KEYS = (
    "access",
    "foot",
    "wheelchair",
    "opening_hours",
    "fee",
    "operator",
    "brand",
    "drinking_water",
)

PROVISION_AMENITIES = ("pub", "cafe", "restaurant")
PROVISION_SHOPS = (
    "supermarket",
    "convenience",
    "bakery",
    "greengrocer",
    "butcher",
    "deli",
    "general",
)
PEDESTRIAN_HIGHWAYS = ("footway", "path", "pedestrian")
PEDESTRIAN_BARRIERS = ("gate", "stile", "kissing_gate", "cycle_barrier")
IGNORED_AMENITIES = ("parking", "toilets", "shower", "drinking_water")
UNKNOWN_VALUE_KEYS = ("amenity", "shop", "railway", "waterway", "barrier")
RETAINED_POI_KINDS = frozenset(
    {
        "water_point",
        "sanitary_disposal",
        "fuel",
        "marina",
        "mooring",
        *PROVISION_AMENITIES,
        *PROVISION_SHOPS,
        "rail_station",
        "rail_halt",
        "bus_stop",
        "taxi_rank",
        "entrance",
        "path_connection",
        "pedestrian_bridge",
        "steps",
        *PEDESTRIAN_BARRIERS,
    }
)

SkipReason = Literal["unknown_value", "insufficient_bus_evidence", "explicitly_unavailable"]


@dataclass(frozen=True)
class PoiClassification:
    category: PoiCategory
    kind: str
    driving_keys: tuple[str, ...]


@dataclass(frozen=True)
class PoiClassificationSkip:
    reason: SkipReason
    key: str
    value: str


class PoiClassificationResult(list[PoiClassification]):
    """Classifications with reader-consumable diagnostics for rejected tag values."""

    def __init__(
        self,
        classifications: list[PoiClassification],
        skips: list[PoiClassificationSkip],
    ) -> None:
        super().__init__(classifications)
        self.skips = tuple(skips)


def classify_poi(tags: dict[str, str]) -> list[PoiClassification]:
    """Return all allowlisted POI classifications in stable rule order."""
    classifications: list[PoiClassification] = []
    skips: list[PoiClassificationSkip] = []

    def add(category: PoiCategory, kind: str, *driving_keys: str) -> None:
        if not any(item.category == category and item.kind == kind for item in classifications):
            classifications.append(PoiClassification(category, kind, tuple(driving_keys)))

    if tags.get("waterway") == "water_point":
        add(PoiCategory.CANAL_SERVICE, "water_point", "waterway")

    sanitary_keys = _matching_keys(
        tags, (("amenity", "sanitary_dump_station"), ("waterway", "sanitary_station"))
    )
    if sanitary_keys:
        add(PoiCategory.CANAL_SERVICE, "sanitary_disposal", *sanitary_keys)

    fuel_keys = _matching_keys(tags, (("amenity", "fuel"), ("waterway", "fuel")))
    if fuel_keys:
        add(PoiCategory.CANAL_SERVICE, "fuel", *fuel_keys)
    if tags.get("leisure") == "marina":
        add(PoiCategory.CANAL_SERVICE, "marina", "leisure")
    if "mooring" in tags:
        if tags["mooring"] == "no":
            skips.append(PoiClassificationSkip("explicitly_unavailable", "mooring", "no"))
        else:
            add(PoiCategory.CANAL_SERVICE, "mooring", "mooring")

    amenity = tags.get("amenity")
    if amenity in PROVISION_AMENITIES:
        add(PoiCategory.PROVISIONS, amenity, "amenity")
    shop = tags.get("shop")
    if shop in PROVISION_SHOPS:
        add(PoiCategory.PROVISIONS, shop, "shop")

    railway = tags.get("railway")
    if railway == "station":
        add(PoiCategory.TRANSPORT, "rail_station", "railway")
    elif railway == "halt":
        add(PoiCategory.TRANSPORT, "rail_halt", "railway")

    public_transport = tags.get("public_transport")
    if tags.get("highway") == "bus_stop":
        keys = ("highway", "public_transport", "bus") if public_transport else ("highway",)
        add(PoiCategory.TRANSPORT, "bus_stop", *keys)
    elif public_transport in ("platform", "stop_position"):
        if tags.get("bus") == "yes":
            add(PoiCategory.TRANSPORT, "bus_stop", "public_transport", "bus")
        else:
            skips.append(
                PoiClassificationSkip(
                    "insufficient_bus_evidence", "public_transport", public_transport
                )
            )
    if amenity == "taxi":
        add(PoiCategory.TRANSPORT, "taxi_rank", "amenity")

    entrance = tags.get("entrance")
    if entrance and entrance != "no":
        if tags.get("access") in ("private", "no") or tags.get("foot") == "no":
            skips.append(PoiClassificationSkip("explicitly_unavailable", "entrance", entrance))
        else:
            add(PoiCategory.PEDESTRIAN_ACCESS, "entrance", "entrance")

    highway = tags.get("highway")
    if highway in PEDESTRIAN_HIGHWAYS:
        if _is_yes(tags.get("bridge")):
            add(PoiCategory.PEDESTRIAN_ACCESS, "pedestrian_bridge", "highway", "bridge")
        else:
            add(PoiCategory.PEDESTRIAN_ACCESS, "path_connection", "highway")
    elif highway == "steps":
        add(PoiCategory.PEDESTRIAN_ACCESS, "steps", "highway")

    barrier = tags.get("barrier")
    if barrier in PEDESTRIAN_BARRIERS:
        add(PoiCategory.PEDESTRIAN_ACCESS, barrier, "barrier")

    for key in UNKNOWN_VALUE_KEYS:
        value = tags.get(key)
        if value is not None and not _is_known_or_ignored(key, value):
            skips.append(PoiClassificationSkip("unknown_value", key, value))

    return PoiClassificationResult(classifications, skips)


def normalize_source_tags(
    tags: dict[str, str], classification: PoiClassification
) -> dict[str, str]:
    """Keep operational properties and only the tags that drove classification."""
    selected = set(OPERATIONAL_KEYS) | set(classification.driving_keys)
    selected.discard("toilets")
    return {key: value for key, value in tags.items() if key in selected}


def corridor_m(category: PoiCategory) -> float:
    if category in (PoiCategory.CANAL_SERVICE, PoiCategory.PEDESTRIAN_ACCESS):
        return 250.0
    return 1000.0


def _matching_keys(tags: dict[str, str], pairs: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    return tuple(key for key, value in pairs if tags.get(key) == value)


def _is_yes(value: str | None) -> bool:
    return value in ("yes", "true", "1")


def _is_known_or_ignored(key: str, value: str) -> bool:
    known_values = {
        "amenity": set(PROVISION_AMENITIES) | {"sanitary_dump_station", "fuel", "taxi"},
        "shop": set(PROVISION_SHOPS),
        "railway": {"station", "halt"},
        "waterway": {"water_point", "sanitary_station", "fuel"},
        "barrier": set(PEDESTRIAN_BARRIERS),
    }
    if key == "amenity" and value in IGNORED_AMENITIES:
        return True
    return value in known_values[key]
