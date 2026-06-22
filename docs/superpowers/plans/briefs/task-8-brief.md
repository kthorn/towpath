## Task 8: Dev CLI + run the real Oxford fetch + document the B deliverable

A thin dev convenience to actually fetch the Oxford extract, print the `summarize()` report, and optionally write the features JSON to `pound/data/` (gitignored). This is how you eyeball the pipeline on real OSM data — the unit-test fixture only proves the logic; this proves it on the real source.

**Files:**

- Create: `/home/kurtt/pound/pound/ingest/cli.py`
- Modify: `/home/kurtt/pound/README.md` (add usage section)
- Test: `tests/ingest/test_cli.py`

**Interfaces:**

- Consumes: `pound.ingest.overpass.fetch_oxford`, `pound.ingest.summarize.summarize`
- Produces: `main(argv=None) -> None` (entry point `pound-ingest`)

- [ ] **Step 1: Write the failing test**

Create `/home/kurtt/pound/tests/ingest/test_cli.py`:

```python
import json
from pathlib import Path

from pound.ingest import cli
from pound.ingest.ir import (
    NodeKind,
    WaterwayFeatures,
    WaterwayKind,
    WaterwayNode,
    WaterwayWay,
    WayDimensions,
)


def _sample_features() -> WaterwayFeatures:
    return WaterwayFeatures(
        ways=[
            WaterwayWay(
                osm_id=1, kind=WaterwayKind.CANAL, name="Oxford Canal",
                tags={"waterway": "canal"}, node_ids=[], geometry=[(51.75, -1.26)],
                dimensions=WayDimensions(max_beam_m=2.1),
            )
        ],
        nodes=[
            WaterwayNode(osm_id=10, lat=51.75, lon=-1.26,
                         tags={"waterway": "lock_gate"}, kind=NodeKind.LOCK_GATE)
        ],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=(51.70, -1.35, 51.80, -1.20),
    )


def test_cli_prints_report_and_writes_out(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_oxford", lambda: _sample_features())
    out_path = tmp_path / "oxford.json"
    cli.main(["oxford", "--out", str(out_path)])

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["way_count"] == 1
    assert report["ways_by_kind"] == {"canal": 1}

    written = WaterwayFeatures.model_validate_json(out_path.read_text())
    assert written.source == "overpass"
    assert len(written.ways) == 1


def test_cli_rejects_unknown_region(monkeypatch):
    monkeypatch.setattr(cli, "fetch_oxford", lambda: _sample_features())
    try:
        cli.main(["bogus"])
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("expected SystemExit for unknown region")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/ingest/test_cli.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pound.ingest.cli'`.

- [ ] **Step 3: Write `pound/ingest/cli.py`**

Create `/home/kurtt/pound/pound/ingest/cli.py`:

```python
"""Dev CLI for the ingest pipeline.

Usage:
    python -m pound.ingest.cli oxford [--out pound/data/oxford_canal_waterways.json]

Fetches the Oxford Canal Overpass extract, prints the summarize() report as
JSON, and optionally writes the WaterwayFeatures IR to --out. Network use only.
Not imported by library code.
"""

import argparse
import json
import sys
from pathlib import Path

from pound.ingest.overpass import fetch_oxford
from pound.ingest.summarize import summarize


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pound-ingest")
    parser.add_argument("region", choices=["oxford"], help="region to fetch")
    parser.add_argument(
        "--out",
        default=None,
        help="path to write the WaterwayFeatures JSON (e.g. pound/data/oxford_canal_waterways.json)",
    )
    args = parser.parse_args(argv)

    if args.region == "oxford":
        features = fetch_oxford()
    else:  # pragma: no cover - argparse choices guard this
        parser.error(f"unknown region: {args.region}")
        return

    report = summarize(features)
    print(json.dumps(report, indent=2))

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(features.model_dump_json(indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/ingest/test_cli.py -q
```

Expected: 2 passed.

- [ ] **Step 5: Update `README.md` with ingest usage**

Replace the `## Development` section in `/home/kurtt/pound/README.md` with:

```markdown
## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```

## Regional ingest (dev / scaffolding)

The Overpass reader is **scaffolding** for early development on a small dataset
(Oxford Canal). It is replaced by a pyosmium bulk reader over the Geofabrik GB
PBF in design step 6.

Fetch the Oxford extract and print the summarize() report (network required):

```bash
uv run pound-ingest oxford
# or, also writing the features IR:
uv run pound-ingest oxford --out pound/data/oxford_canal_waterways.json
```

Network tests are skipped by default; run them explicitly:

```bash
uv run pytest --run-network
```

```

- [ ] **Step 6: Run the full suite (network skipped) and lint**

```bash
uv run pytest -q
uv run ruff check .
```

Expected: all non-network tests pass; 1 network test skipped.

- [ ] **Step 7: Run the live Oxford fetch to validate the pipeline on real OSM**

```bash
uv run pound-ingest oxford --out pound/data/oxford_canal_waterways.json
```

Expected: a JSON report printed to stdout with `way_count > 0`, `ways_by_kind`
including `"canal"`, and a non-zero `lock_count` or lock-gate nodes for the
Oxford flight. The `pound/data/oxford_canal_waterways.json` file is written
(gitignored — confirm with `git status` that it is NOT staged).

If the live fetch fails (Overpass rate limit / timeout), retry once after a
short wait; do not commit the `pound/data/` output. The pipeline is still
validated by the unit tests + fixture; the live run is a manual sanity check.

- [ ] **Step 8: Confirm data/ stays out of git**

```bash
git status --short
```

Expected: `pound/data/oxford_canal_waterways.json` does NOT appear (gitignored).
Only `README.md`, `pound/ingest/cli.py`, `tests/ingest/test_cli.py` are staged.

- [ ] **Step 9: Commit**

```bash
git add pound/ingest/cli.py tests/ingest/test_cli.py README.md
git commit -m "feat(ingest): dev CLI (pound-ingest oxford) + README usage section"
```

---

