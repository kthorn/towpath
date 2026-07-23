# Google place-resolution spike

**Date:** 2026-07-22
**Scope:** transient comparison of Google Maps Search links with Places API
matching for the OSM place catalog.
**Decision:** ship a URL-only Google Maps Search link for the MVP. Do not add
Google Places content to the OSM catalog or its marker/info-window UI.

## Decision in one paragraph

The safe MVP is an external **Search on Google Maps** link generated from the
OSM name and address, or from the OSM name and coordinate when no locality is
available. It needs no Google API key, Places request, quota, response cache, or
Place Details call, and the universal URL is supported by desktop, Android, and
iOS. A Places API match/details flow is **blocked pending Google support/legal
review**: the current Google Maps Platform Terms and Places service-specific
terms prohibit using Places content with or near a non-Google map, expressly
including displaying Places content on a non-Google map. The OSM-only marker and
metadata behavior remains the fallback and the product behavior for this
release.

This spike did not modify Google adapters, add Place Details, persist Place IDs,
or create a bulk enrichment job.

## Sample and procedure

The sample deliberately covers the failure modes that make name matching unsafe.
The names and locality/coordinate values below are transient test inputs used to
exercise URL construction and the proposed matching decision; no provider
response, Place ID, rating, review, photo, or Google-derived field was retained.
The duplicate-name rows are separate OSM records, not an assertion that Google
has one canonical entity for either name.

| ID | Kind and representative input | Coverage case | Query used for URL | Generated universal URL | Link check |
| --- | --- | --- | --- | --- | --- |
| P01 | Pub — The Navigation, Oxford | Urban; duplicate name A | `The Navigation, Oxford` | <https://www.google.com/maps/search/?api=1&query=The+Navigation%2C+Oxford> | URL contract valid; provider result not inspected |
| P02 | Pub — The Navigation, Lapworth | Rural; duplicate name A | `The Navigation, Lapworth` | <https://www.google.com/maps/search/?api=1&query=The+Navigation%2C+Lapworth> | URL contract valid; provider result not inspected |
| P03 | Pub — The Red Lion, Cropredy | Rural; duplicate name B | `The Red Lion, Cropredy` | <https://www.google.com/maps/search/?api=1&query=The+Red+Lion%2C+Cropredy> | URL contract valid; provider result not inspected |
| P04 | Pub — The Red Lion, Bletchley | Urban; duplicate name B | `The Red Lion, Bletchley` | <https://www.google.com/maps/search/?api=1&query=The+Red+Lion%2C+Bletchley> | URL contract valid; provider result not inspected |
| P05 | Pub — The Dog & Duck | Rural; locality missing | `The Dog & Duck, 52.0800,-1.2400` | <https://www.google.com/maps/search/?api=1&query=The+Dog+%26+Duck%2C+52.0800%2C-1.2400> | URL contract valid; provider result not inspected |
| P06 | Pub — King's Head, Banbury | Punctuation/apostrophe | `King's Head, Banbury` | <https://www.google.com/maps/search/?api=1&query=King%27s+Head%2C+Banbury> | URL contract valid; provider result not inspected |
| P07 | Pub — Towpath Arms, Oxford | Website absent | `Towpath Arms, Oxford` | <https://www.google.com/maps/search/?api=1&query=Towpath+Arms%2C+Oxford> | URL contract valid; provider result not inspected |
| A01 | Attraction — Bletchley Park, Bletchley | Urban attraction | `Bletchley Park, Bletchley` | <https://www.google.com/maps/search/?api=1&query=Bletchley+Park%2C+Bletchley> | URL contract valid; provider result not inspected |
| A02 | Attraction — Canal Museum, Stoke Bruerne | Rural attraction | `Canal Museum, Stoke Bruerne` | <https://www.google.com/maps/search/?api=1&query=Canal+Museum%2C+Stoke+Bruerne> | URL contract valid; provider result not inspected |
| A03 | Attraction — National Waterways Museum, Ellesmere Port | Urban attraction; long name | `National Waterways Museum, Ellesmere Port` | <https://www.google.com/maps/search/?api=1&query=National+Waterways+Museum%2C+Ellesmere+Port> | URL contract valid; provider result not inspected |
| A04 | Attraction — St. John’s House, Warwick | Punctuation; attraction | `St. John’s House, Warwick` | <https://www.google.com/maps/search/?api=1&query=St.+John%E2%80%99s+House%2C+Warwick> | URL contract valid; provider result not inspected |
| A05 | Attraction — The Old Lockhouse Museum | Apparent no-match control; coordinate fallback | `The Old Lockhouse Museum, 52.2000,-1.2000` | <https://www.google.com/maps/search/?api=1&query=The+Old+Lockhouse+Museum%2C+52.2000%2C-1.2000> | URL contract valid; provider result not inspected |

### What was and was not live

The available spike credentials did not permit a Places API call. The safe
link portion therefore completed by constructing and validating all twelve
encoded URLs against the documented Maps URL contract. No request was made to a
consumer Google Maps page, no HTML was scraped, and no network result was
recorded. Consequently, “useful result” means **the URL is valid and delegates
search to Google Maps**, not that a provider result was manually ranked. A real
browser check may be run later by a human with the normal external-link flow;
its transient observations must be discarded after the check.

The following remains explicitly **unverified** for every row: Text Search or
Nearby Search candidates, confidence, ambiguity/no-match outcome as returned by
Google, website/address/phone from Place Details, and network latency. This is
preferable to inventing provider identities or committing response data.

Before any future permitted live call:

1. Select the OSM object by stable OSM identity and record only its public name,
   locality/address (if present), and coordinate. Never send user identity or
   other end-user PII.
2. Generate `https://www.google.com/maps/search/?api=1&query=...` with standard
   URL encoding. Use `name,address` when an address/locality exists; otherwise
   use `name,lat,lng`. Keep the URL below Google's 2,048-character limit.
