## Task 5: Ingest pure functions (`ingest/filters.py`) — TDD

This is the permanent core. No network, no file IO. Both readers call these.

**Files:**

- Create: `/home/kurtt/pound/pound/ingest/filters.py`
- Test: `/home/kurtt/pound/tests/ingest/test_filters.py`

**Interfaces:**

- Consumes: `pound.ingest.ir` (enums, `WayDimensions`)
- Produces:
  - `classify_way(tags: dict[str,str]) -> WaterwayKind | None`
  - `is_derelict(tags: dict[str,str]) -> bool`
  - `extract_dimensions(tags: dict[str,str]) -> WayDimensions`
  - `classify_node(tags: dict[str,str]) -> NodeKind | None`

- [ ] **Step 1: Write the failing tests**

Create `/home/kurtt/pound/tests/ingest/test_filters.py`:

```python
import pytest

from pound.ingest.filters import (
    classify_node,
    classify_way,
    extract_dimensions,
    is_derelict,
)
from pound.ingest.ir import NodeKind, WaterwayKind, WayDimensions


# --- classify_way ---

@pytest.mark.parametrize(
    "tags,expected",
    [
        ({"waterway": "canal"}, WaterwayKind.CANAL),
        ({"waterway": "river"}, WaterwayKind.RIVER),
        ({"waterway": "fairway"}, WaterwayKind.FAIRWAY),
        ({"waterway": "lock"}, WaterwayKind.LOCK),
        ({"lock": "yes"}, WaterwayKind.LOCK),
        ({"waterway": "derelict_canal"}, None),
        ({"waterway": "stream"}, None),
        ({}, None),
        ({"highway": "residential"}, None),
    ],
)
def test_classify_way(tags, expected):
    assert classify_way(tags) == expected


# --- is_derelict ---

def test_is_derelict_explicit_value():
    assert is_derelict({"waterway": "derelict_canal"}) is True


def test_is_derelict_disused_prefix():
    assert is_derelict({"waterway": "canal", "disused:waterway": "canal"}) is True


def test_is_derelict_abandoned_prefix():
    assert is_derelict({"abandoned:waterway": "canal"}) is True


def test_is_derelict_clean_canal():
    assert is_derelict({"waterway": "canal", "name": "Oxford Canal"}) is False


def test_is_derelict_empty():
    assert is_derelict({}) is False


# --- extract_dimensions ---

def test_extract_dimensions_all_aliases():
    tags = {
        "maxwidth": "2.1",
        "maxlength": "22.0",
        "maxdraught": "0.9",
        "maxheight": "1.9",
    }
    d = extract_dimensions(tags)
    assert d == WayDimensions(
        max_beam_m=2.1, max_length_m=22.0, max_draft_m=0.9, max_height_m=1.9
    )


def test_extract_dimensions_alternate_aliases():
    tags = {"width": "2.2", "maxdraft": "0.8", "maxclosedheight": "1.8", "depth": "0.7"}
    d = extract_dimensions(tags)
    assert d.max_beam_m == pytest.approx(2.2)
    assert d.max_draft_m == pytest.approx(0.8)
    assert d.max_height_m == pytest.approx(1.8)


def test_extract_dimensions_missing_returns_none():
    d = extract_dimensions({"waterway": "canal"})
    assert d == WayDimensions()


def test_extract_dimensions_bad_value_ignored():
    d = extract_dimensions({"maxwidth": "n/a"})
    assert d.max_beam_m is None


def test_extract_dimensions_first_alias_wins():
    d = extract_dimensions({"maxwidth": "2.1", "width": "9.9"})
    assert d.max_beam_m == pytest.approx(2.1)


# --- classify_node ---

@pytest.mark.parametrize(
    "tags,expected",
    [
        ({"waterway": "lock_gate"}, NodeKind.LOCK_GATE),
        ({"lock": "yes"}, NodeKind.LOCK),
        ({"waterway": "lock"}, NodeKind.LOCK),
        ({"bridge:movable": "swing"}, NodeKind.MOVABLE_BRIDGE),
        ({"bridge": "movable"}, NodeKind.MOVABLE_BRIDGE),
        ({"mooring": "yes"}, NodeKind.MOORING),
        ({"leisure": "marina"}, NodeKind.MARINA),
        ({}, None),
        ({"amenity": "pub"}, None),  # amenities are a later ingest step
    ],
)
def test_classify_node(tags, expected):
    assert classify_node(tags) == expected
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/ingest/test_filters.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pound.ingest.filters'`.

- [ ] **Step 3: Write `pound/ingest/filters.py`**

Create `/home/kurtt/pound/pound/ingest/filters.py`:

```python
"""Pure ingest functions: OSM tags -> filtered WaterwayFeature IR pieces.

Source-agnostic. No network, no file IO. Called by the Overpass reader (now)
and the future pyosmium bulk reader (design step 6). This is the permanent
core of the ingest pipeline.

Tag reference: design §3.1. We keep waterway=canal/river/fairway as routable
edges, waterway=lock (and lock=yes) as lock features, and exclude
derelict_canal / disused:* / abandoned:* by default (allow_derelict is a
later, graph-build concern — at the IR level we only *flag* derelict so the
reader can drop it; restoration routes are a future flag).
"""

from pound.ingest.ir import NodeKind, WaterwayKind, WayDimensions

_DERELICT_WATERWAY_VALUES = {"derelict_canal"}
_DERELICT_TAG_PREFIXES = ("disused:", "abandoned:")

_DIMENSION_ALIASES: dict[str, tuple[str, ...]] = {
    "max_beam_m": ("maxwidth", "width"),
    "max_length_m": ("maxlength",),
    "max_draft_m": ("maxdraft", "maxdraught", "depth"),
    "max_height_m": ("maxheight", "maxclosedheight"),
}


def classify_way(tags: dict[str, str] | None) -> WaterwayKind | None:
    """Classify a way by its waterway/lock tags. None => not a waterway we keep."""
    if not tags:
        return None
    ww = tags.get("waterway", "")
    if ww == "canal":
        return WaterwayKind.CANAL
    if ww == "river":
        return WaterwayKind.RIVER
    if ww == "fairway":
        return WaterwayKind.FAIRWAY
    if ww == "lock":
        return WaterwayKind.LOCK
    if tags.get("lock") == "yes":
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


def classify_node(tags: dict[str, str] | None) -> NodeKind | None:
    """Classify a tagged node. None => not a network node we keep in this plan."""
    if not tags:
        return None
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
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/ingest/test_filters.py -q
```

Expected: all passed (parametrized counts included).

- [ ] **Step 5: Lint**

```bash
uv run ruff check .
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add pound/ingest/filters.py tests/ingest/test_filters.py
git commit -m "feat(ingest): pure tag->IR functions (classify_way/node, is_derelict, extract_dimensions)"
```

---

