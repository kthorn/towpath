# Pound — Final Whole-Branch Review

**Reviewer:** final-review subagent (review-only, no edits)
**Date:** 2026-06-21
**Scope:** whole branch (greenfield) — 8 implementation tasks, scope B (schemas + stub + regional OSM ingest, stopping before graph build)
**Spec:** `docs/superpowers/plans/2026-06-21-pound-ingest-scaffolding.md` against `pound-engine-design.md`

## Verdict: APPROVED_WITH_FIXES

**Counts:** 0 Critical · 1 Important · 3 Minor · 2 Notes

Test gate: `uv run pytest -q` → **60 passed, 1 skipped** (network). `uv run ruff check .` → **All checks passed**. The frozen Agent Core contract is structurally correct and the request-time path is provably pure — so this does not block the parallel Agent Core build. The one Important item is an explicit global-constraint violation that is cheap to fix and should be fixed before the stub is treated as a reference.

---

## Correct (evidence-backed)

- **Schemas match design §6 field-for-field.** `pound/schemas.py` lines 12–57 reproduce `CanalConstraints`, `Amenity`, `RouteLeg`, `DayPlan`, `RouteResult` with identical field names, types, defaults, and ordering to design §6. Verified each class against the design block.
- **Request-time purity holds.** `grep -nE '^(import|from)' pound/schemas.py` → only `from pydantic import BaseModel`. `pound/plan.py` → only `from pound.schemas import (...)`. `requests` is imported in exactly one module: `pound/ingest/overpass.py:14`. No ingest import leaks into `schemas` or `plan`.
- **Stub satisfies its structural invariants.** `tests/test_plan_stub.py` asserts legs connect end-to-end, totals == sum of legs, days partition legs, start/end match constraints, ring closure when `end=None`, `graph_source_date` present — all 7 pass.
- **Tag filters match design §3.1.** `classify_way` (filters.py:26–40) keeps canal/river/fairway/lock + `lock=yes`; `is_derelict` (43–48) catches `derelict_canal` + `disused:`/`abandoned:` prefixes; `extract_dimensions` (62–75) uses the alias groups `maxwidth→width`, `maxlength`, `maxdraft→maxdraught→depth`, `maxheight→maxclosedheight` with first-parseable-wins; `classify_node` (78–89) maps lock_gate/lock/bridge:movable/mooring/marina. Parametrized tests in `test_filters.py` cover each rule including the deliberately-dropped `amenity=pub`.
- **`parse()` keep/drop behavior matches fixture intent.** `tests/ingest/test_overpass.py` asserts canal ways 1001/1002/1006 kept, lock way 1003 kept, derelict 1004 (`disused:waterway`) + 1005 (`derelict_canal`) dropped, dimensions extracted on 1002, tunnel flagged on 1006, lock_gate/lock/mooring nodes kept, pub node 2004 dropped (`test_parse_excludes_amenity_pub_node`). All pass.
- **Cross-task IR consistency.** `filters.py` imports `NodeKind, WaterwayKind, WayDimensions` from `ir`; `overpass.py` imports `WaterwayFeatures, WaterwayKind, WaterwayNode, WaterwayWay, WayDimensions` + uses `filters`; `summarize.py` imports `WaterwayFeatures, WaterwayKind`; `cli.py` imports `fetch_oxford` + `summarize`. No type drift, no signature mismatch, no dead import across the ingest chain. `cli.fetch_oxford` is monkeypatched in `test_cli.py` against the `cli` namespace (correct given `from pound.ingest.overpass import fetch_oxford`).
- **Data hygiene.** `git ls-files pound/data/` → only `.gitkeep`. `.gitignore` lines 18–19: `pound/data/*` + `!pound/data/.gitkeep`. Fixture `tests/fixtures/oxford_overpass_sample.json` is committed.
- **ODbL attribution present.** README "Data attribution" section; fixture carries `osm3s.copyright` ODbL note.
- **Network tests gated.** `tests/conftest.py` adds `--run-network` and auto-skips `network`-marked tests; `test_network.py` confirmed skipped by default.
- **No YAGNI over-build.** No premature pyosmium/parser interface introduced; the Overpass reader is a thin wrapper over `filters` as specified. `NodeKind.MARINA` is spec'd and is produced by `classify_node` (`leisure=marina`).
- **Tests are meaningful, not vacuous.** Round-trip serialization, parametrized tag rules, first-alias-wins, bad-value-ignored, derelict exclusion, amenity-drop, summarize counts/lock-combination/missing-dims-routable-only, CLI report+write+unknown-region rejection. No tautological test found.

---

## Important

### I-1: Stub `est_minutes=131` is inconsistent with the documented cost formula

**Location:** `pound/plan.py:40` (`est_minutes=131`) with `distance_km=9.5`, `locks=2` (lines 36–38); constants `CRUISE_KMH=4.8`, `LOCK_MINUTES=12` at lines 17–18.

