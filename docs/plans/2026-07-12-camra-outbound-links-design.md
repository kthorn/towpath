# CAMRA Outbound Links Design

## Goal

Help a small group of Towpath users discover and verify pubs using CAMRA while
planning canal journeys. Towpath continues to use its OSM enrichment as the
source for pub markers. It does not scrape, fetch, import, cache, or republish
CAMRA data.

This design assumes the separate OSM enrichment work supplies pub amenities to
the route result and displays them as map markers. It covers only the CAMRA
handoff layered on those markers.

## Scope

After a canal route is planned, each named OSM pub marker offers a secondary
**Check on CAMRA** action. A small **CAMRA guides** map control also appears and
opens CAMRA's curated-guide browser.

Both actions are outbound references. CAMRA results do not appear inside
Towpath, and there is no CAMRA-backed import, correction, review flag, or local
editing workflow. Trip-summary integration is deferred.

The initial guide action always opens CAMRA's guide browser. Manually associating
guides with canal areas and automatically matching guides from place names are
future investigations, not MVP requirements.

## Pub Handoff Spike

Implementation starts with a time-boxed spike comparing two approaches:

1. Open CAMRA's pub finder and copy a concise search phrase such as
   `The Navigation, Oxford`.
2. Open a search-engine query constrained to CAMRA pub pages.

Test at least ten representative OSM pubs, including duplicate names, rural
pubs, punctuation, missing locality, and a pub apparently missing from CAMRA.
Score both options on result accuracy, required user actions, desktop and mobile
behavior, clipboard failure behavior, privacy, accessibility, and dependence on
undocumented URL formats.

Prefer the CAMRA-plus-copy approach unless the targeted search produces
materially better results. Record the evidence and decision in the
implementation notes. Do not retain both mechanisms as a user preference.

## Architecture and Data Flow

The feature lives entirely in the web client. It adds no CAMRA calls to the
Python API, route planner, OSM ingestion, or graph artifacts.

A small CAMRA-link module owns outbound behavior. It:

- returns stable CAMRA pub-finder and curated-guide URLs;
- normalizes a pub name and optional locality into human-readable search text;
- constructs the targeted search-engine URL used by the spike;
- exposes the selected handoff through one narrow interface; and
- never fetches CAMRA pages or transmits coordinates.

The map layer filters route amenities to pubs and uses existing OSM-derived
fields. Locality comes from the enriched amenity when available. If the amenity
contract does not expose locality, the query degrades to the pub name; this
feature does not add reverse geocoding.

The pub popover invokes the selected handoff on an explicit user action. The
route-level control uses the same module to open CAMRA's curated-guide browser.
External links open in a new tab with opener isolation. The guides control is
shown only while a successful canal route is displayed. Pub actions appear only
for named pub markers.

Towpath persists no CAMRA identifiers, results, cookies, HTML, or inferred
matches. Temporary interaction state may be used for feedback such as
**Search text copied**.

## Privacy and Attribution

The feature sends neither route geometry nor precise pub coordinates to CAMRA
or a search engine. Search option 2 transmits only the user-triggered textual
query, and its privacy trade-off must be considered in the spike. The UI clearly
labels CAMRA as an external service and must not imply that CAMRA endorses the
route or that a relevant curated guide exists.

OSM attribution remains attached to the pub data under the existing map and
data attribution behavior. CAMRA attribution applies only to the outbound link.

## Failure Handling

Clipboard failure must not block navigation. If copying fails, Towpath opens
CAMRA and displays the prepared phrase for manual copying. Popup blocking leaves
a normal navigable link available. Unnamed pubs remain eligible for map display
but do not receive a CAMRA lookup action.

CAMRA downtime, changed pages, or unavailable results must not affect route
planning or map rendering. The curated-guide control is a plain external link
and does not depend on clipboard or matching logic.

## Accessibility

Both actions are keyboard accessible, identify that they open an external site,
and have meaningful accessible names. Clipboard success and failure are
announced without stealing focus. Pub-marker popovers retain normal keyboard and
screen-reader navigation.

## Acceptance Criteria

- Named OSM pub markers expose **Check on CAMRA** after a route is planned.
- The route map exposes **CAMRA guides** only while a canal route is displayed.
- Neither action fetches, parses, or stores CAMRA content.
- The feature never transmits coordinates or route details.
- External links use safe new-tab behavior and remain usable when popups or the
  clipboard API are unavailable.
- Missing locality and punctuation are handled deterministically.
- CAMRA failures do not affect core route planning or map rendering.
- No CAMRA actions are added to the trip summary in the MVP.

## Verification

Unit tests cover search-text normalization, URL construction, missing locality,
punctuation, and the selected handoff. Component tests cover control visibility,
named and unnamed pubs, keyboard operation, safe external-link attributes, and
clipboard success and failure.

A browser-level test verifies both outbound actions by intercepting navigation;
the automated suite must not contact CAMRA or a search engine. The spike itself
is a manual, documented evaluation because it assesses live third-party search
quality.

## Deferred Exploration

- Add CAMRA actions to a future trip-summary pub list.
- Maintain a small editorial mapping from canal areas to known CAMRA guides.
- Match guides from route place names without fetching CAMRA content.
- Revisit direct CAMRA deep links if CAMRA publishes a supported search URL or
  integration interface.
