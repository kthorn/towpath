# Scope D PR1 — live (post-merge) testing plan

This is the manual/human-gated testing path for the Scope D PR1 work merged into
`main` at `f8b3b36` (8 feature commits + the merge). The CI hermetic gate is
already green (**130 passed, 5 skipped** = 1 `network` + 4 `bulk`); this document
covers everything CI *deliberately does not* exercise — the real England build,
which needs system prereqs and a 1.5 GiB download, and the dev Overpass path.

Run checks in order. Each section says **what proves the contract**, what to
expect, and what to do if it fails.

> **Branch context:** `scope-d-pr1-bulk-ingest` was merged locally into `main`
> at commit `f8b3b36` (merge `--no-ff`). The worktree was cleaned up and the
> feature branch deleted. SDD artifacts (briefs, reports, review packages,
> progress ledger) are preserved under `.git/sdd/`.

---

## 0. Prereqs (one-time)

You need four things in place before the live tests (C, D) will run. A and B
need none of these.

### 0.1 Python environment

```bash
cd ~/towpath
uv sync --extra dev
```

### 0.2 `osmium-tool` (system CLI — the one non-`uv` install)

Needed for `pound-ingest build england` and the bulk round-trip test (D).

- Debian/Ubuntu: `sudo apt install osmium-tool`
- macOS: `brew install osmium-tool`
- Conda: `conda install -c conda-forge osmium-tool`

Verify:

```bash
osmium --version   # must print a version (e.g. 1.17.x)
```

### 0.3 The `bulk` Python extra (the OSM stream bindings)

> **Name note:** the plan calls this "pyosmium", but the official osmcode project
> publishes on **PyPI as `osmium`** and imports as `import osmium`. The
> committed `bulk` extra pins `osmium>=3.7` correctly. (Plan prose used the word
> "pyosmium"; the spec was corrected during implementation, verified against
> `pypi.org/project/osmium/`.)

```bash
uv sync --extra bulk
python -c "import osmium; print('osmium bindings OK')"
```

Building `osmium` needs native `libexpat`/`zlib`/`libbz2` dev headers. If the
install fails on missing native libs (Debian/Ubuntu):

```bash
sudo apt install libexpat1-dev zlib1g-dev libbz2-dev
uv sync --extra bulk   # retry
```

### 0.4 The Geofabrik England extract (~1.55 GiB — manual download)

The CLI deliberately does **not** download 1.5 GiB itself. ⚠️ Use the
**`united-kingdom`** path — Geofabrik restructured `great-britain/` →
`united-kingdom/`; the old path now 302-redirects to the homepage and serves a
~9 KB **HTML page**, not the PBF (the committed URL was updated to the new path
in the merge: `fix(ingest): correct Geofabrik England URL …`).

```bash
curl -L -o pound/data/england.osm.pbf \
  https://download.geofabrik.de/europe/united-kingdom/england-latest.osm.pbf
```

`-L` follows Geofabrik's 302 from `england-latest` to the dated snapshot
(`england-YYMMDD.osm.pbf`) automatically.

Verify it's the real PBF (~1.55 GiB, **not** a 9 KB HTML):

```bash
file pound/data/england.osm.pbf          # => "Protocol Buffer Format" / data, NOT HTML
ls -lh pound/data/england.osm.pbf        # => ~1.5G
```

If `file` reports `HTML document`, the download hit the homepage — confirm the
URL ends in `/united-kingdom/england-latest.osm.pbf` and re-download.

`POUND_PBF_PATH` overrides the default `pound/data/england.osm.pbf` location.

---

## A. Hermetic smoke (no system prereqs) — do this first

```bash
uv sync --extra dev
uv run pytest -q
```

**Expect:** `130 passed, 5 skipped` (`1 network` = live Overpass fetch;
`4 bulk` = pyosmium/osmium-tool).

This covers the graph build, gazetteer, augmented `validate_graph`, the `build
oxford` path (via the integration gate), and the hard-fail gate logic. If this
isn't green, **stop** — something regressed in the merge.

---

## B. The integration gate (still no system prereqs)

This is the CI-surrogate for the production build path. It monkeypatches
`fetch_oxford` so no network is used.

```bash
uv run pytest tests/ingest/test_pipeline_integration.py -v
```

**Expect:** both tests pass:

