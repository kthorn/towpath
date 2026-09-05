"""Pure ingest functions: OSM tags -> filtered WaterwayFeature IR pieces.

Source-agnostic. No network, no file IO. Called by the Overpass reader (now)
and the future pyosmium bulk reader (design step 6). This is the permanent
core of the ingest pipeline.

Tag reference: design §3.1. We keep waterway=canal/river/fairway as routable
edges, waterway=lock (and lock=yes) as lock features, and exclude
derelict_canal / disused:* / abandoned:* unconditionally. At the IR level we
only *flag* derelict so the reader can drop it.
"""

from pound.ingest.ir import (
    AccessCaveat,
    NodeKind,
    WaterwayFeatures,
    WaterwayKind,
    WayDimensions,
)

_DERELICT_WATERWAY_VALUES = {"derelict_canal"}
_DERELICT_TAG_PREFIXES = ("disused:", "abandoned:")

_DIMENSION_ALIASES: dict[str, tuple[str, ...]] = {
    "max_beam_m": ("maxwidth", "width"),
    "max_length_m": ("maxlength",),
    "max_draft_m": ("maxdraft", "maxdraught", "depth"),
    "max_height_m": ("maxheight", "maxclosedheight"),
}


def classify_way(tags: dict[str, str] | None) -> WaterwayKind | None:
    """Classify a way by its waterway/lock tags. None => not a waterway we keep.

    lock=yes is checked first: UK staircases (Bingley, Foxton) tag each chamber
    as waterway=canal + lock=yes (one way per chamber), so without this ordering
    the lock signal is shadowed and a whole staircase would count as 0 locks.
    """
    if not tags:
        return None
    if tags.get("lock") == "yes":
        return WaterwayKind.LOCK
    ww = tags.get("waterway", "")
    if ww == "canal":
        return WaterwayKind.CANAL
    if ww == "river":
        return WaterwayKind.RIVER
    if ww == "fairway":
        return WaterwayKind.FAIRWAY
    if ww == "lock":
        return WaterwayKind.LOCK
    return None


def is_derelict(tags: dict[str, str] | None) -> bool:
    """True if the tags mark the feature as derelict/disused/abandoned."""
    if not tags:
        return False
    if tags.get("waterway") in _DERELICT_WATERWAY_VALUES:
        return True
    return any(key.startswith(_DERELICT_TAG_PREFIXES) for key in tags)


def _parse_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_dimensions(tags: dict[str, str] | None) -> WayDimensions:
    """Extract restrictive max-dimension tags, trying aliases in order.

    First present alias with a parseable float wins; missing/unparseable => None.
    """
    tags = tags or {}
    values: dict[str, float] = {}
    for field, aliases in _DIMENSION_ALIASES.items():
        for alias in aliases:
            if alias in tags:
                parsed = _parse_float(tags[alias])
                if parsed is not None:
                    values[field] = parsed
                    break
    return WayDimensions(**values)


_NON_PUBLIC_BOAT = {"no", "unsuitable", "canoe", "private", "permit"}
_NON_PUBLIC_ACCESS = {"no", "private", "permit"}
_ORDINARY_ACCESS_VALUES = {"yes", "permissive", "designated"}


def is_navigable(tags: dict[str, str] | None) -> bool:
    """True unless exact literal boat or access tags exclude a public route.

    Matching is case-sensitive. Missing tags and non-standard explicit values
    remain eligible; later routing reports the retained values as caveats.
    """
    tags = tags or {}
    return tags.get("boat") not in _NON_PUBLIC_BOAT and tags.get("access") not in _NON_PUBLIC_ACCESS


def extract_access_caveats(
    osm_way_id: int, tags: dict[str, str] | None
) -> tuple[AccessCaveat, ...]:
    """Normalize retained access caveats without interpreting legal permission."""
    if not is_navigable(tags):
        return ()
    values = []
    for tag in ("boat", "access"):
        value = (tags or {}).get(tag)
        if not value or value in _ORDINARY_ACCESS_VALUES:
            continue
        kind = "discouraged" if value == "discouraged" else "unknown"
        values.append(AccessCaveat(osm_way_id, tag, value, kind))
    return tuple(sorted(set(values)))


def filter_navigable_ways(features: WaterwayFeatures) -> WaterwayFeatures:
    """Return a new WaterwayFeatures with non-public-access ways (`is_navigable`
    is False) removed from `features.ways`. `nodes` are untouched (infra-node
    pruning is a separate concern handled by `prune_non_navigable_infra`).

    Pure: returns a new WaterwayFeatures; does not mutate the input. Uses
    `model_copy(update=...)` to rebuild the `ways` list — the returned model is
    a shallow copy, but its `ways` list is fresh (the individual `WaterwayWay`
    elements are shared references, which is safe because nothing in `pound/`
    mutates `WaterwayWay` instances post-construction; if a future caller would
    mutate one, switch to a deep copy). `nodes` is the same list reference as
    the input (deliberately — "untouched").

    Public-access-only: does NOT fold `is_derelict`. The readers drop derelict ways
    inline in their way loops; that stays. Folding here would break
    `test_parse_excludes_derelict` and leak `disused:waterway` ways.
    """
    kept = [w for w in features.ways if is_navigable(w.tags)]
    return features.model_copy(update={"ways": kept})


def classify_node(tags: dict[str, str] | None) -> NodeKind | None:
    """Classify a tagged node. None => not a network node we keep in this plan."""
    if not tags:
        return None
    if tags.get("waterway") == "turning_point":
        return NodeKind.TURNING_POINT
    if tags.get("waterway") == "lock_gate":
        return NodeKind.LOCK_GATE
    if tags.get("waterway") == "lock" or tags.get("lock") == "yes":
        return NodeKind.LOCK
    if "bridge:movable" in tags or tags.get("bridge") == "movable":
        return NodeKind.MOVABLE_BRIDGE
    if "mooring" in tags:
        return NodeKind.MOORING
    if tags.get("leisure") == "marina":
        return NodeKind.MARINA
    if "place" in tags:
        return NodeKind.PLACE
    return None