**Evidence:** The global constraint states the stub's `est_minutes` "must be plausibly consistent with the documented formula so structural tests can later assert against it." The formula (`design §5.2`) is `distance_km / 4.8 * 60 + locks * 12`. With the stub's own inputs: `9.5 / 4.8 * 60 + 2 * 12 = 142.75 → 143`, not 131. The distance that would yield 131 is ~8.56 km, but the stub hardcodes `distance_km=9.5`. The module docstring rationalizes "a shorter leg so the totals arithmetic stays exact," which contradicts the hardcoded 9.5 km.

**Why it matters:** Design §7.2 lists "per-leg `est_minutes` matches the cost formula for `(distance, locks)`" as a required structural invariant. The plan's current tests deliberately omit that assertion, but the global constraint's stated purpose is precisely that future structural tests *can* assert against the formula. Adding that invariant later (as §7.2 requires) will fail: `143 != 131`. The constants `CRUISE_KMH`/`LOCK_MINUTES` are also defined but unused — the stub hardcodes the answer instead of computing it, which is the root of the drift.

**Fix:** Either set `est_minutes = round(9.5/4.8*60 + 2*12) = 143` (and `cruising_minutes=143`, `total_minutes` via the existing `sum-of-legs` path stays consistent), or compute `est_minutes` from the constants directly. Update the docstring. The `test_schemas.py` round-trip uses 131 independently and does not need to follow the formula (it tests serialization, not cost).

---

## Minor

### M-1: `progress.md` is committed and not gitignored

**Location:** `progress.md` (tracked across 5 commits: dd89076, b981475, 07d0c4f, 182d164, 95f5c25); absent from `.gitignore`.

**Evidence:** `git ls-files progress.md` lists it; `grep progress .gitignore` finds nothing. Repo guidelines (AGENTS.md context) state repo-local `progress.md` files should remain untracked and be covered by `.gitignore`.

**Note:** Per review instructions I am not flagging progress files as repo noise or asking for their removal — only that the current state (tracked) does not match the intended untracked/gitignored state. Add `progress.md` to `.gitignore` and `git rm --cached progress.md` if the intent is to keep it as scratch.

### M-2: `NodeKind.OTHER` is an unreachable enum member

**Location:** `pound/ingest/ir.py:24` (`OTHER = "other"`); `classify_node` (filters.py:78–89) never returns it (returns `None` for anything unclassified).

**Evidence:** No code path produces `NodeKind.OTHER`. It is listed in the plan's Task 4 interface spec, so it is spec'd rather than accidental — but it is currently dead. Either wire it in (e.g. for tagged-but-unrecognized waterway nodes) or drop it until a caller exists (YAGNI). Low impact; flag for the graph-build step where node triage may need it.

### M-3: `test_day_cruising_within_budget` first assertion is trivially true

**Location:** `tests/test_plan_stub.py:21` — `assert day.cruising_minutes <= result.legs[0].est_minutes * 100`.

**Evidence:** 131 ≤ 13100 is always true; the assertion carries no information. The second assertion on the same line (`day.cruising_minutes == sum(leg.est_minutes for leg in day.legs)`) is tight and meaningful. The loose bound is commented "generous for stub" but the `* 100` multiplier makes it vacuous. Consider tightening or dropping the loose half when the budget invariant becomes real.

---

## Notes

### N-1: `classify_node` matches `mooring`/`bridge:movable` on any value

**Location:** `pound/ingest/filters.py:84–85` (`if "mooring" in tags`, `if "bridge:movable" in tags`).

This matches any value including a hypothetical `mooring=no`. It is consistent with design §3.1's `mooring=*` / `bridge:movable=*` notation (which denotes tag presence), and the Overpass query (`node["mooring"]`, `node["bridge:movable"]`) also matches any value — so the reader and filter agree. Low risk for scaffolding; worth revisiting at graph build if `*=no` nodes appear in the wild.

### N-2: `CRUISE_KMH`/`LOCK_MINUTES` defined but unused in the stub

**Location:** `pound/plan.py:17–18`. The stub hardcodes `131` rather than computing from the constants. Acceptable for a stub that documents the future formula, but it is the contributing factor to I-1 — computing `est_minutes` from the constants would have prevented the drift. Resolving I-1 naturally uses these constants.

---

## Out-of-scope confirmation (not flagged as missing)

Graph build, connectivity validation, real cost model, routing, amenities, rings, day budgeting, bulk Geofabrik PBF, CRT data, and external oracle are all correctly absent per scope B. The pub node in the fixture is correctly dropped by `parse()`. The live Overpass HTTP 406 rate-limit is a known server-side issue, not a `fetch_raw` defect. The `NodeKind.MARINA` forward-compat member is spec'd and produced. The `StrEnum`/`datetime.UTC` modernizations versus the plan's `str, Enum`/`datetime.timezone` are equivalent under `requires-python = ">=3.12"` and all tests pass.
