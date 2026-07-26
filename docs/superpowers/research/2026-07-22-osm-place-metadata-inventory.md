# OSM Place Metadata Inventory

## Scope and source

This Phase 1 inventory is a tag-coverage pass over the original OSM source. It
uses `pyosmium.FileProcessor` directly and does not read or create the filtered
waterway PBF, construct geometry, or attach records to the routing graph.

The reproducible command is:

```bash
inventory_tmp=$(mktemp -d)
trap 'rm -rf "$inventory_tmp"' EXIT
uv run python scripts/catalog_inventory.py \
  --pbf pound/data/england.osm.pbf \
  --out "$inventory_tmp/catalog-inventory.json"
```

The checked-out worktree does not contain `pound/data/england.osm.pbf`, so the
local England command correctly fails with `FileNotFoundError` and writes no
output. The parent supplied the original England PBF tag-scan evidence; this
worker did not rerun that unbounded scan. The fixture run used for the checked-in
behavioral baseline is:

```text
source: tests/fixtures/tiny_bulk.osm
scanned_objects: 54
candidate_objects: 7
counts_by_kind: {"cafe": 1, "fuel": 1, "marina": 1, "museum": 1, "pub": 1,
                 "supermarket": 1, "water_point": 1}
metadata coverage:
  cafe: amenity=1, area=1, name=1
  fuel: amenity=1, name=1, type=1
  marina: area=1, leisure=1, name=1
  museum: name=1, tourism=1
  pub: amenity=1, name=1, opening_hours=1
  supermarket: name=1, shop=1
  water_point: drinking_water=1, name=1, toilets=1, waterway=1
excluded:
  inactive=1, pedestrian_access=3, transport=2

A focused regression adds one duplicate `(node, 2002)` source object to a
copy of the fixture and confirms it is counted once with
`excluded_counts["duplicate"] == 1`. Unnamed approved tags (the fixture's
bakery, restaurant, and second pub) are intentionally not candidates.
```

Objects are deduplicated by `(osm element type, OSM id)` before classification.
Named candidates are required; inactive lifecycle tags (`abandoned`, `disused`,
`razed`, `removed`, including namespaced forms) are rejected. No geometry is
constructed in this pass.

## Exclusions

Transport infrastructure is excluded because Google Maps remains the native
transport-navigation surface and transport markers are not part of the new
catalog. Pedestrian-access infrastructure is excluded because entrances, paths,
and barriers describe route access topology rather than user-facing places. The
inventory records these exclusions instead of promoting their raw tags into the
catalog taxonomy.

## Frozen taxonomy

`pound/catalog/manifest.py` freezes these stable kinds:

- Hospitality: `pub`, `cafe`, `restaurant`.
- Provisions: `supermarket`, `convenience`, `bakery`, `greengrocer`, `butcher`,
  `deli`, `general`.
- Canal services: `marina`, `mooring`, `fuel`, `water_point`,
  `sanitary_disposal`.
- Visitor attractions: `museum`, `gallery`, `historic_site`, `garden`,
  `wildlife_attraction`, `landmark`.

The fixture currently provides measured coverage for seven approved kinds;
the remaining allowlist entries are covered by a synthetic fixture-scale test
and are not inferred from unknown OSM values. `MAX_CATALOG_KINDS` is 16 (a
per-query selection cap, not a taxonomy-size cap), `MAX_CATALOG_RADIUS_M` is
2,000 m, and `MAX_CATALOG_RESULTS` is 1,000. The existing 10,000-route-vertex
ceiling remains unchanged in the route contract.

## Frozen metadata surface and validation policy

The exact raw keys eligible for later normalization are:

```text
name, alt_name, brand, operator,
addr:housenumber, addr:street, addr:place, addr:city, addr:postcode,
opening_hours, access, fee, wheelchair,
phone, contact:phone, email, contact:email,
description, website, contact:website,
wikidata, wikipedia, osm_url
```

Names and descriptive/address/contact values are optional, bounded text fields;
empty values are omitted. Access, fee, and accessibility values remain source
strings until the metadata normalizer applies its controlled validators.
External links accept only absolute `http` and `https` URLs, with no embedded
credentials or malformed/overlong values. Wikidata and Wikipedia references are
canonicalized to safe known links. `osm_url` is a derived OSM provenance link,
not arbitrary source HTML.

The fixture has insufficient coverage to justify additional UI fields such as
cuisine, dietary options, stock hints, capacity, admission details, imagery,
or ratings. Those remain out of the manifest until a measured source inventory
supports them. Raw mapper notes, `fixme`, stale-history tags, arbitrary tags,
and commercial provider content are excluded.

## Resource measurements and production gate

