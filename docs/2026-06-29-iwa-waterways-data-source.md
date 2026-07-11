# IWA waterways.org.uk canal-map data source

**Date:** 2026-06-29
**Origin URL:** <https://waterways.org.uk/waterways/uk-canal-map>
**Status:** Research note / decision record — *not yet implemented*

## Where <https://waterways.org.uk/waterways/uk-canal-map> gets its data

The "Map view" tab is built with **Leaflet + Esri Leaflet**, configured by the
site's theme script at `wp-content/themes/salty/assets/js/map.js`. It does
**not** consume OpenStreetMap or a static GeoJSON file; it pulls the waterway
geometries live from **ArcGIS Online / ArcGIS REST FeatureServer layers** hosted
under the IWA's own ArcGIS Online account.

### Vector (waterway) layers — all from the same ArcGIS Online tenant

Each is an `L.esri.featureLayer` pointing at a FeatureServer under
`https://services5.arcgis.com/6RT5lRlaAg7aZTZi/arcgis/rest/services/`:

| Layer on screen | REST endpoint | Style |
|---|---|---|
| Current navigable waterways | `…/IWA_Current_Navigations_2020_Sept/FeatureServer/0/` | solid blue `#528da9` |
| Abandoned waterways | `…/IWA_Abandoned/FeatureServer/0/` | dashed red `#e51f2f` |
| Under restoration | `…/IWA_Restorations_Sept_2020/FeatureServer/0/` | dark `#253143` |
| New alignments | `…/IWA_New_Alignments/FeatureServer/0/` | green `#6bab6a` |

### Basemap

Esri basemaps via `L.esri.basemapLayer` — either `Topographic`, or `Gray` +
`GrayLabels` (branch in the script). Esri-hosted tiles, not IWA data.

### ArcGIS Online webmap

The script also holds a default
`webmapId = '03299b3a5b134705a462d167e2104376'`. Queried against ArcGIS Online:

- **Title:** "IWA Website Map"
- **Owner:** `mapeditor_iwa`
- **Visibility:** public

So the owning account is literally `mapeditor_iwa` — confirming the vector data
is **IWA's own curated GIS data**, published by the Inland Waterways Association
to their ArcGIS Online account. Layer names carry the date "Sept 2020",
suggesting the navigations/restorations data was last refreshed as a snapshot in
September 2020.

### Two other incidental data flows on the map

- **Click popups** (`showWaterwayPopup` in `map.js`): on click of a waterway,
  `$.get("/get_waterway/" + name)` fetches descriptive HTML from
  **waterways.org.uk's own WordPress backend** (`/get_waterway/...`), not ArcGIS.
- **Event/news markers** (clustered pins): come from `markers.push({...})`
  calls injected into the page HTML by WordPress/FacetWP, with `lat`/`lng`
  from the site's own event/news post metadata — not from ArcGIS.

### Bottom line on provenance

The underlying **canal/waterway network geometry** comes from **ArcGIS Online
FeatureServer layers owned by `mapeditor_iwa`** (the Inland Waterways
Association), at `https://services5.arcgis.com/6RT5lRlaAg7aZTZi/arcgis/rest/services/IWA_*`.
Basemap tiles are **Esri's** ("Topographic" / "Gray+GrayLabels"). Event marker
pins and click-through descriptions are served from waterways.org.uk's own
WordPress site.

There is **no visible attribution** on the map itself (the `copyrightText`
field on the feature layer is empty) — the legitimate provenance is IWA's own
database as published through ArcGIS Online.

## Should Pound use it? — decision record

**Recommendation:** use IWA **in addition to** OSM as a build-time
*validation/reference* layer, **not instead of** OSM as the routed graph.

### What the IWA data actually is

The four FeatureServer layers expose line geometry with, as far as the map
script reads, essentially one attribute: `Name`. There is:

- No `max_beam` / `max_length` / `max_draft` / `max_height`.
- No `lock_gate` nodes, no lock chamber ways, no movable-bridge tags, no tunnel
  flags.
- No shared-node topology between polylines (each waterway is an independent
  linestring; junctions are geometric near-misses, not shared node IDs).
- A dated snapshot — "Sept 2020" is in the layer names — behind a network
  service (fights Pound's "no network at request time, deterministic artifact"
  stance).

### Honest tradeoff

- **Steel-man for IWA-instead-of-OSM:** it is the subject-matter authority.
  "Current Navigations" *is* the authoritative answer to "is this canal
  actually navigable today," which in OSM must be inferred from
  `waterway=canal` + absence of `disused:yes` + usage tags. The
  abandoned/restoration/new-alignment split maps almost 1:1 onto routability and
  `filters.is_derelict`. A single curated dataset beats OSM's volunteer
  patchwork for *which lines are the network*.
