# OSM Place Metadata Inventory

## Scope and source

This Phase 1 inventory is a tag-coverage pass over the original OSM source. It
uses `pyosmium.FileProcessor` directly and does not read or create the filtered
waterway PBF, construct geometry, or attach records to the routing graph.

The reproducible command is:

```bash
uv run python scripts/catalog_inventory.py \
  --pbf pound/data/england.osm.pbf \
  --out /tmp/catalog-inventory.json
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

## Resource measurements

The parent supplied the nationwide England PBF scan evidence from the original
source. This worker intentionally did not repeat that expensive scan. The
fixture inventory completes in approximately 0.04 s in the focused test run;
process peak RSS and a nationwide artifact-size estimate belong to the parent's
full-scan evidence and are not regenerated here.
