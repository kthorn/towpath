# Canal Network Explorer and Visitor Attractions

## Goal

Add a shared discovery experience that lets users browse the whole canal network,
explore visitor attractions within 2 km of a canal, and reuse the same POI catalog
while planning or reviewing a route.

The initial attraction scope is museums, historic sites, galleries, gardens,
wildlife attractions, notable landmarks, and similar visitor destinations.
Hospitality remains in the broader amenity work tracked separately.

## Product Surfaces

The application exposes two complementary surfaces over one POI system:

1. **Explore canals** displays the national network with zoom-dependent detail,
   clustered attractions, filters, and attraction details.
2. **Trip planning** displays attractions along a planned route and associates
   them with route legs or days.

An attraction selected in either surface can become a trip-planning input. The
explorer does not require a route to exist.

## Data Architecture

Use two data layers with different ownership and retention rules.

### Offline catalog

Build a durable catalog from sources whose licenses permit ingestion and
redistribution. Start with OpenStreetMap tourism and historic features, then
evaluate official tourism and heritage datasets in the provider spike. Normalize
source records into a provider-neutral attraction model, retain source provenance,
and spatially associate records with canal geometry within a 2 km corridor.

The catalog lives beside the graph artifact rather than inside the routable graph.
It supports nationwide rendering, category filters, clustering, and deterministic
route-corridor queries without paid API calls.

### Live enrichment

Query commercial providers only when the user inspects an area or attraction.
Current ratings, review counts, opening status, photos, and provider links remain
provider-owned fields. They must not be copied into the durable offline catalog
unless the provider terms explicitly allow it.

Google Places and Tripadvisor both generally prohibit caching or indexing their
content except for place/location identifiers. The implementation must store only
permitted identifiers and fetch restricted details on demand with required
attribution. Provider failure must leave the open-data attraction usable.

## Provider Spike

Before selecting adapters, compare at least Google Places, Tripadvisor Content API,
OSM, and plausible official UK tourism or heritage datasets. Use representative
urban, rural, high-density, and sparse canal areas. Measure:

- attraction coverage and category accuracy;
- usefulness of ratings and ranking signals;
- matching quality between open and commercial records;
- query limits, field-based pricing, and projected map-browsing cost;
- storage, caching, attribution, map-display, and privacy requirements;
- support for photos, opening status, accessibility, and canonical links;
- operational readiness, key availability, and provider roadmap risk.

Documentation research is mandatory. If credentials are available, add small live
samples; never scrape a consumer website. The spike produces a decision record,
sample results, cost envelope, and recommended fallback behavior rather than a
production ingestion pipeline.

## Map and Query Behavior

The whole network must not be emitted as one unbounded browser payload. Serve or
render network geometry and POIs progressively by viewport and zoom. At national
zoom, show simplified canal geometry and aggregate attraction clusters. Reveal
individual attractions and richer geometry only as the user zooms in.

The 2 km rule is a geometric candidate filter, not a claim of walkability. Detail
views should show straight-line canal proximity initially. A later access-routing
integration can calculate an actual walking route and distinguish attractions that
are physically close but inaccessible from the towpath.

## Failure and Compliance Boundaries

- The offline explorer remains useful without commercial credentials or network.
- Rate limiting, quota exhaustion, and provider errors degrade to open-data fields.
- Provider fields carry their own freshness and attribution metadata.
- Restricted provider content never enters distributed Pound artifacts.
- OSM and every added open dataset retain required attribution and provenance.
- Duplicate matching is explainable and does not silently merge uncertain records.

## Delivery Issues

1. Evaluate POI datasets and live enrichment providers.
2. Add a progressive whole-canal-network explorer.
3. Ingest and spatially index visitor attractions within 2 km of canals.
4. Add attraction discovery, filtering, clustering, and detail interactions.
5. Add compliant on-demand commercial POI enrichment.
6. Show attractions along planned routes and associate them with legs or days.

The offline index should share primitives with the existing general amenity issue,
but visitor-attraction scope and explorer delivery remain independently testable.