- `test_build_oxford_artifact_has_connected_graph_and_gazetteer` — builds the
  Oxford artifact via the real CLI path with the default
  `pound/data/overrides.json` (which resolves the fixture's pendant snap),
  asserts `tolerance_snaps_unresolved == []`, `tolerance_snaps_used` non-empty,
  and `gazetteer` contains `Oxford`, `Hayfield`, `Marston`.
- `test_build_oxford_gate_fails_when_pendant_left_unresolved` — same build with
  an absent overrides file → gate fires, `rc != 0`, no artifact written.

---

## C. `pound-ingest build oxford` CLI directly — **network-dependent**

> ⚠️ The Overpass reader is **dev scaffolding** (small Oxford dataset). It
> hits `overpass-api.de` live, so it is gated by the `--run-network` marker and
> **may transiently fail with `406 Not Acceptable`** (Overpass rate-limits /
> anti-bot). A 406 is not a code defect — retry later, or treat section B as
> the authoritative Oxford evidence.

If you want to exercise the live path anyway (network required):

```bash
uv run pound-ingest build oxford --out /tmp/oxford.pkl
```

**Expect:** exit `0` and a JSON validation report on stdout. Load the artifact
and check the PR1 acceptance keys:

```bash
uv run python -c "
import pickle
g, m = pickle.load(open('/tmp/oxford.pkl', 'rb'))
v = m['validation']
print('derelict_edges:', v['derelict_edges'])
print('self_loops:', v['self_loops'])
print('tolerance_snaps_used:', len(v['tolerance_snaps_used']))
print('tolerance_snaps_unresolved:', v['tolerance_snaps_unresolved'])
print('gazetteer places:', sorted(g.graph['gazetteer']))
print('component_count:', v['component_count'])
"
```

**Built artifact acceptance criteria (must hold):**

- `derelict_edges == 0`
- `self_loops == 0`
- `tolerance_snaps_unresolved == []` (the pendant is resolved by the shipped
  `pound/data/overrides.json`)
- `tolerance_snaps_used` non-empty (at least the resolved pendant)
- `gazetteer` contains `Oxford`, `Hayfield`, `Marston`

If `tolerance_snaps_unresolved` is non-empty on the Oxford build, the shipped
`overrides.json` is wrong — report it.

---

## D. `pound-ingest build england` CLI — **human-gated, needs all prereqs**

This is the headline PR1 deliverable. Per the plan's OQ-5, the **report is the
authority, not the threshold**: run once at a *low* tolerance to *measure*
fragmentation, then curate and/or dial tolerance up.

### D.1 First pass — measure fragmentation (low tolerance)

```bash
uv run pound-ingest build england --out /tmp/england.pkl --tolerance-m 1
```

The build will print a JSON validation report to stdout, then either exit `0`
(wrote the artifact) or exit non-zero after printing `BUILD FAILED: …` to
stderr (**without** writing the artifact).

**Read `component_count` and `component_sizes`** in the report:

| Signal | Interpretation | Next step |
|--------|----------------|-----------|
| **thousands** of components | Most "gaps" are real OSM-edit curation work | Add `join` overrides to `pound/data/overrides.json`; raise `--tolerance-m` gradually |
| **~ a dozen** components | Fragmentation is plausibly genuine (derelict arms, separate basins) | Most "gaps" are correct as-is |

**Expected at `--tolerance-m 1`:** the gate will most likely **fail** at the
default `--max-unresolved-snaps 0` because the curation queue
(`tolerance_snaps_unresolved`) is non-empty. This is **the design** —
unresolved snaps are the curation queue, surfaced for manual resolution via
`overrides.json`. It is not a defect; do not raise `--max-unresolved-snaps` to
mask it. Curate real joins and suppress false joins instead.

### D.2 The curation loop (ongoing)

`pound/data/overrides.json`, format:

```json
{
  "join": [["<osm-node-id-a>", "<osm-node-id-b>"]],
  "split": [["<osm-way-id-a>", "<osm-way-id-b>"]]
}
```

- `join` — connect two OSM node ids' graph nodes (resolves a near snap AND
  bridges genuine gaps where coords aren't within tolerance).
- `split` — suppress a snap between the two ways' near ends (the aqueduct /
  overpass / parallel-canal case).

`load_overrides` rejects unknown top-level keys (no `_comment` — document the
worked example in the commit message instead).

References the `tolerance_snaps_unresolved` queue from the report for the next
batch of joins/splits.

### D.3 Iterate until the gate is green

Re-run after each curation round:

```bash
uv run pound-ingest build england --out /tmp/england.pkl --tolerance-m <N>
```

The build writes `/tmp/england.pkl` when:

- `derelict_edges == 0`
- `self_loops == 0`
- `len(tolerance_snaps_unresolved) <= --max-unresolved-snaps` (default `0`)

**Advisory keys never fail the build** — read them, don't gate on them:

