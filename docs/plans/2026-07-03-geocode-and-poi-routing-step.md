# Geocoding + POI search — next routing step

> **Status:** design / planning draft  
> **Builds on:** `pound/route/resolve.py` (offline gazetteer), noded graph build, and `pound/route/plan.py` point-to-point routing.  
> **Triggering request:** *"find me marinas with narrowboat rentals near Milton Keynes"*

## 1. What the request actually needs

The current engine turns *place-name → graph node → route*. The new request is different:

1. **Geocode** a free-text place (`Milton Keynes`) to a lat/lon.
2. **Snap** that lat/lon to the canal network (nearest graph node) so results are canal-reachable.
3. **Search** for amenities of a given kind (`marina`) plus a tag filter (`narrowboat rentals`) within a radius of the geocoded point.
4. **Rank** results by straight-line distance from the point (and optionally by canal-network distance if we later route to each one).

This is a **location-based POI query**, not a route. The routing engine supplies the canal network; the new layer supplies geocoding and amenity indexing.

## 2. High-level approach

Keep the existing pure routing core untouched. Add two request-time capabilities beside it:

```
free-text place  ──►  GeocodeResolver  ──►  lat/lon
                                              │
                                              ▼
                        CanalNetwork.snap(lat, lon)  ──►  nearest graph node
                                              │
                                              ▼
                        AmenityIndex.nearby(lat, lon, kind, filters)
                                              │
                                              ▼
                                   list[Amenity] ranked by distance
```

Optionally, each result can be handed to `plan_route` for a route from the snapped canal node to the marina’s nearest canal node.

## 3. Design options considered

| Approach | Pros | Cons | Verdict |
|---|---|---|---|
| **A. Online geocoder at request time** (Nominatim / Google) | Understands free text; no build-time gazetteer bloat; matches the user’s suggestion. | Requires network; rate limits / API keys; attribution/licensing needs care. | **Recommended for the query path.** Keep the offline gazetteer as a fallback for routing-only calls. |
| **B. Offline-only gazetteer** (expand PR2’s `graph.graph["gazetteer"]` to cover towns) | Keeps the engine network-free; fast. | `place=*` nodes are sparse for towns/cities; “Milton Keynes” may not resolve, and generic queries (“near Birmingham”) fail silently. | Keep as fallback, not primary. |
| **C. Bulk geocode at build time** | Request-time pure; can cache Nominatim results. | Build becomes slow and network-dependent; violates the offline-build principle. | Reject. |

Decision: **Option A for POI/natural-language queries**, with a clean seam so the offline resolver stays available for `pound-plan` style routing.

## 4. New tools / modules

### 4.1 `pound/route/geocode.py` — online geocoding resolver

A small resolver that translates a free-text place into `(lat, lon)`.

```python
class GeocodeResolver(Protocol):
    def resolve(self, name: str) -> tuple[float, float]: ...

class NominatimResolver:
    """OSM Nominatim. Free, ODbL, requires User-Agent and rate limiting."""

class GoogleMapsResolver:
    """Google Maps Geocoding API. Requires GOOGLE_MAPS_API_KEY."""
```

Details:
- Use `requests` (already a project dependency for ingest).
- Default to **Google Maps Geocoding API** (user decision); it is faster and has higher quota, but requires `GOOGLE_MAPS_API_KEY`.
- Ship `NominatimResolver` as a keyed alternative for users who prefer a free/OSM-native provider.
- Add a simple on-disk or in-memory cache so repeated queries don’t hammer the service.
- Raise `ValueError` for no results / network failure with a user-actionable message.

### 4.2 `pound/route/network_snap.py` — snap lat/lon to the canal graph

```python
def snap_to_network(
    lat: float,
    lon: float,
    graph: nx.Graph,
    *,
    tolerance_m: float = 500.0,
) -> int:  # returns internal graph node uid
    ...
```

