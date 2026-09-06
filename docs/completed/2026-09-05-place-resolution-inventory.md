# Place-resolution catalog inventory (#77)

## Scope and method

This note records the local catalog evidence available before implementing the
resolver. The reproducible inventory command is:

```bash
.venv/bin/python scripts/place_resolution_inventory.py \
  --catalog /path/to/great-britain-catalog.pkl \
  --warmups 2 --iterations 7
```

The script loads the artifact only through
`pound.catalog.artifact.load_catalog`, so it accepts only the current restricted
catalog pickle contract. It emits sorted JSON to stdout and does not create or
modify catalog, PBF, or graph artifacts. The report includes the catalog path,
file size, complete artifact metadata, load time/RSS, record count, coordinate
extent, counts by kind, name/alias/locality completeness, and deterministic
national linear scans for:

| Case | Query | Match rule |
| --- | --- | --- |
| exact | `Bletchley Park` | normalized primary name or recorded alias equals the query |
| partial | `bletchley` | normalized primary name or recorded alias contains the query |
| miss | `place-resolution-inventory-no-such-name-9f4b` | same partial rule, expected to be empty |

Whitespace is collapsed and text is `casefold`ed. Every scan examines every
catalog record; the report records that work explicitly, along with match
identities, warmups, iterations, p50/p95/max milliseconds, and RSS. Locality is
measured from the existing normalized `address.place` and `address.city`
fields. No locality is inferred from coordinates or source strings.

## Local artifact findings (2026-09-05)

No usable Great Britain catalog artifact is present in the checked local
search roots (`/home/kurtt/towpath` and `/tmp`). The only non-test catalog
artifact found is:

```text
/home/kurtt/towpath/pound/artifacts/england-catalog.pkl
82622655 bytes
```

Running the inventory against it through the current loader fails with:

```text
Invalid catalog: could not load catalog: catalog pickle global is not allowed: pound.ingest.ir.OsmElementType
```

This is an older pre-package-split artifact. It is intentionally treated as
stale and rejected; no unrestricted or compatibility unpickling was used. The
small `great-britain.pkl` files under pytest temporary directories are routing
test fixtures, not place catalogs, and are not evidence of Great Britain
catalog coverage.

The checked-in README records build metadata for a Great Britain catalog built
on 2026-09-02: 218,443 records, 101,046,536 bytes, 167.91 seconds wall time,
and 2,968,328 KiB peak RSS. It also states that the source was the original
Great Britain PBF and that the catalog contract is schema version 3. These are
historical build results and provenance claims; they do not establish that the
artifact is currently staged or loadable in this checkout. The README contains
no Bletchley record, alias, locality, or national name-scan results.

Consequently, this checkout cannot provide real Great Britain counts/name,
alias, locality, extent, Bletchley-match, or exact/partial/miss latency
measurements. The inventory script and its focused tests exercise those fields
against a current schema-v3 fixture, but those fixture timings are not a
national Great Britain baseline. A fresh schema-v3 Great Britain artifact must
be staged locally and rerun before using numeric lookup latency or memory as a
production decision gate.

## Index recommendation

The historical record count is 218,443, already above the proposed 100,000
records-per-operation OSM work budget. A direct national scan would therefore
consume more than the budget for every exact, partial, and miss query once a
current Great Britain catalog is available. Build an in-memory normalized
primary-name/recorded-alias index once while loading that same catalog, with
entries referring to existing records. Keep partial enumeration bounded and
rebuild the index when `catalog_revision` changes. Do not persist a second
source of truth or alter the catalog schema in this inventory slice.

The staged-artifact rerun should compare index construction RSS/startup cost
with direct-scan work and latency on the same host, and should report exact,
partial, duplicate, and miss behavior for Bletchley and representative names.
Until that rerun is possible, the recommendation is based on the documented
218,443-record build size and the explicit 100,000-record work ceiling rather
than on an observed current artifact.

## Verification

The focused script tests pass with the current schema-v3 fixture:

```text
2 passed
```

Ruff also passes for the script and its focused tests. The England artifact
loader rejection above was captured from the same `.venv/bin/python` runtime.
