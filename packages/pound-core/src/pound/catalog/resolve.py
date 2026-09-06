"""Bounded name resolution over the existing catalog, without network access."""

from collections import defaultdict

from pound.catalog.models import CatalogPlace
from pound.schemas import PlaceResolution, ResolvedPlaceOption, ResolvePlaceRequest

GB_BOUNDS = {"south": 49.8, "west": -8.7, "north": 60.9, "east": 2.0}


def in_scope(lat: float, lon: float) -> bool:
    return (
        GB_BOUNDS["south"] <= lat <= GB_BOUNDS["north"]
        and GB_BOUNDS["west"] <= lon <= GB_BOUNDS["east"]
    )


def normalize(value: str) -> str:
    return " ".join(value.casefold().split())


class PlaceNameIndex:
    """Derived exact-name and trigram postings; values reference catalog records."""

    def __init__(self, places: tuple[CatalogPlace, ...], revision: str) -> None:
        self.places = tuple(sorted(places, key=lambda p: (p.osm_type.value, p.osm_id, p.kind)))
        self.revision = revision
        self.exact: dict[str, list[int]] = defaultdict(list)
        self.grams: dict[str, list[int]] = defaultdict(list)
        self.names: list[tuple[str, ...]] = []
        for i, place in enumerate(self.places):
            names = tuple(
                sorted(
                    {
                        normalize(name)
                        for name in [place.name or "", *(place.metadata.alt_name or "").split(";")]
                        if name.strip()
                    }
                )
            )
            self.names.append(names)
            for name in names:
                self.exact[name].append(i)
            for gram in {name[j : j + 3] for name in names for j in range(len(name) - 2)}:
                self.grams[gram].append(i)


def resolve_place(
    request: ResolvePlaceRequest, *, index: PlaceNameIndex | None, max_work: int = 100_000
) -> PlaceResolution:
    """Resolve one bounded catalog query; incomplete searches never prove uniqueness."""
    if index is None:
        return PlaceResolution(status="unavailable", reason="catalog_unavailable")
    query = normalize(request.query)
    exact = query in index.exact
    if exact:
        positions = index.exact[query]
    elif len(query) >= 3:
        postings = [index.grams.get(query[j : j + 3], []) for j in range(len(query) - 2)]
        positions = min(postings, key=len)
    else:
        positions = range(len(index.places))
    options = []
    identities = set()
    work = 0
    for position in positions:
        if work >= max_work:
            return PlaceResolution(
                status="incomplete", reason="work_limit", options=options, work_used=work
            )
        work += 1
        place = index.places[position]
        if place.kind not in request.kinds or not in_scope(place.lat, place.lon):
            continue
        if not any(query in name for name in index.names[position]):
            continue
        identity = f"osm:{place.osm_type.value}:{place.osm_id}"
        if identity in identities:
            continue
        identities.add(identity)
        if len(options) == 5:
            return PlaceResolution(
                status="incomplete", reason="result_limit", options=options, work_used=work
            )
        address = place.metadata.address
        options.append(
            ResolvedPlaceOption(
                option_ref=identity,
                source_id=identity,
                name=place.name or query,
                coordinate={"lat": place.lat, "lon": place.lon},
                locality=(address.city or address.place) if address else None,
                catalog_revision=index.revision,
            )
        )
    status = "resolved" if exact and len(options) == 1 else "ambiguous"
    reason = "exact" if status == "resolved" else "selection_required"
    if not options:
        status, reason = "not_found", "no_match"
    return PlaceResolution(status=status, reason=reason, options=options, work_used=work)
