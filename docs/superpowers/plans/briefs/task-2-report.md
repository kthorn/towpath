# Task 2 Report: Schemas — Frozen Agent Core Contract

## Summary

Implemented the shared Pydantic v2 contract (`CanalConstraints`, `RouteResult`, `RouteLeg`, `DayPlan`, `Amenity`) in `pound/schemas.py` with JSON round-trip coverage in `tests/test_schemas.py`.

## Changed Files

- `pound/schemas.py` (new) — frozen Pydantic models per brief
- `tests/test_schemas.py` (new) — default-value + JSON round-trip tests
- `progress.md` — updated tracking

## Commands Run

```text
$ cd /home/kurtt/pound && uv run pytest tests/test_schemas.py -q
..                                                                       [100%]
2 passed in 0.16s
exit code: 0
```

```text
$ cd /home/kurtt/pound && uv run pytest -q
....                                                                     [100%]
4 passed in 0.07s
exit code: 0
```

```text
$ cd /home/kurtt/pound && uv run ruff check .
All checks passed!
exit code: 0
```

```text
$ cd /home/kurtt/pound && git commit -m "feat(schemas): freeze CanalConstraints/RouteResult/RouteLeg/DayPlan/Amenity contract"
[main d4ca0b3] feat(schemas): freeze CanalConstraints/RouteResult/RouteLeg/DayPlan/Amenity contract
 2 files changed, 108 insertions(+)
 create mode 100644 pound/schemas.py
 create mode 100644 tests/test_schemas.py
exit code: 0
```

## Test Output Summary

- `test_canal_constraints_defaults`: validates required fields and defaults on `CanalConstraints`
- `test_route_result_round_trip`: constructs full `RouteResult` graph, serializes to JSON, validates back, and checks defaults (`flagged_unknown_dims`, `warnings`)
- Full suite remains green: 4 passed

## Surprises

- `pyproject.toml` had incidental formatting-only changes (whitespace / array style) from an earlier tool invocation; these were left unstaged because they were outside the brief's Files block.

## Residual Risks

- The contract field names are now frozen; any future change to `pound/schemas.py` must be coordinated with labyrinth-core / labyrinth-agent.
- Pydantic defaults on mutable fields (`amenity_prefs: list[str] = []`, `warnings: list[str] = []`) follow the brief exactly. In standard Pydantic v2 this is acceptable because new list instances are created per model instance, but downstream consumers should treat them as owned per-instance.
- No runtime validation was added for `kind`/`source` enum-like strings; the brief specifies plain `str`, so invalid values will round-trip silently until the Agent Core enforces them.

## Decisions Needing Approval

None.

## Commit

- `d4ca0b3` — `feat(schemas): freeze CanalConstraints/RouteResult/RouteLeg/DayPlan/Amenity contract`