- `component_count`, `component_sizes` (the fragmentation dial)
- `edges_missing_dims` (ways lacking `maxwidth`/`maxdraught`/etc.)
- `ambiguous_place_names` (duplicate place names → a `list` in the gazetteer)
- `place_nodes_seen` vs `place_nodes_in_gazetteer` (gazetteer coverage)

Load the trusted artifact and inspect:

```bash
uv run python -c "
import pickle
g, m = pickle.load(open('/tmp/england.pkl', 'rb'))
v = m['validation']
print(v)
print('gazetteer size:', len(g.graph['gazetteer']))
print('ambiguous places:', v['ambiguous_place_names'][:10])
"
```

---

## E. Bulk unit tests (optional — confirms the reader round-trips)

```bash
uv run pytest --run-bulk
```

With the `bulk` extra installed, the 4 `tests/ingest/test_osm.py` tests run:

- `test_tags_filter_expr_is_pinned` — the pinned osmium tags-filter expression
  contains the right keys and excludes dimension-alias lines.
- `test_read_pbf_populates_node_ids_and_features` — `read_pbf` fills `node_ids`
  and produces the right `WaterwayFeatures` shape.
- `test_read_pbf_captures_place_and_lock_gate_nodes` — place and lock_gate nodes
  captured.
- `test_tags_filter_round_trip_matches_overpass_shape` — **additionally needs
  `osmium-tool` on PATH** (it calls `osmium tags-filter`); SKIPs if absent.

If a `bulk` test SKIPs with reason `pyosmium not installed`, you forgot
`uv sync --extra bulk` (prereq 0.3).

---

## Triage: if a step fails

| Symptom | Cause | Fix |
|---------|-------|-----|
| Bulk tests skip with `pyosmium not installed` | `bulk` extra not installed | `uv sync --extra bulk` (prereq 0.3) |
| `build england` says "Missing England extract at …" | PBF not at default path | Download (prereq 0.4) or set `POUND_PBF_PATH` |
| Downloaded file is ~9 KB HTML | Used the old `great-britain` URL | Use `/united-kingdom/england-latest.osm.pbf` |
| `build england` exec error on `osmium tags-filter` | `osmium-tool` not on PATH | Install it (prereq 0.2) |
| Gate fires on `tolerance_snaps_unresolved=N` | Real curation work needed (expected at low tolerance) | Curate `pound/data/overrides.json` from the queue (D.2) |
| `build oxford` returns `406 Not Acceptable` | Overpass rate-limiting (transient, dev path only) | Retry later, or rely on section B |

---

## Known deferred / latent items (not PR1 blockers)

Recorded during the final whole-branch review; not fixed in PR1:

- **`_contract` union-find (Task 1 review #2).** The Phase-1 transitive
  contraction in `pound/graph/build.py` lacks union-find for overlapping key
  groups. The final reviewer's analysis: **unreachable with pyosmium data**
  (pyosmium reports one consistent location per OSM node id → `id2keys[sid]`
  is always length 1 → Phase 1 produces no groups → contraction never fires).
  Latent logic defect; optional future polish. Worth revisiting if a synthetic
  fixture ever exercises it.
- **Oxford fixture is hybrid.** Ways 1003 and 1007 carry synthetic `nodes`
  arrays (which real Overpass `out geom` never returns) so the `join` override
  can anchor on OSM node ids. A fixture comment clarifying real Overpass never
  returns `nodes` would help future readers.
- **Movable-bridge nodes.** The pinned `TAGS_FILTER_EXPR` does not pull
  `node["bridge:movable"]` (the Overpass dev query does), so the bulk path
  silently drops movable-bridge nodes. Per the pinned spec; flag for PR2 if
  movable bridges matter.

---

## Done-when

PR1 is trusted on real data when **all** of these hold:

- [ ] Section A green (`130 passed, 5 skipped`)
- [ ] Section B green (2 integration tests)
- [ ] Section D: a real `england.pkl` exists with `derelict_edges == 0`,
      `self_loops == 0`, `tolerance_snaps_unresolved` within your curated
      budget, and a `component_count` whose order of magnitude you understand
      (the human-read fragmentation signal — thousands ⇒ needs curation;
      ~a dozen ⇒ plausibly genuine)
- [ ] `pound/data/overrides.json` shows evidence of curation rounds (or you
      have consciously decided the low-tolerance queue is acceptable)

PR2 (`docs/superpowers/plans/2026-06-25-pound-scope-d-pr2-resolve-cli.md`) —
the `OfflineResolver`, contract evolution, `pound-plan` CLI, retirement of
`route/snap.py` — stays out of scope for PR1.
