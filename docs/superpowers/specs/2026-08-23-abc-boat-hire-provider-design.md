# ABC Boat Hire provider ingestion design

## Purpose

Add ABC Boat Hire as an independent boat-hire source provider. It must never be
merged into an existing provider merely because two providers use the same
marina. The source is ABC Boat Hire's official map at
`https://www.abcboathire.com/our-locations`; its embedded marker array is a
one-time curation input only, never a runtime or test-time network dependency.

## Canonical records

Create 16 `company_base` records with:

- `source_provider_id=abc-boat-hire`
- `source_provider_name=ABC Boat Hire`
- `source_provider_website=https://www.abcboathire.com/`
- `location_id=base:<raw marker slug>`
- `location_name` and `official_location_name` equal to the exact marker name
- `source_url` and `evidence_url` both equal to the official map URL
- `source_kind=official_location_map`
- `google_search_url` formed as `ABC Boat Hire` plus the marker name plus
  `boat hire`, using `+` for spaces
- blank `location_area`, `waterway`, operator, booking, contact, and `osm_url`
  fields unless independently evidenced
- `review_identity=abc-boat-hire-map/<raw marker slug>`
- `enrichment_status=provider_map_verified`
- notes containing the exact marker name and raw marker slug, with exact
  coordinate strings recorded in the row and its offline test attestation.

No OSM association, provider association, redirect following, title heuristic,
or coordinate-proximity identity inference is permitted.

| Location ID | Marker name | Latitude | Longitude | Coverage |
|---|---|---:|---:|---|
| `base:aldermaston-wharf` | Aldermaston Wharf | 51.400800 | -1.134460 | active |
| `base:march-marina` | March Marina | 52.554174 | 0.064960 | active |
| `base:alvechurch-marina` | Alvechurch Marina | 52.347199 | -1.970306 | active |
| `base:falkirk` | Falkirk Canal | 56.000526 | -3.842200 | excluded |
| `base:goytre-wharf` | Goytre Wharf | 51.751262 | -2.997115 | excluded |
| `base:anderton-marina` | Anderton Marina | 53.276055 | -2.523323 | active |
| `base:blackwater-meadow-marina` | Blackwater Meadow Marina | 52.902436 | -2.889776 | active |
| `base:gailey-base` | Gailey Marina | 52.690789 | -2.119703 | active |
| `base:gayton-marina` | Gayton Marina | 52.191493 | -0.945934 | active |
| `base:hilperton-marina` | Hilperton Marina | 51.338480 | -2.204374 | active |
| `base:whitchurch-marina` | Whitchurch Marina | 52.968024 | -2.708846 | active |
| `base:worcester-marina` | Worcester Marina | 52.196215 | -2.216549 | active |
| `base:wrenbury-mill` | Wrenbury Mill | 53.028227 | -2.612507 | active |
| `base:kings-orchard` | Kings Orchard Marina | 52.691398 | -1.780221 | active |
| `base:springwood-haven` | Springwood Haven | 52.541490 | -1.492940 | active |
| `base:nantwich-canal-centre` | Nantwich Canal Centre | 53.071111 | -2.541386 | active |

Falkirk Canal and Goytre Wharf are explicit out-of-coverage records with
`exclude=true`; add only those two exact identities to the exclusion set.
Wrenbury Mill remains active: ABC's own location page gives its address as
"Nr Nantwich, Cheshire, CW5 8HG." Its Welsh Borders marketing grouping is not
an out-of-England location classification.

## Validation

Extend the offline data test with an identity-keyed, 16-entry ABC map
attestation table containing the marker name, raw slug, latitude, longitude,
and exclusion value. Assert that every and only ABC map-evidence row equals
this set, with exact canonical identity, coordinate strings, review identity,
status, blank OSM URL, map/source URLs, and notes. Update CSV structural counts
from 117 to 133 total rows and 106 to 122 `company_base` rows. Update the
explicit exclusion set from 13 to 15 identities.

No resolution-queue rows are required: every new source row enters with
first-party map evidence and has no manual-evidence handoff.

## Runtime and deployment behavior

No runtime code changes are required. The existing loader will include the 14
active ABC seeds and ignore the two excluded ones. The existing 250 m,
routing-eligible-edge startup gate remains unchanged. A deployment check against
the intended England graph must pass for every active ABC seed; a failure must
stop curation for manual review rather than broaden the threshold or exclude a
row implicitly.

## Non-goals

- No ABC data is used to alter an existing provider's record.
- No new map scraper, HTTP client, dependency, spatial index, runtime fallback,
  or provider-switch configuration is added.
- No coordinate or evidence is guessed from a nearby marker or shared base.
