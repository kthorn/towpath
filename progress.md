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
  - Commit: `07d0c4f`
  - Status: DONE
  - Notes: Thin Overpass JSON scaffolding reader added (`pound/ingest/overpass.py`); curated fixture at `tests/fixtures/oxford_overpass_sample.json` with canal/lock/derelict/disused/dimensions/tunnel/lock_gate/mooring and pub node deliberately dropped. parse() is pure; fetch_raw/fetch_oxford confined to network functions. 11 new overpass tests pass, network test skipped by default, full suite 52 passed/1 skipped; ruff clean.

## Completed

- Task 7: summarize() report -> dict
  - Commit: `be8a221`
  - Status: DONE
  - Notes: Added pure `pound/ingest/summarize.py` consuming WaterwayFeatures IR and returning a validation report dict with exact keys required by design §4.3/§7.1. 6 new tests cover counts by kind, lock_count semantics (lock ways + lock nodes, not lock_gate), routable-missing-dims, tunnel/movable flags, and provenance. Full suite 58 passed/1 skipped; ruff clean.

## Completed

- Task 8: Dev CLI (`pound-ingest oxford`) + README usage section
  - Commit: `7115547`
  - Status: DONE
  - Notes: Added `pound/ingest/cli.py` with argparse entry point, `--out` flag, and monkeypatchable tests. README updated with ingest usage section. Full suite 60 passed/1 network skipped; ruff clean. Optional live Overpass fetch attempted but failed with HTTP 406 Not Acceptable; skipped per brief instructions and noted in task report.

## Next

- Task 9+ (not yet planned)