- **Why it still loses as the primary:** Pound cannot *route* on named
  centrelines alone. No dimensions ⇒ every edge is unlimited. No lock/gate/
  bridge nodes ⇒ no lock-flight cost model. No shared topology ⇒ falls back to
  tolerance-snapping, which the design doc treats as a failure mode
  (`tolerance_snaps_unresolved`, manual `overrides.json`). And it is a 2020
  snapshot behind a network service, which fights Pound's "no network at
  request time, deterministic artifact" stance.
- **Steel-man for OSM alone:** richest attributes, real topology, continuously
  updated, clear ODbL licence, offline PBF. Its weakness is exactly where IWA
  is strong — authoritative routability classification and clean
  abandoned/restoration boundaries.

So they are complementary, not substitutes. OSM is the right primary; IWA is
the right authority check.

### Where IWA data is genuinely valuable in Pound

1. **Routability validation at build time.** Diff OSM ways classified routable
   against the IWA current/abandoned sets. OSM canal inside IWA-abandoned ⇒
   routing over a dead canal; OSM canal *outside* IWA-current ⇒ IWA thinks it
   not navigable (or OSM is missing `disused:yes`). Fits the existing
   advisories pattern (`edges_missing_dims`, `ambiguous_place_names`) — add
   `iwa_classification_conflicts` as a reported-but-never-fails advisory.
2. **Abandoned/restoration classification** as a second opinion on
   `filters.is_derelict`.
3. **Gazetteer / canonical names.** IWA "Oxford Canal (Southern)" naming is a
   clean seed for `gazetteer.py` canonical place names, and the
   `/get_waterway/<name>` endpoint is already a name→waterway lookup that could
   be mirrored.
4. **OSM-gap detection.** IWA current line with no OSM way over it = an OSM
   data-improvement opportunity to feed back upstream, **not** geometry to
   silently substitute into the routed graph.

### Licence flag worth acting on

The AGO item's `licenseInfo` and the layer's `copyrightText` are both **empty**.
Anonymous querying at build time for private validation is almost certainly
fine — it is a public map service. But **bundling** IWA geometry into a
published Pound artefact, or redistributing it, needs written permission. IWA
is a waterways charity; an email to their office is plausibly trivial to get
reuse terms, and might secure the source shapefiles and refresh cadence too.
Do **not** silently mix IWA geometry into an ODbL artefact — licence-mixing
trap.

## How to fetch the IWA data

The FeatureServer is public and anonymous (no token). Three options, easiest
first:

### `esridump` (recommend for a one-shot snapshot committed deterministically)

```bash
pip install esridump
esridump --json \
  "https://services5.arcgis.com/6RT5lRlaAg7aZTZi/arcgis/rest/services/IWA_Current_Navigations_2020_Sept/FeatureServer/0/" \
  > iwa_current.jsonl
```

Handles pagination and `objectId` chunking automatically.

### Direct REST query (thin reader — mirrors `pound/ingest/overpass.py`)

```
…/FeatureServer/0/query?where=1%3D1&outFields=Name&f=geojson&resultRecordCount=2000&resultOffset=0
```

Page via `resultOffset` until fewer than `resultRecordCount` come back.
`f=geojson` returns GeoJSON LineStrings directly.

### `arcgis` Python lib

Overkill; needs the ArcGIS API for Python and an account for some calls.
Avoid for this.

### Slotting into the IR

Add `pound/ingest/iwa.py` alongside `overpass.py`, producing a
`WaterwayFeatures` with:

- `source="iwa_arcgis"`
- geometry as `(lat, lon)` tuples
- `node_ids=[]` (same limitation as Overpass `out geom` — confirms it is a
  scaffolding/validation source, not a bulk replacement)
- `kind` mapping: current → `canal` (they do not distinguish canal vs river, so
  a name heuristic or default-to-canal is needed); abandoned → drop-but-record
  for the diff; restoration/new → record as advisory.

Treat IWA as a **build-time-only validation input** that produces advisories,
never edges in the routed graph — keeping OSM the single source of truth for the
topology Pound actually routes on.

## Proposed implementation (TDD)

1. `pound/ingest/iwa.py` — REST fetcher + IR adapter, with a committed
   fixture (mirrors the Overpass reader's unit-tested `parse()` against a
   committed fixture; `fetch_*` network use behind `--run-network`).
2. Build-time advisory `iwa_classification_conflicts` in `pound/graph/build.py`
   (or `pound/validate/`): reported-but-never-fails, joining OSM ways to IWA
   current/abandoned/restoration sets by geometry intersection + name match.
3. Optional: IWA names as gazetteer seed in `pound/graph/gazetteer.py`.

Net effect: OSM stays the routed-graph source of truth; IWA becomes a
deterministic, committed-snapshot authority check that surfaces mismatches the
build already cares about.
