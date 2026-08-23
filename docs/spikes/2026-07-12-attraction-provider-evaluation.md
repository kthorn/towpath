# Attraction Dataset and Live Provider Evaluation

**Issue:** [#27](https://github.com/kthorn/towpath/issues/27)
**Research date:** 2026-07-12
**Decision status:** In progress

## Executive Decision

Use OSM as the durable attraction catalog and Google Places as optional, user-triggered live
enrichment. Reuse Towpath's existing Google Maps JavaScript integration, restricted browser key,
Google map, and Places library. Persist only Google Place IDs; never prefetch or copy Google fields
into the offline artifact. Do not integrate Tripadvisor in the first version. Evaluate Historic
England as an OGL heritage supplement after the OSM taxonomy is working.

## Product Requirement

Towpath needs one attraction system for two surfaces: browsing the whole canal network and showing
interesting destinations along a planned route. The first scope includes museums, galleries,
historic sites and monuments, gardens and notable parks, wildlife attractions, and notable visitor
landmarks within a geometric 2 km corridor of navigable canal geometry. Hospitality belongs to the
separate general-amenity scope.

The 2 km test establishes canal proximity, not a safe or walkable towpath connection. Access scoring
or walking routes are separate work.

## Evidence Labels

- **Verified policy:** supported by current first-party documentation linked in this record.
- **Observed sample:** measured by the reproducible query recorded in the OSM sample fixture.
- **Unverified:** plausible but not tested because credentials, approval, or reusable data were not
  available.

## Evaluation Matrix

| Source | Durable catalog | Ratings/current details | Coverage evidence | Cost evidence | Decision |
|---|---|---|---|---|---|
| OpenStreetMap | Yes, under ODbL | No general rating signal | Five England samples | Bulk/hosting only | Baseline candidate |
| Google Places API (New) | No; place IDs only | Yes | Unverified without credentials | Published SKU pricing | Enrichment candidate |
| Tripadvisor Content API | No; location IDs only | Yes | Unverified without credentials | Partly login-gated | High-risk candidate |
| Official UK heritage data | Yes where OGL applies | No ratings | Dataset availability verified | Download/hosting only | Supplemental candidate |

## Sample Design

The spike uses point-radius samples as a cheap comparison, not as a complete census of a canal
corridor. Each query searches 2 km around a representative canal location using the same attraction
tag allowlist.

| Sample | Character | Reason |
|---|---|---|
| Birmingham, Gas Street Basin | Dense city | High POI density and mixed cultural tagging |
| Oxford, central canal corridor | Canal city | Museums and historic features near urban waterways |
| Foxton Locks | Tourism-heavy rural | Canal attraction expected to be strongly represented |
| Braunston | Rural canal hub | Village-scale canal tourism with sparse surrounding POIs |
| Fenny Stratford | Sparse/suburban | Tests whether baseline results become thin away from major destinations |

## Provider Findings

### OpenStreetMap

**Verified policy.** OSM data is available under the Open Database License. A distributed Towpath
POI database must attribute OpenStreetMap and comply with ODbL requirements. The
[OSMF attribution guidance](https://osmfoundation.org/wiki/Licence/Attribution_Guidelines) is the
implementation reference.

OSM covers the required categories with tags such as `tourism=museum`, `tourism=gallery`,
`tourism=attraction`, `historic=*`, and selected `leisure=*` values. It offers source geometry,
names, websites, opening-hours strings, wheelchair/access tags, and Wikidata/Wikipedia links where
contributors supplied them. It does not offer a consistent popularity or review score.

The local PBF sample shows that broad tags are not a ready-made recommendation feed. `historic=*`
includes administrative boundaries, canal remnants, memorials, and many other records that are not
visitor destinations. `tourism=artwork` and `leisure=garden` create very high urban cardinality,
while rural Braunston has no named result in the broad sample. Source-identity and semantic
deduplication are mandatory: several named places appear through multiple OSM elements.

Public Overpass returned two samples but rejected or timed out on the other three. Use bulk extracts
for repeatable catalog builds; reserve Overpass for development and diagnostics.

### Google Places API (New)

**Verified policy and capability; live quality unverified.** Nearby Search supports circular
location restrictions, type filters, popularity/distance ranking, and required field masks. The
current type vocabulary directly covers museums, galleries, historical places and landmarks,
gardens, wildlife attractions, zoos, aquariums, and tourist attractions. See the official
[place types](https://developers.google.com/maps/documentation/places/web-service/place-types) and
[Nearby Search](https://developers.google.com/maps/documentation/places/web-service/nearby-search)
documentation.

Google's [Places policies](https://developers.google.com/maps/documentation/places/web-service/policies)
prohibit prefetching, caching, or storing Places content outside stated exceptions. Place IDs may be
stored indefinitely, but Google recommends refreshing IDs older than 12 months. Places displayed on
a map must use a Google map with required Google and third-party attribution; non-map displays still
require Google branding. Photos and reviews carry additional author/provider attribution.

Field masks determine the highest billed SKU. Display name, location, types, address, and place ID
are Pro fields for Nearby Search. Ratings, user rating counts, opening hours, price, phone, and
website fields raise Nearby Search or Place Details to Enterprise. Reviews and editorial summaries
raise requests to Enterprise + Atmosphere. This strongly favors an OSM-first list with Google detail
requests only after user interaction.

### Tripadvisor Content API

**Verified policy and capability; live quality unverified.** Tripadvisor Nearby Search accepts a
coordinate, radius, and `attractions` category, but returns at most ten nearby locations per request.
Its [caching policy](https://tripadvisor-content-api.readme.io/reference/caching-policy) prohibits
caching, storing, or indexing every returned attribute except `location_id`. Required Tripadvisor
branding and rating imagery must follow its display requirements.

The current [FAQ](https://tripadvisor-content-api.readme.io/reference/faq) advertises 5,000 free API
calls per month after billing signup, a user-selected daily budget, and up to 10,000 search calls per
day. Exact overage pricing is presented during account checkout rather than in public documentation.
The FAQ also announces a forthcoming Terra API platform. That migration notice, ten-result search
cap, single-key account model, non-cacheability, and login-gated pricing make Tripadvisor a higher
operational-risk enrichment candidate than Google for this spike.

### Official UK Tourism and Heritage Data

**Verified dataset availability; visitor attractiveness unverified.** The strongest immediately
usable official source is Historic England's National Heritage List for England. Its
[Open Data Hub](https://historicengland.org.uk/listing/the-list/data-downloads) supplies current
listed buildings, scheduled monuments, registered parks and gardens, battlefields, and World
Heritage data in downloadable and API formats. The data is free under OGL, with specific Historic
England and Ordnance Survey attribution and currency statements documented in the
[Open Data Hub terms](https://historicengland.org.uk/terms/website-terms-conditions/open-data-hub/).

Cadw publishes Welsh listed-building and scheduled-monument downloads through DataMapWales; the
listed-building metadata identifies OGL. Historic Environment Scotland publishes downloads for
listed buildings, scheduled monuments, and gardens/designed landscapes through its heritage portal.
These sources can improve authoritative heritage coverage as a later UK-wide supplement.

Designation does not equal tourist appeal: the NHLE alone contains hundreds of thousands of
records. These datasets need an attraction-worthiness policy or should enrich matching OSM records,
not be displayed wholesale. Ordnance Survey Points of Interest has useful cultural/tourism classes
but is a licensed product rather than the open baseline selected here.

## OSM Coverage Sample

The checked-in
[`attraction-provider-osm-sample.json`](fixtures/attraction-provider-osm-sample.json) records the
query policy, extract timestamp, counts, attribution, and examples. The local source was the
Geofabrik England PBF at replication timestamp `2026-06-27T20:21:30Z`.

| Area | Character | Raw records | Named | Key observation |
|---|---|---:|---:|---|
| Birmingham | dense city | 958 | 410 | Artwork and garden noise dominate; strong museum/gallery signal exists |
| Oxford | canal city | 839 | 379 | Rich coverage but heavy garden/artwork duplication and broad attractions |
| Foxton Locks | tourism-heavy rural | 9 | 6 | Correctly finds locks, inclined plane, and museum in a small result set |
| Braunston | rural canal hub | 3 | 0 | Broad OSM tags alone fail to yield a useful named attraction list |
| Fenny Stratford | sparse/suburban | 70 | 56 | Finds Bletchley Park but includes broad historic/duplicate records |

Counts are intentionally pre-taxonomy and pre-deduplication. They measure the raw policy's workload,
not the number of recommendations a user should see. Distances use full exported geometry segments,
not only label points. Point-radius samples are not complete canal-corridor censuses.

Live Overpass cross-checks returned 555 Oxford elements and 3 Braunston elements from the same query
shape on `2026-07-12`. The different Oxford count reflects source date/export/query semantics and
reinforces that the spike should compare representative quality rather than claim an exact census.

## Cost and Operational Model

### Existing integration

Towpath already loads the Google Maps JavaScript `maps`, `places`, `routes`, and `marker` libraries
through one browser SDK boundary. The operating guide already requires Maps JavaScript API, Places
API, and Routes API, and a website-restricted browser key. Attraction enrichment therefore needs a
new adapter and field policy, not a second provider account or server-side key.

The current adapter uses Autocomplete with name, formatted address, and geometry. Attraction
enrichment should use the current Places API surface exposed by the loaded Places library rather
than extending the legacy Autocomplete result as an implicit cache. Before implementation, confirm
that the production project's enabled Places API and key restrictions permit the selected Nearby
Search/Place Details calls.

### Google incremental cost scenarios

The official [Google Maps Platform pricing list](https://developers.google.com/maps/billing-and-pricing/pricing)
reviewed on 2026-07-12 gives these global first-tier prices per 1,000 billable events:

- Nearby Search Pro: $32 after 5,000 free monthly events;
- Place Details Enterprise: $20 after 1,000 free monthly events;
- Place Details Photos: $7 after 1,000 free monthly events.

The model assumes search requests ask only for Pro discovery/matching fields; ratings, rating counts,
current hours, website, and similar fields are fetched with Enterprise details only after selection.
It excludes existing map/route charges, taxes, currency conversion, higher-volume discounts, and any
Enterprise + Atmosphere fields such as reviews or editorial summaries.

| Scenario | Search/month | Detail/month | Photo/month | Approx. incremental monthly cost |
|---|---:|---:|---:|---:|
| Four-person pilot | 350 | 350 | 350 | $0 |
| Low | 2,000 | 2,000 | 400 | $20 |
| Medium | 10,000 | 20,000 | 10,000 | $603 |
| High | 60,000 | 100,000 | 50,000 | $4,083 |

The four-person pilot assumes each person uses the explorer twice per week, for about 35 sessions
per month (`4 × 2 × 52 ÷ 12`), and opens ten enriched attraction cards per session. It conservatively
assigns one Pro search, one Enterprise detail request, and one photo request to every opened card.
All three monthly totals remain inside their respective free usage caps. Even twenty attraction
cards per session would produce about 700 events of each kind and remain at $0 incremental Places
cost. At thirty cards per session, approximately 1,040 details and photos would cost about $1.08
total while searches would remain below their 5,000-event free cap.

Calculations apply the free caps independently, then use the first paid tier: medium is
`5,000×$0.032 + 19,000×$0.020 + 9,000×$0.007`; high is
`55,000×$0.032 + 99,000×$0.020 + 49,000×$0.007`.

This makes viewport-driven commercial searches unattractive. The implementation should render and
filter the viewport from OSM, then call Google when a user opens a detail card or explicitly requests
current information. A session-level request coalescer may prevent duplicate in-flight requests, but
the implementation must not assume persistent response caching is permitted.

### Failure modes

- **No key or Places unavailable:** show OSM and official-source fields without ratings.
- **Quota/budget exhausted:** stop enrichment, retain the detail card, and show a concise unavailable
  state rather than retrying across every marker.
- **No confident Google match:** do not attach ratings; offer the stored OSM website or a Google Maps
  search link where policy permits.
- **Place ID ages:** refresh stored IDs according to Google's recommendation for IDs older than 12
  months.
- **Provider outage:** isolate failure in the Google adapter; network exploration and canal routing
  remain functional.
- **Key misuse:** retain website/API restrictions, conservative quotas, and billing alerts already
  required by the map prototype.

## Recommendation

### 1. OpenStreetMap — GO for the durable baseline

Build the nationwide attraction index from the same bulk OSM snapshot as the canal artifact. Keep
source identities and provenance, apply explicit visitor-attraction rules, and deduplicate before
display. Tighten the spike allowlist for production:

- retain museums, galleries, zoos, aquariums, named tourist attractions, and selected heritage sites;
- do not treat every `historic=*`, `tourism=artwork`, or `leisure=garden` record as independently
  recommendable;
- use names, websites, Wikidata/Wikipedia links, heritage designation, and feature scale as quality
  evidence, not an invented rating;
- preserve low-confidence records for diagnostics without placing them in the default map layer.

### 2. Google Places — GO for on-demand enrichment

Use the existing frontend Google boundary and map. Match or search only when a user inspects an
attraction, request the minimum field mask, and store only Place IDs. Initially request ratings,
rating counts, current hours, canonical Google link, and at most one photo. Omit reviews and AI or
editorial summaries from v1 because they add cost, attribution, display, and policy complexity.

Google popularity must not silently overwrite the offline catalog's ordering. Label Google-derived
ratings and freshness, preserve OSM-only results, and allow unmatched attractions.

### 3. Tripadvisor — NO-GO for v1

Do not build a Tripadvisor adapter now. It adds a second commercial identity/attribution system,
permits storage of only location IDs, caps nearby results at ten, hides exact overage pricing behind
checkout, and is announcing a replacement Terra platform. Revisit after Terra documentation and
pricing stabilize or if live Google samples show a material attraction-coverage gap.

### 4. Official heritage data — GO for a later supplemental experiment

Historic England is the first supplemental candidate because it is authoritative, downloadable,
and OGL-licensed. Test it as an enrichment/matching source for registered parks, scheduled monuments,
and major designated sites. Do not display all listed buildings. Add Cadw and Historic Environment
Scotland when the explorer expands beyond the current England artifact.

## Follow-up Issue Impact

- **#23 — attraction ingest:** implement the refined OSM taxonomy and source-quality evidence; leave
  a source-neutral seam for later Historic England enrichment.
- **#25 — network explorer:** require no commercial provider for national or viewport rendering.
- **#26 — discovery UI:** show OSM records first, separate Google fields visually, and support
  unmatched/unavailable states.
- **#28 — live enrichment:** use Google through the existing frontend SDK, minimal fields,
  user-triggered requests, Place-ID-only persistence, quotas, and mandatory attribution.
- **#24 — route integration:** query the offline index along route geometry; enrich only opened
  results rather than every route attraction.

## Compliance Check

- [x] No Google or Tripadvisor response content is committed.
- [x] Every commercial-provider claim links to first-party documentation.
- [x] OSM sample data includes query, timestamp, and attribution.
- [x] Live coverage is not claimed without credentials and captured evidence.
