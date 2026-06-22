## Task 6: Curated Overpass fixture + Overpass reader (`ingest/overpass.py`)

The reader is explicitly scaffolding — thin wrapper around `filters`. It builds the Overpass QL query, fetches JSON via `requests`, and calls the pure functions to build `WaterwayFeatures`. Replaced by a pyosmium reader in design step 6.

**Files:**

- Create: `/home/kurtt/pound/tests/fixtures/oxford_overpass_sample.json`
- Create: `/home/kurtt/pound/pound/ingest/overpass.py`
- Test: `/home/kurtt/pound/tests/ingest/test_overpass.py`
- Test: `/home/kurtt/pound/tests/ingest/test_network.py`

**Interfaces:**

- Consumes: `pound.ingest.ir`, `pound.ingest.filters`, `requests`
- Produces:
  - `OXFORD_BBOX: tuple[float,float,float,float]`
  - `build_query(bbox) -> str`
  - `fetch_raw(bbox, url, timeout) -> dict` (live network)
  - `parse(elements, bbox, source) -> WaterwayFeatures` (pure)
  - `fetch_oxford() -> WaterwayFeatures` (live network, convenience)

- [ ] **Step 1: Write the curated Overpass fixture**

Create `/home/kurtt/pound/tests/fixtures/oxford_overpass_sample.json`:

```json
{
  "version": 0.6,
  "generator": "Overpass API (test fixture, hand-curated)",
  "osm3s": {
    "timestamp_osm_base": "2026-06-21T12:00:00Z",
    "copyright": "The data included in this document is from www.openstreetmap.org. The data is made available for users under the Open Database License (ODbL)."
  },
  "elements": [
    {
      "type": "way", "id": 1001,
      "tags": {"waterway": "canal", "name": "Oxford Canal"},
      "geometry": [
        {"lat": 51.7500, "lon": -1.2600},
        {"lat": 51.7510, "lon": -1.2610},
        {"lat": 51.7520, "lon": -1.2620}
      ]
    },
    {
      "type": "way", "id": 1002,
      "tags": {"waterway": "canal", "name": "Oxford Canal", "maxwidth": "2.1", "maxdraught": "0.9"},
      "geometry": [
        {"lat": 51.7520, "lon": -1.2620},
        {"lat": 51.7530, "lon": -1.2630}
      ]
    },
    {
      "type": "way", "id": 1003,
      "tags": {"waterway": "lock", "name": "Hayfield Lock"},
      "geometry": [
        {"lat": 51.7530, "lon": -1.2630},
        {"lat": 51.7540, "lon": -1.2640}
      ]
    },
    {
      "type": "way", "id": 1004,
      "tags": {"waterway": "canal", "name": "Old Arm (disused)", "disused:waterway": "canal"},
      "geometry": [
        {"lat": 51.7600, "lon": -1.2700},
        {"lat": 51.7610, "lon": -1.2710}
      ]
    },
    {
      "type": "way", "id": 1005,
      "tags": {"waterway": "derelict_canal", "name": "Abandoned Branch"},
      "geometry": [
        {"lat": 51.7700, "lon": -1.2800},
        {"lat": 51.7710, "lon": -1.2810}
      ]
    },
    {
      "type": "way", "id": 1006,
      "tags": {"waterway": "canal", "name": "Duke's Cut", "tunnel": "yes"},
      "geometry": [
        {"lat": 51.7400, "lon": -1.2500},
        {"lat": 51.7410, "lon": -1.2510}
      ]
    },
    {
      "type": "node", "id": 2001, "lat": 51.7535, "lon": -1.2635,
      "tags": {"waterway": "lock_gate"}
    },
    {
      "type": "node", "id": 2002, "lat": 51.7540, "lon": -1.2640,
      "tags": {"lock": "yes"}
    },
    {
      "type": "node", "id": 2003, "lat": 51.7450, "lon": -1.2550,
      "tags": {"mooring": "yes"}
    },
    {
      "type": "node", "id": 2004, "lat": 51.7480, "lon": -1.2580,
      "tags": {"amenity": "pub", "name": "The Navigation"}
    }
  ]
}
```

Note: element 2004 (a pub) is included deliberately — it must be **dropped** by `parse()` since amenity POIs are out of scope for this plan (design step 5). The test asserts it is excluded.

- [ ] **Step 2: Write the failing test for `parse()` over the fixture**

Create `/home/kurtt/pound/tests/ingest/test_overpass.py`:

```python
import json
from pathlib import Path

import pytest

from pound.ingest.ir import NodeKind, WaterwayKind
from pound.ingest.overpass import OXFORD_BBOX, build_query, parse

FIXTURE = Path(__file__).parent.parent / "fixtures" / "oxford_overpass_sample.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_build_query_contains_bbox_and_filters():
    q = build_query((51.70, -1.35, 51.80, -1.20))
    assert "[out:json]" in q
    assert "(51.7,-1.35,51.8,-1.2)" in q
    assert "waterway" in q
    assert "lock_gate" in q
    assert "out geom;" in q


def test_parse_keeps_canal_ways():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    canal_ids = {w.osm_id for w in feats.ways if w.kind == WaterwayKind.CANAL}
    assert 1001 in canal_ids
    assert 1002 in canal_ids
    assert 1006 in canal_ids


def test_parse_keeps_lock_way():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    lock_ways = [w for w in feats.ways if w.kind == WaterwayKind.LOCK]
    assert any(w.osm_id == 1003 for w in lock_ways)


def test_parse_excludes_derelict():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    ids = {w.osm_id for w in feats.ways}
    assert 1004 not in ids  # disused:waterway
    assert 1005 not in ids  # waterway=derelict_canal


def test_parse_extracts_dimensions():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    w = next(w for w in feats.ways if w.osm_id == 1002)
    assert w.dimensions.max_beam_m == pytest.approx(2.1)
    assert w.dimensions.max_draft_m == pytest.approx(0.9)
    assert w.dimensions.max_height_m is None


def test_parse_flags_tunnel():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    w = next(w for w in feats.ways if w.osm_id == 1006)
    assert w.has_tunnel is True


def test_parse_keeps_lock_gate_and_lock_nodes():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    kinds = {n.kind for n in feats.nodes}
    assert NodeKind.LOCK_GATE in kinds
    assert NodeKind.LOCK in kinds


def test_parse_keeps_mooring_node():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    assert any(n.kind == NodeKind.MOORING for n in feats.nodes)


def test_parse_excludes_amenity_pub_node():
    """Amenity POIs (pub/shop/etc.) are a later ingest step — parse must drop them."""
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    assert not any("amenity" in n.tags and n.tags["amenity"] == "pub" for n in feats.nodes)


def test_parse_sets_source_and_bbox():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX, source="overpass")
    assert feats.source == "overpass"
    assert feats.bbox == OXFORD_BBOX
    assert feats.fetched_at  # non-empty ISO timestamp


def test_parse_geometry_carried_through():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    w = next(w for w in feats.ways if w.osm_id == 1001)
    assert len(w.geometry) == 3
    assert w.geometry[0] == (pytest.approx(51.75), pytest.approx(-1.26))
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/ingest/test_overpass.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pound.ingest.overpass'`.

- [ ] **Step 4: Write `pound/ingest/overpass.py`**

Create `/home/kurtt/pound/pound/ingest/overpass.py`:

```python
"""Overpass JSON reader — SCAFFOLDING.

Thin wrapper that builds an Overpass QL query, fetches JSON via `requests`, and
calls the pure functions in `pound.ingest.filters` to build a `WaterwayFeatures`
IR. Replaced by a pyosmium/osmium bulk reader over the Geofabrik GB PBF in
design step 6; the pure functions and IR survive that swap.

Network use is confined to `fetch_raw`/`fetch_oxford`. `parse()` is pure and
unit-tested against a committed fixture.
"""

from datetime import datetime, timezone

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
) -> WaterwayFeatures:
    """Pure: turn Overpass `elements` into a WaterwayFeatures IR via `filters`."""
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
        fetched_at=datetime.now(timezone.utc).isoformat(),
        bbox=bbox,
    )


def fetch_oxford() -> WaterwayFeatures:
    """Live network: fetch the Oxford Canal extract and parse it."""
    raw = fetch_raw(OXFORD_BBOX)
    return parse(raw["elements"], OXFORD_BBOX)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/ingest/test_overpass.py -q
```

Expected: all passed.

- [ ] **Step 6: Write the network test (skipped by default)**

Create `/home/kurtt/pound/tests/ingest/test_network.py`:

```python
import pytest

from pound.ingest.overpass import OXFORD_BBOX, fetch_oxford


@pytest.mark.network
def test_live_overpass_oxford_returns_features():
    feats = fetch_oxford()
    assert feats.source == "overpass"
    assert feats.bbox == OXFORD_BBOX
    # a real Oxford extract should contain at least some canal ways
    assert len(feats.ways) > 0
    assert any(w.kind.value == "canal" for w in feats.ways)
```

- [ ] **Step 7: Run the full suite — confirm network test is skipped**

```bash
uv run pytest -q
```

Expected: all non-network tests pass; `test_network.py` shows as skipped (1 skipped).

- [ ] **Step 8: Lint**

```bash
uv run ruff check .
```

Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add tests/fixtures/oxford_overpass_sample.json pound/ingest/overpass.py tests/ingest/test_overpass.py tests/ingest/test_network.py
git commit -m "feat(ingest): Overpass reader + curated fixture; network test gated behind --run-network"
```

---

