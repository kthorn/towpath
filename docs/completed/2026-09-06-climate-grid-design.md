# UK historical temperature surface

## Intended behaviour

An optional translucent Google Maps overlay shows historical summer temperatures across
UK land on an approximately 10 km sampling grid. Coverage includes Northern Ireland and
constituent offshore islands; Crown Dependencies are outside the UK scope.

The default view is P90 daily high. Users can choose median daily high, P90 daily high,
median daily low, P10 daily low, or the historical fraction of daily highs strictly above
an adjustable Celsius threshold (default 30°C). All views support the existing 18 seven-day
summer windows and both 25-year and recent 5-year periods ending in the same complete year.

The historical fraction is `count(daily high > threshold) / n_days`. A day exactly at the
threshold is excluded. It is not a forecast, a probability for an entire trip, or a claim
that zero historical exceedances rules out future heat. P90 is an empirical percentile,
not a worst-case bound. Complete distributions contain 175 or 35 days, with correlated
observations within each summer. Existing strict completeness rules remain in force.

## Data and acquisition

Generate 10,000 m cells in EPSG:3035 from UK country land boundaries. Keep land-intersecting
coastal cells and select a point on the land intersection when the centre falls offshore.
This preserves small islands. Store requested and provider coordinates separately, including
provider elevation and weather and boundary attribution. Simplify the display mask with
topology preserved; generation uses the original land geometry.

The initial adapter reuses pinned ERA5-Land daily maxima/minima in Celsius and Europe/London
calendar days. Fetching is an explicit offline operation with a resumable cache and an
explicit weighted-call budget. Runtime code never calls a weather service. Threshold changes
reuse the same stored samples and need no extra acquisition.

The generated December 2024 ONS land grid contains 3,030 cells. Twenty-five seasonal
years require 75,750 annual requests, estimated at 681,750 weighted calls before retries.
The 10 km EPSG:3035 grid uses origin (4,321,000 m, 3,210,000 m); it is not aligned to
the EEA reference grid origin. Open-Meteo's free limits and historical
subscription requirements make unrestricted acquisition inappropriate. The implementation
must support bounded regional evaluation and resumable national acquisition. Full weather
population depends on available provider access and must not be represented as complete
merely because a national geometry was generated.

Authoritative references:

- [Open-Meteo historical API](https://open-meteo.com/en/docs/historical-weather-api)
- [Open-Meteo request limits and access plans](https://open-meteo.com/en/pricing)
- [ONS UK country boundaries, December 2024 BGC](https://www.data.gov.uk/dataset/c0ebe11c-0c81-4eed-81b3-a0394d4116a9/countries-december-2024-boundaries-uk-bgc1)
- [Copernicus ERA5-Land time series](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land-timeseries)

## Artifact and API

A separate SQLite artifact avoids extending the named-location artifact's 500-location limit
or loading every sample into the web process. Metadata records a content revision, complete
end year, weather source, boundary source, build time, spacing and WGS84 land mask. A cells
table holds requested/provider coordinates; distributions contain exactly 18 × 2 × 2 records
per cell, each using the existing validated empirical distribution contract.

The reader opens immutable read-only connections per query and detects file replacement;
updating the artifact requires an application restart. Missing or malformed grid artifacts
leave routing available. Query responses are bounded to 10,000 grid cells, with no samples
in surface responses. Detailed distributions load only when a location is inspected.

- `GET /api/climate/grid?week_id=8&period_years=25&view=high_p90`
- `GET /api/climate/grid?week_id=8&period_years=5&view=high_exceedance&threshold_c=30`
- `GET /api/climate/grid/cells/{id}?week_id=8`

A surface returns revision, source, week/period/view, threshold when relevant, unit, spacing,
land mask and `{id, coordinate, value, n_days}` for each cell. Missing values remain explicit
nulls. Detail returns both periods and metrics in the existing location-detail shape. ETags
include the revision and complete query, preserving threshold precision.

## Rendering and interaction

A custom Google `OverlayView` owns a noninteractive canvas. Normalized inverse-distance
interpolation uses a finite 15 km geographical cutoff. It interpolates temperature or
probability values before assigning colours; point overlap does not add temperature.
Original values are preserved at sample points, and regions owned by missing cells remain
transparent. A land mask clips the image, including holes and islands. Broad smoothing is
avoided because it could obscure local heat extremes.

Rendering work and backing-canvas resolution are bounded independently. Map pan/zoom redraws
are coalesced, changing opacity requires no fetch, and disabling/destroying the layer cleans
up the canvas and pending frames. Fixed temperature scales match the existing high/low
legends; exceedance uses a fixed 0–100% scale. The surface remains a visual interpolation,
not finer-resolution weather observations.

A searchable, paginated selector makes every sampled cell reachable. An explicit map-click
mode selects the nearest sample within 15 km, instead of changing route endpoints. Normal
origin/destination click modes remain available. Details show exact unsmoothed distributions
and, for threshold views, exceedance counts for both periods. City reference temperatures
remain independently available while the grid is optional.

Google references: [custom overlays](https://developers.google.com/maps/documentation/javascript/customoverlays)
and [image overlays](https://developers.google.com/maps/documentation/javascript/examples/maptype-image-overlay).
The deprecated heatmap layer is not used.

## Verification and rollout

Tests cover strict thresholds, missing cells, malformed metadata and distribution keys,
wrong timezones, file replacement, ETag precision, stale frontend responses, exact detail
counts, land-mask holes, interpolation, bounded rendering, cleanup and map integration.
A regional real-data pilot must check acquisition volume, artifact size, API latency and
visual appearance before national weather acquisition. Synthetic test fixtures are never
presented as acquired weather.

Deployment includes only generated `artifacts/climate-grid.sqlite`, not raw caches or source
boundaries. `POUND_CLIMATE_GRID_PATH` opts the server into the grid; the named-location JSON
uses its existing separate setting. Docker includes both optional artifacts and validates
those present. Neither generated artifact is committed. This change is prepared for review;
production deployment is a separate operation.

## Implementation evidence (6 September 2026)

The four-cell Oxford-area pilot acquired 100 annual cache batches (2001–2025),
using 900 estimated weighted calls. Artifact revision `2560ff2bb9c26ca3` contains
288 complete distributions, occupies 2,584,576 bytes, and loads through the runtime
reader in approximately 218 ms locally. Median warm surface-query time was 0.31 ms
across 20 calls, excluding JSON serialization and transport. The full UK coastline
dominates the approximately 2.42 MB uncompressed pilot surface response; these pilot
measurements are not a national-scale benchmark.

The real ONS mask revealed a self-intersection after conversion back to WGS84; the
builder now repairs and validates topology in the final coordinate system. Browser
verification used actual Google Maps and pilot data: the canvas painted nontransparent
pixels, opacity changed without another request, exact cell detail and exceedance
counts loaded, disabling removed the canvas, and no page errors occurred.

Whole-UK geometry generation is complete, but national weather acquisition and
production deployment are not. No generated artifact or source cache is committed.

Final verification: 982 Python tests passed (38 optional bulk/network tests skipped);
315 frontend tests passed; Ruff, Svelte check (zero diagnostics), and frontend build passed.
