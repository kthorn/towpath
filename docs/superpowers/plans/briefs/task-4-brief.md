## Task 4: Ingest IR types (`ingest/ir.py`)

**Files:**

- Create: `/home/kurtt/pound/pound/ingest/ir.py`
- Test: `/home/kurtt/pound/tests/ingest/test_ir.py`

**Interfaces:**

- Consumes: `pydantic.BaseModel`, `enum.Enum`
- Produces: `WaterwayKind` (enum: canal/river/fairway/lock), `NodeKind` (enum: lock/lock_gate/movable_bridge/mooring/marina/other), `WayDimensions`, `WaterwayWay`, `WaterwayNode`, `WaterwayFeatures`. These are the IR the pure functions populate and both readers (Overpass now, pyosmium later) emit.

- [ ] **Step 1: Write the failing test**

Create `/home/kurtt/pound/tests/ingest/test_ir.py`:

```python
import pytest

from pound.ingest.ir import (
    NodeKind,
    WaterwayFeatures,
    WaterwayKind,
    WaterwayNode,
    WaterwayWay,
    WayDimensions,
)


def test_waterway_way_defaults():
    w = WaterwayWay(
        osm_id=1,
        kind=WaterwayKind.CANAL,
        name="Oxford Canal",
        tags={"waterway": "canal"},
        node_ids=[101, 102],
        geometry=[(51.75, -1.26), (51.751, -1.261)],
        dimensions=WayDimensions(),
    )
    assert w.has_tunnel is False
    assert w.has_movable_bridge is False


def test_waterway_features_round_trip():
    feats = WaterwayFeatures(
        ways=[
            WaterwayWay(
                osm_id=1,
                kind=WaterwayKind.CANAL,
                name="Oxford Canal",
                tags={"waterway": "canal"},
                node_ids=[],
                geometry=[(51.75, -1.26)],
                dimensions=WayDimensions(max_beam_m=2.1),
            )
        ],
        nodes=[
            WaterwayNode(
                osm_id=10, lat=51.75, lon=-1.26, tags={"waterway": "lock_gate"},
                kind=NodeKind.LOCK_GATE,
            )
        ],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=(51.70, -1.35, 51.80, -1.20),
    )
    dumped = feats.model_dump_json()
    restored = WaterwayFeatures.model_validate_json(dumped)
    assert restored == feats
    assert restored.ways[0].dimensions.max_beam_m == pytest.approx(2.1)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/ingest/test_ir.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pound.ingest.ir'`.

- [ ] **Step 3: Write `pound/ingest/ir.py`**

Create `/home/kurtt/pound/pound/ingest/ir.py`:

```python
"""WaterwayFeatures IR — the intermediate representation the ingest pipeline emits.

Source-agnostic: both the Overpass reader (now) and the future pyosmium bulk
reader (design step 6) populate these types via the pure functions in
`pound.ingest.filters`. Graph build (step 2b) consumes them.

Geometry is stored as a list of (lat, lon) tuples. The Overpass `out geom`
reader fills `geometry` but leaves `node_ids` empty (it does not return node
refs); the pyosmium bulk reader fills both. Connectivity (shared node refs) is
therefore a bulk-path concern, not an Overpass-reader concern — consistent with
this plan stopping before graph build.
"""

from enum import Enum

from pydantic import BaseModel


class WaterwayKind(str, Enum):
    CANAL = "canal"
    RIVER = "river"
    FAIRWAY = "fairway"
    LOCK = "lock"  # waterway=lock chamber way, or way/node with lock=yes


class NodeKind(str, Enum):
    LOCK = "lock"
    LOCK_GATE = "lock_gate"
    MOVABLE_BRIDGE = "movable_bridge"
    MOORING = "mooring"
    MARINA = "marina"  # forward-compat; amenities/marinas are design step 5, not this plan
    OTHER = "other"


class WayDimensions(BaseModel):
    """Restrictive dimensions on a way (min along a segment becomes the edge limit)."""

    max_beam_m: float | None = None
    max_length_m: float | None = None
    max_draft_m: float | None = None
    max_height_m: float | None = None


class WaterwayWay(BaseModel):
    osm_id: int
    kind: WaterwayKind
    name: str | None
    tags: dict[str, str]
    node_ids: list[int]  # empty when source is Overpass `out geom`
    geometry: list[tuple[float, float]]  # (lat, lon)
    dimensions: WayDimensions
    has_tunnel: bool = False
    has_movable_bridge: bool = False


class WaterwayNode(BaseModel):
    osm_id: int
    lat: float
    lon: float
    tags: dict[str, str]
    kind: NodeKind


class WaterwayFeatures(BaseModel):
    ways: list[WaterwayWay]
    nodes: list[WaterwayNode]
    source: str  # "overpass" | "geofabrik"
    fetched_at: str  # ISO 8601 timestamp
    bbox: tuple[float, float, float, float] | None  # (south, west, north, east)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/ingest/test_ir.py -q
```

Expected: 2 passed.

- [ ] **Step 5: Lint**

```bash
uv run ruff check .
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add pound/ingest/ir.py tests/ingest/test_ir.py
git commit -m "feat(ingest): add WaterwayFeatures IR (WaterwayWay/Node, WayDimensions, kinds)"
```

---

