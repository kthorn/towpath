"""Public places query limits and combined source contract constants."""

from pound.catalog.manifest import CATALOG_KINDS

PLACE_KINDS = CATALOG_KINDS | frozenset({"boat_hire"})
MAX_PLACES_RESULTS = 1_000
MAX_PLACES_QUERY_WORK = 100_000
MAX_PLACES_VIEWPORT_SPAN_DEGREES = 10.0
MAX_PLACES_TARGETS = 64
