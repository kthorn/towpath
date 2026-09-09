# Direct Copernicus UK temperature acquisition

The existing UK grid needs 25 complete seasonal years at 3,030 locations. Direct
Copernicus ERA5-Land geo-chunked temperature data avoids tens of thousands of
per-location annual Open-Meteo requests. Access uses the user's configured CDS
credential; dataset terms must be accepted by the user.

An offline importer reads only 2 m temperature from the official Zarr store in
bounded spatial tiles. Raw chunks are cached without credentials for interrupted
runs. Annual daily caches retain requested and provider coordinates and source
identity. The current SQLite builder and map API remain the delivery format.

Daily extrema are computed from all 24 hourly samples for each Europe/London
summer calendar day, after Kelvin-to-Celsius conversion. Incomplete days remain
unavailable. These are extrema of hourly model samples, not station observations.
Direct values are not elevation-downscaled by Open-Meteo; source attribution must
make that distinction clear, and the pilot comparison will quantify differences.
Coastal sampling must record the actual source coordinate and enforce a bounded
nearest-land search rather than silently substituting distant land temperatures.

The resulting artifact retains both 2001–2025 and 2021–2025 distributions. Existing
strict completeness, threshold and percentile rules apply. New data is built and
validated separately from the deployed pilot, with rollback metadata retained.

References: https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land?tab=analysis_ready_data
and https://cds.climate.copernicus.eu/how-to-api .


## Pilot and validation

The four-cell Oxford pilot produced all 100 annual caches. Comparison with the
existing Open-Meteo data matched 12,600 days per metric: median absolute difference
0.0586°C for highs and 0.0581°C for lows, with maximum absolute differences below
0.275°C. This comparison checks day alignment and confirms that the direct model
values are close; it does not establish equivalence for other terrain or locations.

The importer verifies source URL and metadata SHA at run boundaries. This is a
metadata fingerprint, not proof of immutable remote chunk contents. Raw caches
must be retained for reproducibility; artifact content revisions capture changes
in the derived daily distributions. Metadata and data writes are atomic. Missing
HTTP 404 chunks are cached as missing, while authentication failures never become
missing data. The service was observed returning transient licence errors after
acceptance; bounded retries repeat the authenticated request and stop on persistent
errors. Keys are excluded from URLs, logs, cache identities, and raised messages.

Tests cover local-day boundaries, nonconstant multi-year indexing, completeness,
finite missing sentinels, masks, no input mutation, bounded coastal selection,
metadata changes, real compressed Zarr cache reuse, transient/persistent provider
errors, annual cache interoperability, and a strictly offline CLI artifact build.

The source archive appended 24 hours during nationwide acquisition. The importer
permits only array-length growth with every other metadata field unchanged. It
compares the requested historical prefix of every affected cached time/temperature
chunk, including cached missing chunks, against the source before retaining the
original snapshot identity. The real acquisition verified 218 affected chunks
through 2025-09-03 22:00 UTC with no historical changes. The comparison report and
both metadata fingerprints are retained alongside the raw cache.

## Nationwide result

The 2001–2025 acquisition produced 75,750 annual caches for all 3,030 UK grid
cells. Artifact `aac9dc8be23ef596` contains 218,160 validated distributions:
213,192 available and 4,968 explicitly unavailable. All 2,961 populated cells have
complete 5- and 25-year distributions across all 18 weeks and both metrics; 69
coastal/island cells have no eligible land point within 15 km. The SQLite artifact
is 888,909,824 bytes. All five surface views were checked for both periods; local
query times were 47–101 ms. Generated artifacts and source caches are not committed.

Verification: 1,072 Python tests passed (38 optional tests skipped), including 17
CDS regressions; repository Ruff and whitespace checks passed. The existing runtime
and frontend consume the unchanged artifact/API schema.
