# Boat-hire candidate review tool

## Status

Approved design for a one-time, local review workflow.

## Goal

Produce a ranked JSON file of OSM places that may offer canal or boat vacation
hire, then provide a small local Flask application for a human to inspect each
company's website and classify it.

The review labels are `vacation_hire`, `not_vacation_hire`, and `uncertain`.
An unreviewed record has a null decision and is not itself a review label.

## Candidate extraction

The extractor reads `pound/artifacts/england-catalog.pkl` rather than the
routing artifact. The catalog retains normalized metadata and website links.
It emits:

- every named `marina` and `mooring` record;
- named `landmark` records whose name, operator, or description has a
  boat-related signal such as `boat`, `boatyard`, `narrowboat`, `cruiser`,
  `cruising`, `boat trip`, or `hire`.

Each JSON record contains the stable OSM identity, kind, name, coordinates,
address/contact metadata, operator, description, all normalized links, source
OSM URL, a deterministic likelihood score, rank, and human-readable ranking
reasons. Existing decisions are retained when a review file is regenerated.

The generator does not fetch websites. Ranking is based only on catalog data,
so generation is deterministic and offline. The review page supplies the
human website check.

## Review JSON

The top level stores a format version, source artifact/revision, generation
metadata, and a list of records. Each record stores:

- source identity and normalized catalog data;
- `website_urls` and the OSM URL;
- `likelihood_score`, `rank`, and `likelihood_reasons`;
- `decision`: `null`, `vacation_hire`, `not_vacation_hire`, or `uncertain`;
- a review timestamp when a decision is saved.

The JSON file is the only persistence layer; no database is needed for this
one-time local review.

## Flask reviewer

The standalone app binds to `127.0.0.1` and accepts a path to the JSON file.
The page has two panes:

- a left website iframe; when a site refuses framing, the pane provides an
  explicit new-tab fallback; if there is no website, it shows the OSM link;
- a right metadata pane with the place details, all links, likelihood score,
  ranking reasons, progress, filters, and the three decision buttons.

The app supports previous/next navigation and filters for unreviewed and each
review decision. Selecting a decision writes immediately and advances to the
next unreviewed record. Existing decisions survive restarts.

Writes use a temporary file followed by an atomic rename. Missing or malformed
input is reported as an error; the app never silently recreates review data.

## Verification

Tests will cover candidate inclusion and deterministic ranking, JSON round-trip
and preservation of decisions, atomic decision updates, filtering/navigation,
and the main Flask routes.
