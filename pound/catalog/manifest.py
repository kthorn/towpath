"""The measured, bounded taxonomy and metadata surface for the place catalog."""

# Stable kinds are grouped by hospitality, provisions, canal services, and
# visitor attractions.  Unknown OSM values are never promoted automatically.
CATALOG_KINDS: frozenset[str] = frozenset(
    {
        "pub",
        "cafe",
        "restaurant",
        "supermarket",
        "convenience",
        "bakery",
        "greengrocer",
        "butcher",
        "deli",
        "general",
        "marina",
        "mooring",
        "fuel",
        "water_point",
        "sanitary_disposal",
        "museum",
        "gallery",
        "historic_site",
        "garden",
        "wildlife_attraction",
        "landmark",
    }
)

# Raw OSM keys eligible for normalization in the catalog.  ``osm_url`` is a
# derived provenance field; it is listed here so later metadata code has one
# checked-in allowlist for the complete public surface.
CATALOG_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "name",
        "alt_name",
        "brand",
        "operator",
        "addr:housenumber",
        "addr:street",
        "addr:place",
        "addr:city",
        "addr:postcode",
        "opening_hours",
        "access",
        "fee",
        "wheelchair",
        "phone",
        "contact:phone",
        "email",
        "contact:email",
        "description",
        "website",
        "contact:website",
        "wikidata",
        "wikipedia",
        "osm_url",
    }
)

MAX_CATALOG_KINDS = 16
MAX_CATALOG_RADIUS_M = 2_000.0