3. If a credential and quota are expressly approved, call Text Search (New)
   server-side with the OSM name/locality as `textQuery` and the OSM coordinate
   as a circular `locationBias`. Nearby Search is not the primary matcher: it
   has no arbitrary business-name query and is capped at 20 results.
4. Require one conservative candidate before calling Details: normalized name
   agreement (case-folded Unicode, punctuation/whitespace normalized) and a
   candidate within **250 m** of the OSM coordinate. This is a Towpath spike
   gate, not a Google guarantee. A tie, a second plausible candidate, or a
   name/location disagreement is `ambiguous`; no candidate passing both checks
   is `no-match`. Neither state auto-publishes Google content.
5. Request an explicit field mask. For candidate checking, the smallest mask
   that supplies independent name/location evidence is
   `places.id,places.displayName,places.location` (a Text Search Pro-tier
   request). If a candidate is selected, the narrowly scoped Place Details mask
   is `id,displayName,formattedAddress,nationalPhoneNumber,websiteUri,googleMapsUri`.
   Never request `*`, ratings, reviews, photos, or unrelated fields. Details is
   a second billable method call and is not needed merely to build a definitive
   Maps link.
6. Record only transient timing, status, and a Towpath-derived decision in a
   local scratch buffer. Delete the buffer, response body, candidate names,
   addresses, coordinates, phone numbers, and any Place ID immediately after
   review unless a later approved design explicitly permits storing the Place
   ID. Do not write logs, fixtures, caches, artifacts, or screenshots to the
   repository.

## Findings

### URL, mobile, and execution surface

- The documented URL is `https://www.google.com/maps/search/?api=1&query=...`;
  `api=1` and `query` are required and values must be URL-encoded. The URL is
  limited to 2,048 characters.
- A Maps URL requires no API key and creates no Places API event. It opens the
  installed Google Maps app on Android/iOS, or a browser when the app is absent;
  desktop also uses a browser. No user-agent branch or platform-specific
  intent is needed for a search link.
- A future approved match may add
  `query_place_id={stored_id}` while retaining a human-readable `query` fallback;
  the Place ID then takes precedence. This is not implemented in the MVP.
- Coordinate-only search gives a pin but not a verified place identity. That is
  why the link remains a search action and is never presented as a confirmed
  OSM↔Google match.

### Matching and field masks

Text Search (New) returns candidates ordered by perceived relevance and accepts a
text query plus circular location bias. Bias can return results outside the
circle, latitude/longitude is not itself a supported text query, identical
requests are not guaranteed to return the same list, and Google provides no
OSM crosswalk, canonical confidence score, stable result order, or sanctioned
name/distance threshold. The 250 m gate above is therefore a deliberately
conservative experiment, followed by user confirmation for any future ambiguous
case.

Search, Nearby Search, and Place Details require a field mask; omitting it is an
error and the highest requested field tier controls billing. Search masks are
rooted at `places.*`; Details masks are not. `places.id` is an ID-only matching
mask but cannot independently validate name or coordinate. Asking for
`places.displayName` or `places.location` raises the search to Pro. In Details,
`location` is Essentials, `displayName`/`googleMapsUri` are Pro, and website,
phone, and similar fields are Enterprise. A Search + Details chain must not be
used unless Details fields are actually displayed.

### Billing, quotas, and latency

The URL-only MVP makes zero Places API calls, consumes zero Places quota, and
has no Places SKU charge. Browser Maps JavaScript, endpoint autocomplete, and
Routes requests are separate product surfaces and must retain their own
restricted key, quotas, budgets, and monitoring.

If a future API experiment is approved, billing must be enabled and requests
must be authenticated. The research snapshot records these current global list
prices after the applicable monthly free cap: Text Search IDs Only and Place
Details IDs Only are no-cost; Text Search Pro and Nearby Search Pro are $32 per
1,000 events after 5,000 free; Place Details Essentials is $5 per 1,000 after
10,000 free; Place Details Pro is $17 per 1,000 after 5,000 free. Prices vary
by region and may change. Quotas are per method and project; there is no one
universal published numeric limit, so inspect Cloud Console quotas and add
budgets/alerts before testing.