- Under the noded build, graph nodes have `lat`/`lon` attributes and internal uids.
- Linear nearest-node scan is acceptable: ~240 k nodes ≈ single-digit ms per call.
- If the nearest node is beyond `tolerance_m`, raise `ValueError("no canal within … of …")`.

### 4.3 `pound/amenities/index.py` + `pound/amenities/filters.py` — amenity search

Build an index at artifact-build time from OSM POI nodes/ways captured by the ingest filter.

Relevant OSM tags (verified against the OSM Wiki):
- Marinas: `leisure=marina`.
- Boat rental: `amenity=boat_rental`, or `rental=boat` on a shop/tourism feature.
- Narrowboat-specific tagging is not a single standard tag.
  - Primary filter: `amenity=boat_rental` / `rental=boat` plus name/description containing "narrowboat".
  - Enrichment: a small curated list of known narrowboat hire bases (Canal & River Trust listings or major hire companies), ingested as a build-time supplement. Licensing of any external list must be checked before bundling.

Index API:

```python
class AmenityIndex:
    def __init__(self, features: WaterwayFeatures): ...

    def nearby(
        self,
        lat: float,
        lon: float,
        *,
        kind: str | None = "marina",
        rental: str | None = None,          # e.g. "narrowboat", "boat"
        radius_m: float = 10_000.0,
        limit: int = 20,
    ) -> list[Amenity]:
        ...
```

- `Amenity` already exists in `pound/schemas.py`; extend it with an optional `rental: list[str] | None` field if needed.
- The index is embedded in the artifact (or rebuilt from the artifact graph on first use) so request-time search stays fast.

### 4.4 Schema additions

Add a query model and result model:

```python
class AmenityQuery(BaseModel):
    place: str
    kind: str = "marina"
    rental: str | None = None
    radius_m: float = 10_000.0
    limit: int = 20

class AmenityResult(BaseModel):
    place: str
    place_lat: float
    place_lon: float
    nearest_canal_node: int
    amenities: list[Amenity]
```

## 5. Build-time changes

The current `TAGS_FILTER_EXPR` keeps `n/leisure=marina` and `n/waterway=mooring`, but drops standalone `amenity=boat_rental` nodes and marina polygons (`w/leisure=marina`). For POI search we need to capture them.

Proposed ingest additions:
- Add `n/amenity=boat_rental` and `n/rental=boat` to the tags-filter node lines.
- Add `w/leisure=marina` (polygon) to the way lines; take its centroid as the POI location.
- Keep these POIs out of the routable graph but store them in `WaterwayFeatures.nodes` with `NodeKind` extensions (`BOAT_RENTAL`, etc.) so the amenity index can consume them.

## 6. CLI / agent surface

Add a thin CLI for manual testing:

```bash
pound-nearby "Milton Keynes" --kind marina --rental narrowboat --radius 10km
```

For the agent core, expose a single function:

```python
def find_amenities(query: AmenityQuery, *, graph: nx.Graph, geocoder: GeocodeResolver) -> AmenityResult:
    ...
```

## 7. Acceptance criteria

1. `find_amenities(AmenityQuery(place="Milton Keynes", kind="marina", rental="narrowboat"))` returns a ranked list of marinas.
2. Results include straight-line distance from the geocoded point and a `rental` note where tags support it.
3. If the geocoder is unavailable, the call raises a clear `ValueError` (no silent network fallbacks).
4. If no canal node is within `tolerance_m` of the geocoded point, raise a clear `ValueError`.
5. Unit tests use a stub geocoder and a small fixture graph; no real network in CI.

## 8. Open questions

1. **Geocoding provider:** Default to Nominatim, or do you want Google Maps as the primary? Nominatim is free/ODbL but has a 1 req/s policy; Google needs an API key but is faster/higher quota.
2. **Radius default:** Is 10 km sensible for "near Milton Keynes"? Should it be configurable per query?
3. **Narrowboat rental filter:** Resolved — use the OSM heuristic plus a build-time curated hire-base supplement.
