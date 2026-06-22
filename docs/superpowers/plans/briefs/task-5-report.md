# Task 5 Report: Ingest pure functions (`ingest/filters.py`)

## Summary

Implemented the permanent core ingest pure functions per the brief. Created `pound/ingest/filters.py` and `tests/ingest/test_filters.py`. All parametrized tests pass, full suite passes, ruff clean. Committed with the brief's exact message.

## Changed files

- `pound/ingest/filters.py` (new)
- `tests/ingest/test_filters.py` (new)
- `progress.md` (updated)

## Commands run

| Command | Exit code | Result |
|---|---|---|
| `uv run pytest tests/ingest/test_filters.py -q` | 0 | 28 passed |
| `uv run pytest -q` | 0 | 41 passed |
| `uv run ruff check .` | 0 | All checks passed |
| `git add pound/ingest/filters.py tests/ingest/test_filters.py` | 0 | Files staged |
| `git commit -m "feat(ingest): pure tag->IR functions (classify_way/node, is_derelict, extract_dimensions)"` | 0 | Committed as `78b9e15` |

## Test output summary

- Filter tests: 28 passed
- Full suite: 41 passed
- No failures, no warnings

## Surprises / deviations

- None. The implementation follows the brief exactly.

## Residual risks

- `is_derelict` flags any tag with `disused:` or `abandoned:` prefix, which is broad but matches the brief.
- Dimension aliases are limited to the set in the brief; additional OSM tags (e.g., `seamark:maxheight`) are not handled.
- `classify_node` does not handle amenity tags (pubs etc.); that is explicitly out of scope per the brief.

## Decisions needing approval

- None. All decisions were specified by the brief.