No external API latency was measured in this spike because no API call was made.
A future run must report request latency separately for Text Search and Details,
including failures and throttling, then discard response data.

### Terms, attribution, privacy, and storage

- Google Maps Platform Terms §3.2.3(e) prohibit using Google Maps Core Services
  “with or near a non-Google Map”; the listed example includes displaying Places
  content on a non-Google map. Places service-specific terms §14.2 independently
  prohibit using Places content in conjunction with a non-Google map. This is the
  blocker for any Google name, address, phone, coordinate, hours, rating, review,
  photo, or website shown beside Towpath's OSM map. Pixel, panel, and modal
  separation is not defined by the public text; obtain Google support/counsel
  confirmation before implementing it.
- If API content is ever shown on an allowed Google surface, the same visual
  container needs Google Maps logo/text attribution, any third-party attributions,
  and (for photos/reviews) author attribution and direct source access. Ranking
  disclosure is recommended. Attribution cannot cure the non-Google-map
  prohibition.
- A Customer Application must notify users about Google Maps features/content,
  link the Google Maps End User Additional Terms and Google Privacy Policy, and
  follow applicable cookie/consent law. Google receives search terms, IP
  addresses, and coordinates. Send only public OSM POI text/coordinates in a
  future server-side experiment; never send user identity or other PII.
- Place IDs are the only long-lived Places value expressly identified as safe to
  retain. They may be stored indefinitely but can change, should be refreshed
  after 12 months, and can become `NOT_FOUND` or `INVALID_REQUEST`; one place may
  have multiple IDs. Other Places content is not a catalog cache: scraping,
  pre-fetching, indexing, bulk downloading, copying/saving business names or
  addresses, and caching are restricted; Places latitude/longitude caching is
  limited to 30 consecutive days. This spike stores none of it and performs no
  bulk or background enrichment.

## Product decision and follow-up boundary

| Option | Decision | Reason |
| --- | --- | --- |
| Generated Search on Google Maps link | **Ship for MVP** | No key or Places billing; universal mobile behavior; no provider data enters the OSM catalog; useful even when locality is missing through the coordinate fallback. |
| On-demand matched details | **Blocked** | Requires legal/support review of Places content with/near the OSM map, a server-side key, strict masks, quotas/budgets, conservative matching, attribution, privacy notice, and explicit user confirmation. No live credentials were available for this spike. |
| Defer all Google interaction | **Not selected** | The URL-only action provides user value without taking on Places enrichment risk. |

Until the blocker is resolved, catalog markers show only normalized OSM fields
and the external link label **Search on Google Maps**. There is no Place Details
button, no Google-derived marker metadata, no Place ID persistence, and no
Google response fallback. If the external link is unavailable, the marker still
uses the OSM-only behavior.

## Sources

- [Google Maps URLs — Get Started](https://developers.google.com/maps/documentation/urls/get-started)
  — URL syntax, encoding, length, Place ID query, and device behavior.
- [Text Search (New)](https://developers.google.com/maps/documentation/places/web-service/text-search)
  — text query, location bias, consistency, field masks, and candidate fields.
- [Nearby Search (New)](https://developers.google.com/maps/documentation/places/web-service/nearby-search)
  — circle/type constraints, ranking, result cap, and billing tier.
- [Place Details (New)](https://developers.google.com/maps/documentation/places/web-service/place-details)
  — field masks and details lookup.
- [Choose fields](https://developers.google.com/maps/documentation/places/web-service/choose-fields)
  — mandatory masks and SKU tiers.
- [Place IDs](https://developers.google.com/maps/documentation/places/web-service/place-id)
  — storage, refresh, and obsolescence.
- [Places policies](https://developers.google.com/maps/documentation/places/web-service/policies)
  — caching, attribution, and display duties.
- [Usage and billing](https://developers.google.com/maps/documentation/places/web-service/usage-and-billing)
  and [pricing](https://developers.google.com/maps/billing-and-pricing/pricing#places-pricing)
  — quota and price model.
- [Google Maps Platform Terms](https://cloud.google.com/maps-platform/terms#3.-license)
  and [Service Specific Terms §14](https://cloud.google.com/maps-platform/terms/maps-service-terms)
  — non-Google-map, storage, attribution, and privacy restrictions.
- [API security best practices](https://developers.google.com/maps/api-security-best-practices)
  — restricted keys and server/client execution guidance.

## Spike limitations

This is a documentation spike, not approval for a Google integration. The
following need a separately authorized run or counsel decision: live candidate
quality and latency, project-specific quotas, billing-account/EEA terms, whether
match audit metadata may be retained, the exact legal meaning of “with or near,”
and any future use of a stored Place ID. Recheck mutable prices and terms before
relying on them.
