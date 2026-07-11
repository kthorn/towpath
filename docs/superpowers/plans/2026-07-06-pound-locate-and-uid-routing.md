# Pound — `pound-locate` CLI + UID routing in `pound-plan` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:test-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone `pound-locate` CLI that resolves a lat/lon pair to the nearest canal-network node uid + distance, and extend `pound-plan` so `start`/`end` accept uids as well as place names. This lands the `# future: resolve_coord` seam PR2 left in `route/resolve.py`.

**Branch:** `pound-locate-and-uid-routing`, stacked off `pound-scope-d-pr2-resolve-cli` (PR #5). New PR targets `pound-scope-d-pr2-resolve-cli` so PR #5 can merge independently; retarget to `main` once #5 lands.

**Architecture:**

- `resolve_coord(lat, lon, graph) -> tuple[int, float]` in `pound/route/resolve.py` — nearest graph node uid + haversine distance in metres. **No tolerance gate** (always returns nearest; caller decides acceptability). This supersedes PR2's `# future: resolve_coord` seam (old hint said `-> int`; distance is inherent to "nearest" so the primitive returns both).
- `pound-locate` CLI (`pound/route/locate_cli.py`) — `pound-locate --lat X --lon Y [--artifact PATH] [--max-distance-m N]`. Calls `resolve_coord`, prints `uid  <name?>  <distance_m>`. Exit 0 on nearest found; exit 1 if `--max-distance-m` exceeded. No network, no LLM.
- `pound-plan` extended (modify `pound/route/cli.py`) — each of `start`/`end` is auto-detected: bare all-digits token → `int` uid; else → name via `resolve_place`. When a token is a uid, the CLI builds `ResolvedConstraints(start_uid=…, end_uid=…)` directly and calls `plan_route`; when both are names, it uses `plan_route_from_constraints` as today. Mix allowed (one uid, one name).

**Tech Stack:** Python 3.12+, pydantic v2, NetworkX, `argparse` — all present. **No new dependencies.**

## Open questions (resolved)

- **OQ-1 — auto-detect vs explicit flags for uids in `pound-plan`** → auto-detect by shape (all-digits → uid; else → name). "Take UIDs as well as names" reads as interchangeable. Edge case: a place literally named `"42"` mis-resolves as a uid — vanishingly rare (gazetteer keys are "Oxford"/"Banbury"/etc.), noted in the CLI docstring. Override: if this ever bites, add `--start-uid`/`--end-uid` flags; not now (YAGNI).
- **OQ-2 — `resolve_coord` tolerance** → **no tolerance gate**. Always returns the nearest node + distance. A future map-click UI that needs "fail if too far" compares the distance itself. `pound-locate` offers optional `--max-distance-m` for that scripting need.
- **OQ-3 — `pound-locate` output format** → plain space-separated `uid  name?  distance_m` (one line, script-friendly). `name?` is the matched node's `name` attr if present, else `-`. No `--json` (the routing CLI is also plain; consistency).
- **OQ-4 — `pound-plan` mixed uid/name path** → CLI-side helper `_resolve_start_end(start_tok, end_tok, graph) -> ResolvedConstraints`. For each token: all-digits → `int(tok)` (uid); else → `resolve_place(token, graph)`. Builds `ResolvedConstraints` directly. The bridge `plan_route_from_constraints` is unchanged (still the names-only path). This keeps the "token is name-or-uid" logic in the CLI, not the contract.

## Global Constraints

- Python 3.12+; `uv` for env/dep. No new dependencies.
- Request-time path stays pure-Python, no network, no LLM. `resolve_coord` is offline (haversine over node lat/lon attrs).
- CLI is a **test harness** (design §6): plain human-readable stdout, no `--json`, no fancy formatting.
- Default artifact path: `pound/artifacts/england.pkl`. Tests build a fixture-scale artifact into `tmp_path`.
- TDD: failing test → implement → green → commit, per logical change.
- Per AGENTS.md: `mktemp` for temp files (N/A — pytest `tmp_path`); conventional commit messages; frequent small commits.
- Stage only touched files (working tree has unrelated untracked dirs).

## File Structure

```
pound/
├── pyproject.toml                      # MODIFY: add `pound-locate = "pound.route.locate_cli:main"`
├── README.md                           # MODIFY: document `pound-locate` + uid routing
├── pound/
│   ├── route/
│   │   ├── resolve.py                  # MODIFY: add resolve_coord (supersedes # future seam)
│   │   └── cli.py                      # MODIFY: auto-detect uid-vs-name for start/end; add _resolve_start_end
│   │   └── locate_cli.py               # NEW: pound-locate CLI
│   └── (everything else)               # NO CHANGE
└── tests/
    ├── route/
    │   ├── test_resolve.py             # MODIFY: add resolve_coord tests
    │   ├── test_cli.py                 # MODIFY: add uid-start/end tests
    │   └── test_locate_cli.py          # NEW: pound-locate tests
    └── (everything else)               # NO CHANGE
```

---

### Task 1: `resolve_coord(lat, lon, graph) -> tuple[int, float]` + tests

**Files:**

- Modify: `pound/route/resolve.py`
- Modify: `tests/route/test_resolve.py`

**Interfaces:**

- Consumes: `pound.graph.build._haversine_m` (already imported), graph nodes' `lat`/`lon` attrs.
- Produces: `resolve_coord(lat: float, lon: float, graph: nx.Graph) -> tuple[int, float]` — returns `(nearest_uid, distance_m)`. No tolerance gate; always returns nearest. Raises `ValueError("no graph nodes to resolve against")` if the graph is empty (defensive; production graphs always have nodes).
- Supersedes the `# future: resolve_coord` docstring seam — update the module docstring to say `resolve_coord` is now shipped.

- [ ] **Step 1: Write failing tests**

Append to `tests/route/test_resolve.py`:

```python
from pound.route.resolve import resolve_coord


def test_resolve_coord_returns_nearest_uid_and_distance():
    g = _graph_with_gazetteer(
        {}, [(0, 51.75, -1.26), (1, 52.06, -1.34)],
    )
    uid, dist = resolve_coord(51.7501, -1.2601, g)
    assert uid == 0
    assert dist == pytest.approx(13, abs=5)  # ~13 m from node 0


def test_resolve_coord_picks_closer_of_two_nodes():
    g = _graph_with_gazetteer(
        {}, [(0, 51.75, -1.26), (1, 52.06, -1.34)],
    )
    uid, dist = resolve_coord(52.0599, -1.3399, g)
    assert uid == 1
    assert dist < 50


def test_resolve_coord_exact_node_returns_zero_distance():
    g = _graph_with_gazetteer({}, [(0, 51.75, -1.26)])
    uid, dist = resolve_coord(51.75, -1.26, g)
    assert uid == 0
    assert dist == 0


def test_resolve_coord_empty_graph_raises():
    g = nx.Graph()
    with pytest.raises(ValueError, match="no graph nodes"):
        resolve_coord(51.75, -1.26, g)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/route/test_resolve.py -v`
Expected: FAIL — `resolve_coord` does not exist.

- [ ] **Step 3: Implement `resolve_coord`**

Append to `pound/route/resolve.py` (and update the module docstring to drop the `# future: resolve_coord` "deferred" framing — it now ships):

```python
def resolve_coord(lat: float, lon: float, graph: nx.Graph) -> tuple[int, float]:
    """Resolve a coordinate to the nearest graph node uid + distance (offline only).

    Geography-first entry (supersedes PR2's `# future: resolve_coord` seam). No
    tolerance gate: always returns the nearest node and its haversine distance in
    metres; the caller decides whether the distance is acceptable. A future
    map-click UI compares the distance to its own tolerance; `pound-locate`
    offers `--max-distance-m` for that scripting need.

    Raises ValueError for an empty graph (production graphs always have nodes).
    """
    best, best_d = None, math.inf
    for uid, nd in graph.nodes(data=True):
        d = _haversine_m((lat, lon), (nd["lat"], nd["lon"]))
        if d < best_d:
            best, best_d = uid, d
    if best is None:
        raise ValueError("no graph nodes to resolve against")
    return best, best_d
```

Update the module docstring `# future: resolve_coord` lines to read that `resolve_coord` now ships (keep the `# future: GeocodeResolver` seam unchanged).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/route/test_resolve.py -v && uv run ruff check pound/route/resolve.py tests/route/test_resolve.py`
Expected: PASS — 4 new + existing tests green; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add pound/route/resolve.py tests/route/test_resolve.py
git commit -m "feat(route): resolve_coord (lat/lon -> nearest uid + distance)"
```

---

### Task 2: `pound-locate` CLI + console script + tests

**Files:**

- Create: `pound/route/locate_cli.py`
- Modify: `pyproject.toml` (add console script)
- Test: `tests/route/test_locate_cli.py`

**Interfaces:**

- Consumes: `resolve_coord` (Task 1), `load_artifact`. Default artifact `pound/artifacts/england.pkl`.
- Produces: `[project.scripts] pound-locate = "pound.route.locate_cli:main"` and `main(argv) -> int` that:
  - Parses `pound-locate --lat X --lon Y [--artifact PATH] [--max-distance-m N]`.
  - `load_artifact(artifact_path)` → graph.
  - `resolve_coord(lat, lon, graph)` → `(uid, distance_m)`.
  - Prints `<uid>  <name-or-dash>  <distance_m>` (space-separated, one line). `name` from `graph.nodes[uid].get("name")` or `-`.
  - If `--max-distance-m` set and `distance_m > max`, prints a message to stderr and returns 1.
  - Returns 0 on success.

- [ ] **Step 1: Write failing tests**

Create `tests/route/test_locate_cli.py`:

```python
import json
from pathlib import Path

from pound.graph.artifact import save_artifact
from pound.graph.build import build_graph
from pound.graph.gazetteer import attach_node_names, build_gazetteer
from pound.graph.locks import attach_locks
from pound.ingest.overpass import parse
from pound.route import locate_cli
from tests.fixtures import oxford_fixture_path


def _build_oxford_artifact(out: Path) -> Path:
    raw = json.loads(Path(oxford_fixture_path()).read_text())
    feats = parse(raw["elements"], None, osm_timestamp=raw["osm3s"]["timestamp_osm_base"])
    g, _ = attach_locks(build_graph(feats), feats)
    attach_node_names(g, feats)
    g.graph["gazetteer"] = build_gazetteer(feats)
    g.graph["fetched_at"] = feats.fetched_at
    save_artifact(g, out, {"source": feats.source, "fetched_at": feats.fetched_at, "built_at": "t", "version": "1"})
    return out


def test_pound_locate_prints_nearest_uid_and_distance(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    # Oxford fixture's Oxford node ~ (51.75, -1.26); click very near it
    rc = locate_cli.main(["--lat", "51.7501", "--lon", "-1.2601", "--artifact", str(art)])
    assert rc == 0
    out = capsys.readouterr().out.strip().split()
    assert out[0].isdigit()  # uid is an int
    assert float(out[-1]) < 50  # distance under 50 m


def test_pound_locate_includes_node_name_when_present(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = locate_cli.main(["--lat", "51.7501", "--lon", "-1.2601", "--artifact", str(art)])
    assert rc == 0
    out = capsys.readouterr().out.strip().split()
    # <uid>  <name-or-dash>  <distance>; name is the matched node's name or "-"
    assert len(out) == 3


def test_pound_locate_max_distance_exceeds_exits_nonzero(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = locate_cli.main(["--lat", "51.75", "--lon", "-1.26",
                          "--max-distance-m", "0.001", "--artifact", str(art)])
    assert rc != 0
    assert "exceeds" in capsys.readouterr().err.lower() or "farther" in capsys.readouterr().err.lower()


def test_pound_locate_missing_args_exits_nonzero(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    with __import__("pytest").raises(SystemExit):
        locate_cli.main(["--lon", "-1.26", "--artifact", str(art)])  # missing --lat
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/route/test_locate_cli.py -v`
Expected: FAIL — `pound.route.locate_cli` does not exist.

- [ ] **Step 3: Register the console script**

In `pyproject.toml`, extend `[project.scripts]`:

```toml
[project.scripts]
pound-ingest = "pound.ingest.cli:main"
pound-plan = "pound.route.cli:main"
pound-locate = "pound.route.locate_cli:main"
```

Re-sync: `uv sync --extra dev`.

- [ ] **Step 4: Implement the CLI**

Create `pound/route/locate_cli.py`:

```python
"""Minimal pound-locate CLI — resolve a coordinate to the nearest canal node.

Type a lat/lon pair, get the nearest canal-network node uid + distance. Plain
human-readable stdout; no --json. A future map-click UI uses the resolve_coord
function this CLI wraps.

Usage:
    pound-locate --lat X --lon Y [--artifact PATH] [--max-distance-m N]
"""

import argparse
import sys
from pathlib import Path

from pound.graph.artifact import load_artifact
from pound.route.resolve import resolve_coord

_DEFAULT_ARTIFACT = Path("pound/artifacts/england.pkl")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pound-locate")
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--artifact", default=str(_DEFAULT_ARTIFACT))
    p.add_argument("--max-distance-m", type=float, default=None)
    args = p.parse_args(argv)

    artifact = Path(args.artifact)
    if not artifact.exists():
        print(f"artifact not found: {artifact}", file=sys.stderr)
        return 2

    graph, _ = load_artifact(artifact)
    uid, dist_m = resolve_coord(args.lat, args.lon, graph)
    name = graph.nodes[uid].get("name") or "-"

    if args.max_distance_m is not None and dist_m > args.max_distance_m:
        print(f"nearest canal node is {dist_m:.1f} m away — exceeds --max-distance-m {args.max_distance_m}", file=sys.stderr)
        return 1

    print(f"{uid}  {name}  {dist_m:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 5: Run the locate tests + full suite + ruff**

Run: `uv run pytest tests/route/test_locate_cli.py -v`
Run: `uv run pytest -q`
Run: `uv run ruff check . && uv run ruff format --check .`
Expected: PASS across the board.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml pound/route/locate_cli.py tests/route/test_locate_cli.py
git commit -m "feat(route): minimal pound-locate CLI (lat/lon -> nearest uid + distance)"
```

---

### Task 3: `pound-plan` accepts uids as well as names for start/end

**Files:**

- Modify: `pound/route/cli.py`
- Modify: `tests/route/test_cli.py`

**Interfaces:**

- Consumes: `ResolvedConstraints`, `plan_route`, `plan_route_from_constraints` (PR2), `resolve_place` (PR2).
- Produces: in `cli.py`, a `_resolve_start_end(start_tok, end_tok, graph, **boat_kwargs) -> tuple[ResolvedConstraints | CanalConstraints, bool]` helper. Per token: all-digits → `int` (uid); else → name. Returns a `ResolvedConstraints` (if any token was a uid) plus a flag, or a `CanalConstraints` (if both names) plus a flag. `main` then calls `plan_route(rc, graph=graph)` for the uid path or `plan_route_from_constraints(c, graph=graph)` for the names path.
- Auto-detect: `tok.isdigit()` → uid. Edge case (place named "42") noted in docstring.

- [ ] **Step 1: Write failing tests**

Append to `tests/route/test_cli.py`:

```python
def test_pound_plan_accepts_uid_start_and_end(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    # Resolve Oxford + Hayfield to uids first via the locate path, then route by uid.
    from pound.route.resolve import resolve_place
    import json as _json
    from pound.graph.artifact import load_artifact
    graph, _ = load_artifact(Path(art))
    o_uid = resolve_place("Oxford", graph)
    h_uid = resolve_place("Hayfield", graph)
    rc = cli.main([str(o_uid), str(h_uid), "--days", "1", "--artifact", str(art)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Oxford" in out
    assert "Hayfield" in out


def test_pound_plan_mixes_uid_start_and_name_end(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    from pound.route.resolve import resolve_place
    from pathlib import Path as _P
    from pound.graph.artifact import load_artifact
    graph, _ = load_artifact(_P(art))
    o_uid = resolve_place("Oxford", graph)
    rc = cli.main([str(o_uid), "Hayfield", "--days", "1", "--artifact", str(art)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Hayfield" in out


def test_pound_plan_uid_path_unknown_uid_still_routes_or_errors_clearly(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    # A uid not in the graph -> plan_route raises ValueError; CLI catches it.
    rc = cli.main(["999999", "0", "--days", "1", "--artifact", str(art)])
    assert rc != 0
    # clear stderr message, not a traceback
    assert capsys.readouterr().err  # non-empty
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/route/test_cli.py -v`
Expected: FAIL — uid tokens passed as `start=` strings to `CanalConstraints` (pydantic accepts arbitrary strings), but `resolve_place` then fails to find "0"/"999999" in the gazetteer → unclear error.

- [ ] **Step 3: Implement uid auto-detect in `cli.py`**

In `pound/route/cli.py`, refactor `main` so that after building the boat kwargs, it inspects `args.start`/`args.end`:

```python
from pound.route.plan import plan_route, plan_route_from_constraints
from pound.route.resolve import resolve_place
from pound.schemas import CanalConstraints, ResolvedConstraints


def _is_uid(tok: str) -> bool:
    return tok.isdigit()


def _resolve_start_end(start_tok, end_tok, graph, *, days, hours_per_day,
                       boat_length_m, boat_beam_m, boat_draft_m, boat_height_m):
    """Return (ResolvedConstraints, True) if any token is a uid, else (CanalConstraints, False).

    Auto-detect: all-digits -> uid (int); else -> name. Mis-resolves a place literally
    named "42" (vanishingly rare; gazetteer keys are "Oxford"/"Banbury"/etc.) — noted
    in the CLI docstring. Mixed uid/name is allowed.
    """
    boat = dict(boat_length_m=boat_length_m, boat_beam_m=boat_beam_m,
                boat_draft_m=boat_draft_m, boat_height_m=boat_height_m)
    if _is_uid(start_tok) or _is_uid(end_tok):
        start_uid = int(start_tok) if _is_uid(start_tok) else resolve_place(start_tok, graph)
        end_uid = int(end_tok) if _is_uid(end_tok) else resolve_place(end_tok, graph)
        return ResolvedConstraints(
            start_uid=start_uid, end_uid=end_uid, days=days, hours_per_day=hours_per_day, **boat,
        ), True
    return CanalConstraints(
        start=start_tok, end=end_tok, days=days, hours_per_day=hours_per_day,
        amenity_prefs=[], **boat,
    ), False
```

Then in `main`, replace the direct `CanalConstraints(...)` build with a call to `_resolve_start_end`, and dispatch:

```python
    graph, meta = load_artifact(artifact)
    graph.graph["fetched_at"] = meta.get("fetched_at", "")

    try:
        constraints, is_resolved = _resolve_start_end(
            args.start, args.end, graph,
            days=args.days, hours_per_day=args.hours_per_day,
            boat_length_m=args.boat_length, boat_beam_m=args.boat_beam,
            boat_draft_m=args.boat_draft, boat_height_m=args.boat_height,
        )
        if is_resolved:
            result = plan_route(constraints, graph=graph)
        else:
            result = plan_route_from_constraints(constraints, graph=graph)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
```

(Keep the existing pydantic `ValidationError` → exit 2 block by validating `days`/`hours_per_day` up front via a throwaway `CanalConstraints` only if you want the early validation; OR move validation into `_resolve_start_end`. The cleanest: build the `CanalConstraints`/`ResolvedConstraints` inside the try and let pydantic raise `ValidationError` -> caught separately -> exit 2. See Step 4 verification.)

- [ ] **Step 4: Run the CLI tests + full suite + ruff**

Run: `uv run pytest tests/route/test_cli.py -v`
Run: `uv run pytest -q`
Run: `uv run ruff check . && uv run ruff format --check .`
Expected: PASS — new uid/mix tests green; existing name-only tests still green (no regression); ruff clean.

- [ ] **Step 5: Commit**

```bash
git add pound/route/cli.py tests/route/test_cli.py
git commit -m "feat(route): pound-plan accepts uids as well as names for start/end"
```

---

### Task 4: README update

**Files:**

- Modify: `README.md`

- [ ] **Step 1: Document `pound-locate` and uid routing**

Append after the existing `## Planning a route (pound-plan)` section:

```markdown
## Locating the nearest canal node (`pound-locate`)

Resolve a coordinate to the nearest canal-network node uid + distance:

```bash
uv run pound-locate --lat 51.75 --lon -1.26
# override the artifact:
uv run pound-locate --lat 51.75 --lon -1.26 --artifact pound/artifacts/england.pkl
# fail if the nearest canal is farther than N metres (for scripting):
uv run pound-locate --lat 51.75 --lon -1.26 --max-distance-m 200
```

Prints `<uid>  <name|->  <distance_m>`. A future map-click UI uses the same
`resolve_coord` function this CLI wraps.

## Routing by uid

`pound-plan` accepts a graph node **uid** (the integer `pound-locate` prints) as
well as a place name for `start` and `end` — auto-detected (all-digits → uid,
else → name), and mixable:

```bash
uv run pound-plan Oxford Hayfield --days 1            # names (as before)
uv run pound-plan 0 1 --days 1                        # uids
uv run pound-plan 0 Hayfield --days 1                 # mixed uid + name
```

This closes the loop: `pound-locate` finds the uid a map click snaps to, then
`pound-plan` routes from it.

```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document pound-locate and uid routing in pound-plan"
```

---

## Acceptance (exit gate)

- `uv run pytest -q` green without pyosmium (bulk tests skip; locate/CLI tests build a fixture-scale artifact into `tmp_path`).
- `pound-locate --lat 51.7501 --lon -1.2601 --artifact <oxford.pkl>` prints `<uid>  <name|->  <distance_m>`; exit 0.
- `pound-locate --lat 51.75 --lon -1.26 --max-distance-m 0.001 --artifact <oxford.pkl>` exits 1 with a clear stderr message.
- `pound-plan 0 1 --days 1 --artifact <oxford.pkl>` prints a real route; exit 0.
- `pound-plan 0 Hayfield --days 1 --artifact <oxford.pkl>` (mixed uid + name) prints a real route; exit 0.
- `pound-plan Oxford Hayfield --days 1` (names only) still works exactly as PR2 — no regression.
- `pound-plan 999999 0 --days 1 --artifact <oxford.pkl>` exits nonzero with a clear error, not a traceback.

## Deferred

A network geocoder (`# future: GeocodeResolver` seam remains in `resolve.py`), rings, amenities, mooring-aware placement, full-GB scale beyond England, `rtree`/`shapely` spatial indexing (linear nearest-node is ms at England scale).
