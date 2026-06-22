## Task 2: Schemas — the frozen Agent Core contract

**Files:**

- Create: `/home/kurtt/pound/pound/schemas.py`
- Test: `/home/kurtt/pound/tests/test_schemas.py`

**Interfaces:**

- Consumes: `pydantic.BaseModel`
- Produces: `CanalConstraints`, `RouteResult`, `RouteLeg`, `DayPlan`, `Amenity` (Pydantic v2 models, field names frozen — the Agent Core imports these)

- [ ] **Step 1: Write the failing test**

Create `/home/kurtt/pound/tests/test_schemas.py`:

```python
from pound.schemas import (
    Amenity,
    CanalConstraints,
    DayPlan,
    RouteLeg,
    RouteResult,
)


def test_canal_constraints_defaults():
    c = CanalConstraints(start="Oxford", end="Heyford", days=1)
    assert c.start == "Oxford"
    assert c.end == "Heyford"
    assert c.days == 1
    assert c.hours_per_day == 6.0
    assert c.boat_beam_m is None
    assert c.amenity_prefs == []
    assert c.allow_derelict is False


def test_route_result_round_trip():
    leg = RouteLeg(
        from_place="Oxford",
        to_place="Heyford",
        distance_km=9.5,
        locks=2,
        est_minutes=131,
    )
    day = DayPlan(day=1, legs=[leg], end_near="Heyford", cruising_minutes=131)
    amenity = Amenity(
        kind="pub", name="The Navigation", lat=51.75, lon=-1.26, distance_m=120.0, source="osm"
    )
    result = RouteResult(
        start="Oxford",
        end="Heyford",
        is_ring=False,
        legs=[leg],
        days=[day],
        total_km=9.5,
        total_locks=2,
        total_minutes=131,
        amenities=[amenity],
        graph_source_date="2026-06-21",
    )
    dumped = result.model_dump_json()
    restored = RouteResult.model_validate_json(dumped)
    assert restored == result
    assert restored.legs[0].flagged_unknown_dims is False
    assert restored.warnings == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_schemas.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pound.schemas'`.

- [ ] **Step 3: Write `pound/schemas.py`**

Create `/home/kurtt/pound/pound/schemas.py`:

```python
"""Shared Pydantic models — the frozen contract Pound and the Agent Core both import.

Per design §6. Field names are the integration seam; do not rename without
coordinating with labyrinth-core / labyrinth-agent.
"""

from pydantic import BaseModel


class CanalConstraints(BaseModel):
    start: str
    end: str | None = None  # None => ring / round trip
    days: int
    hours_per_day: float = 6.0
    boat_length_m: float | None = None
    boat_beam_m: float | None = None
    boat_draft_m: float | None = None
    boat_height_m: float | None = None
    amenity_prefs: list[str] = []  # ["pub", "water_point", "shop", ...]
    allow_derelict: bool = False


class Amenity(BaseModel):
    kind: str  # "pub" | "water_point" | "marina" | ...
    name: str | None
    lat: float
    lon: float
    distance_m: float  # from route
    source: str  # "osm" | "crt"


class RouteLeg(BaseModel):
    from_place: str
    to_place: str
    distance_km: float
    locks: int
    est_minutes: int
    flagged_unknown_dims: bool = False  # edge(s) lacked dimension tags


class DayPlan(BaseModel):
    day: int
    legs: list[RouteLeg]
    end_near: str | None  # mooring/town the day ends at
    cruising_minutes: int


class RouteResult(BaseModel):
    start: str
    end: str | None
    is_ring: bool
    legs: list[RouteLeg]
    days: list[DayPlan]
    total_km: float
    total_locks: int
    total_minutes: int
    amenities: list[Amenity]
    warnings: list[str] = []  # e.g. "draft unknown on 3 segments"
    graph_source_date: str  # provenance from the artifact
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_schemas.py -q
```

Expected: 2 passed.

- [ ] **Step 5: Lint**

```bash
uv run ruff check .
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add pound/schemas.py tests/test_schemas.py
git commit -m "feat(schemas): freeze CanalConstraints/RouteResult/RouteLeg/DayPlan/Amenity contract"
```

---

