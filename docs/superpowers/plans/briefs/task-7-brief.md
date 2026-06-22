## Task 7: `summarize()` report (`ingest/summarize.py`) — seed of §4.3 build report

Pure function over `WaterwayFeatures` → dict. No network. This is the B deliverable you can eyeball, and the seed of the build-time validation report (design §4.3 / §7.1).

**Files:**

- Create: `/home/kurtt/pound/pound/ingest/summarize.py`
- Test: `/home/kurtt/pound/tests/ingest/test_summarize.py`

**Interfaces:**

- Consumes: `pound.ingest.ir.WaterwayFeatures`, `WaterwayKind`
- Produces: `summarize(features: WaterwayFeatures) -> dict` with keys: `source`, `fetched_at`, `bbox`, `way_count`, `ways_by_kind`, `node_count`, `nodes_by_kind`, `lock_count`, `routable_ways_missing_all_dimensions`, `tunnel_ways`, `movable_bridge_ways`.

- [ ] **Step 1: Write the failing test**

Create `/home/kurtt/pound/tests/ingest/test_summarize.py`:

```python
from pound.ingest.ir import (
    NodeKind,
    WaterwayFeatures,
    WaterwayKind,
    WaterwayNode,
    WaterwayWay,
    WayDimensions,
)
from pound.ingest.summarize import summarize


def _canal(osm_id, dims=None, tunnel=False, movable=False):
    return WaterwayWay(
        osm_id=osm_id,
        kind=WaterwayKind.CANAL,
        name="Oxford Canal",
        tags={"waterway": "canal"},
        node_ids=[],
        geometry=[(51.75, -1.26)],
        dimensions=dims or WayDimensions(),
        has_tunnel=tunnel,
        has_movable_bridge=movable,
    )


def _lock_way(osm_id):
    return WaterwayWay(
        osm_id=osm_id,
        kind=WaterwayKind.LOCK,
        name="A Lock",
        tags={"waterway": "lock"},
        node_ids=[],
        geometry=[(51.75, -1.26)],
        dimensions=WayDimensions(),
    )


def _node(osm_id, kind):
    return WaterwayNode(
        osm_id=osm_id, lat=51.75, lon=-1.26, tags={}, kind=kind
    )


def test_summarize_counts_ways_by_kind():
    feats = WaterwayFeatures(
        ways=[_canal(1), _canal(2), _lock_way(3)],
        nodes=[],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=(51.70, -1.35, 51.80, -1.20),
    )
    r = summarize(feats)
    assert r["way_count"] == 3
    assert r["ways_by_kind"] == {"canal": 2, "lock": 1}


def test_summarize_counts_nodes_by_kind():
    feats = WaterwayFeatures(
        ways=[],
        nodes=[_node(1, NodeKind.LOCK_GATE), _node(2, NodeKind.MOORING), _node(3, NodeKind.LOCK)],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=None,
    )
    r = summarize(feats)
    assert r["node_count"] == 3
    assert r["nodes_by_kind"] == {"lock_gate": 1, "mooring": 1, "lock": 1}


def test_summarize_lock_count_combines_lock_ways_and_lock_nodes():
    feats = WaterwayFeatures(
        ways=[_lock_way(1), _canal(2)],
        nodes=[_node(10, NodeKind.LOCK), _node(11, NodeKind.LOCK_GATE)],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=None,
    )
    r = summarize(feats)
    # 1 lock way + 1 lock node (lock_gate counted separately, not as a lock)
    assert r["lock_count"] == 2


def test_summarize_missing_dimensions_for_routable_only():
    feats = WaterwayFeatures(
        ways=[
            _canal(1, dims=WayDimensions(max_beam_m=2.1)),  # has a dim
            _canal(2),  # no dims
            _lock_way(3),  # lock way, no dims — should NOT count against routable
        ],
        nodes=[],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=None,
    )
    r = summarize(feats)
    assert r["routable_ways_missing_all_dimensions"] == 1


def test_summarize_tunnel_and_movable_bridge_flags():
    feats = WaterwayFeatures(
        ways=[_canal(1, tunnel=True), _canal(2, movable=True)],
        nodes=[],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=None,
    )
    r = summarize(feats)
    assert r["tunnel_ways"] == 1
    assert r["movable_bridge_ways"] == 1


def test_summarize_provenance_fields():
    feats = WaterwayFeatures(
        ways=[], nodes=[],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=(51.70, -1.35, 51.80, -1.20),
    )
    r = summarize(feats)
    assert r["source"] == "overpass"
    assert r["fetched_at"] == "2026-06-21T12:00:00+00:00"
    assert r["bbox"] == [51.70, -1.35, 51.80, -1.20]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/ingest/test_summarize.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pound.ingest.summarize'`.

- [ ] **Step 3: Write `pound/ingest/summarize.py`**

Create `/home/kurtt/pound/pound/ingest/summarize.py`:

```python
"""Build/ingest report — seed of the design §4.3 / §7.1 build report.

Pure: takes a WaterwayFeatures IR, returns a plain dict of counts and flags you
can eyeball during dev or serialize to JSON. No network, no file IO.
"""

from collections import Counter

from pound.ingest.ir import WaterwayFeatures, WaterwayKind

_ROUTABLE = {WaterwayKind.CANAL, WaterwayKind.RIVER, WaterwayKind.FAIRWAY}


def summarize(features: WaterwayFeatures) -> dict:
    ways_by_kind = Counter(w.kind.value for w in features.ways)
    nodes_by_kind = Counter(n.kind.value for n in features.nodes)

    lock_count = sum(
        1 for w in features.ways if w.kind == WaterwayKind.LOCK
    ) + sum(1 for n in features.nodes if n.kind.value == "lock")

    def _has_any_dim(w) -> bool:
        d = w.dimensions
        return any(
            v is not None
            for v in (d.max_beam_m, d.max_length_m, d.max_draft_m, d.max_height_m)
        )

    routable_missing_dims = sum(
        1 for w in features.ways if w.kind in _ROUTABLE and not _has_any_dim(w)
    )

    return {
        "source": features.source,
        "fetched_at": features.fetched_at,
        "bbox": list(features.bbox) if features.bbox else None,
        "way_count": len(features.ways),
        "ways_by_kind": dict(ways_by_kind),
        "node_count": len(features.nodes),
        "nodes_by_kind": dict(nodes_by_kind),
        "lock_count": lock_count,
        "routable_ways_missing_all_dimensions": routable_missing_dims,
        "tunnel_ways": sum(1 for w in features.ways if w.has_tunnel),
        "movable_bridge_ways": sum(1 for w in features.ways if w.has_movable_bridge),
    }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/ingest/test_summarize.py -q
```

Expected: all passed.

- [ ] **Step 5: Lint**

```bash
uv run ruff check .
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add pound/ingest/summarize.py tests/ingest/test_summarize.py
git commit -m "feat(ingest): summarize() report -> dict (seed of §4.3 build report)"
```

---

