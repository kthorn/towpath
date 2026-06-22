# Pound progress

## Completed

- Task 1: Scaffold the project (git, pyproject, layout, config)
  - Commit: `1ce65e8`
  - Status: DONE
  - Notes: Package imports pass, pytest passes, ruff clean, network marker skip verified.

## Completed

- Task 2: Freeze shared Pydantic contract
  - Commit: `d4ca0b3`
  - Status: DONE
  - Notes: CanalConstraints, RouteResult, RouteLeg, DayPlan, Amenity models added with round-trip test; pytest and ruff clean.

## Completed

- Task 3: Stub `plan_route()` + structural-invariant tests
  - Commit: `a42f1ef`
  - Status: DONE
  - Notes: Stub returns hardcoded Oxford->Heyford leg with structural tests; pytest 11 passed, ruff clean.

## Completed

- Task 4: Ingest IR types (`ingest/ir.py`)
  - Commit: `2017428`
  - Status: DONE
  - Notes: WaterwayKind/NodeKind enums, WayDimensions, WaterwayWay/Node/Features added; JSON round-trip test passes; pytest 13 passed, ruff clean. Used `enum.StrEnum` instead of brief's `(str, Enum)` to satisfy ruff UP042.

## Completed

- Task 5: Ingest pure functions (`ingest/filters.py`)
  - Commit: `78b9e15`
  - Status: DONE
  - Notes: classify_way, is_derelict, extract_dimensions, classify_node implemented with full parametrized tests; 28 filter tests, 41 total passed; ruff clean. Pure functions, no network/file IO, only stdlib + pound.ingest.ir imports.

## Completed

- Task 6: Overpass reader + curated fixture
  - Commit: `PENDING`
  - Status: DONE
  - Notes: Thin Overpass JSON scaffolding reader added (`pound/ingest/overpass.py`); curated fixture at `tests/fixtures/oxford_overpass_sample.json` with canal/lock/derelict/disused/dimensions/tunnel/lock_gate/mooring and pub node deliberately dropped. parse() is pure; fetch_raw/fetch_oxford confined to network functions. 11 new overpass tests pass, network test skipped by default, full suite 52 passed/1 skipped; ruff clean.

## Next

- Task 7: (awaiting brief)