The successful real-England catalog build evidence from the Task 3/4 reports is
kept as the nationwide build baseline. It used the original England PBF after
the catalog tag filter and produced 185,029 records, an 85,378,417-byte artifact,
in 200.49 s wall time, with 2,534,084 KiB peak RSS. The checked-out worktree
still has no `pound/data/england.osm.pbf`, so the final-fix wave used the supplied
absolute source path `/home/kurtt/towpath/pound/data/england.osm.pbf` and a
`mktemp` artifact. That fresh build produced the same 185,029 records and
85,378,417 bytes; `/usr/bin/time` measured **211.32 s** wall time and
**2,527,792 KiB** peak RSS, passing the existing build gates.

A fresh nationwide startup/index-load measurement used a newly generated
temporary catalog artifact containing 185,029 places, the existing England
graph artifact, and actual `GraphSpatialIndex` plus `CatalogSpatialIndex`
construction. The measured process took **117.531 s** wall time and reached
**4,195,472 KiB** maximum RSS. `/usr/bin/time` reported **131.17 s** elapsed,
with **121.11 s** user time and **10.91 s** system time. Temporary files were
deleted after the command. This is a one-time startup cost on the measured
host, not a per-query cost.

Applying 10% headroom to that baseline gives the bounded nationwide
startup/index-load gate shown below:

| Metric | Baseline | Gate | Baseline status |
| --- | ---: | ---: | --- |
| Catalog records (same source/filter) | 185,029 | exactly 185,029; source refreshes require a new inventory review | PASS |
| Artifact size | 85,378,417 bytes | <= 100,000,000 bytes | PASS |
| Catalog build wall time | 200.49 s | <= 300 s | PASS |
| Catalog build peak RSS | 2,534,084 KiB | <= 3,000,000 KiB | PASS |
| Catalog startup + index-load wall time (nationwide) | 117.531 s (inside process) | <= 130 s (inside process) | PASS |
| Catalog startup + index-load peak RSS (nationwide) | 4,195,472 KiB | <= 4,615,019 KiB | PASS |

Both nationwide startup/index-load rows pass. In rounded prose, the RSS gate
may be described as approximately <= 4,600,000 KiB; the exact enforced value is
4,615,019 KiB in the table. The existing catalog build gates remain unchanged.

## Nationwide catalog query-latency evidence and gate

The reproducible benchmark command is:

```bash
benchmark_tmp=$(mktemp -d)
trap 'rm -rf "$benchmark_tmp"' EXIT
uv run pound-ingest catalog england \
  --pbf /home/kurtt/towpath/pound/data/england.osm.pbf \
  --out "$benchmark_tmp/england-catalog.pkl"
uv run python scripts/catalog_query_benchmark.py \
  --catalog-artifact "$benchmark_tmp/england-catalog.pkl" \
  --routing-artifact /home/kurtt/towpath/pound/artifacts/england.pkl \
  --warmups 2 --iterations 5
```

The benchmark loads the independent catalog and routing artifacts, builds the
real `GraphSpatialIndex` and `CatalogSpatialIndex`, warms each case, and times
only `CatalogSpatialIndex.query` with validated `CatalogPlacesRequest` values.
It does not call an internal distance helper or bypass the public query path.
The fixed request set includes locality/no-policy, route+selected-day geometry,
waterway, and the densest predefined viewport whose display-point candidates
remain within the 100,000-candidate work budget. The final-fix run used a
185,029-record catalog, 695,932 routing nodes, and 695,510 routing edges. Its
sorted JSON reported:

| Case (viewport) | Candidates | Matching / over-cap | p50 ms | p95 ms | Max ms | RSS KiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| densest predefined (London) | 35,874 | 1,001 / true | 43.688 | 44.437 | 44.604 | 4,090,568 |
| locality/no-policy (Oxford) | 1,334 | 1,001 / true | 38.462 | 39.829 | 39.838 | 4,090,568 |
| route+day (Milton Keynes) | 802 | 73 / false | 27.919 | 28.524 | 28.555 | 4,090,568 |
| waterway (Milton Keynes) | 802 | 39 / false | 2.651 | 3.079 | 3.172 | 4,090,568 |

The explicit latency gate is **p95 <= 50 ms and max <= 50 ms for every fixed
case**. The worst measured p95 was **44.437 ms** and the worst measured max was
**44.604 ms**, so the gate has **12.1% measured headroom over the worst max**
and passes. The benchmark process took **104.23 s** wall time and reached
**4,090,568 KiB** RSS, including artifact loading and index construction. The
RSS and timings are host-specific; rerun the command after source or index
changes. The 5 timed iterations followed 2 warmups per case; candidate counts
were checked before query execution and every selected viewport was within the
100,000-candidate work budget.

The reproducible England command remains:

```bash
uv run pound-ingest catalog england \
  --pbf pound/data/england.osm.pbf \
  --out "$(mktemp -d)/england-catalog.pkl" \
  --profile
```

Keep temporary PBFs, catalogs, profiler output, and spike data outside the
repository and delete them after measurement. The fixture inventory completes
in approximately 0.04 s in the focused test run; it is behavioral evidence,
not a substitute for the nationwide gate.
