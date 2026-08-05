"""Deterministic boat-hire candidate extraction and ranking."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

from pound.catalog.artifact import CatalogArtifact
from pound.catalog.models import CatalogPlace
from pound.graph.spatial import GraphSpatialIndex
from pound.review.models import ReviewDocument, ReviewLink, ReviewRecord

_CANDIDATE_SIGNAL = re.compile(
    r"\b(?:boats?|boatyards?|narrowboats?|cruisers?|cruising|boating|"
    r"(?:canal|boat)\s+trips?|canal\s+boat|self[ -]?drive|hire|rental|"
    r"charter|launch\s+hire)\b"
)
_POSITIVE_RULES = (
    ("strong", re.compile(r"\b(?:boat|narrowboat)\s+(?:hire|rental)\b"), 12),
    ("strong", re.compile(r"\bcanal\s+boat\b"), 12),
    ("strong", re.compile(r"\bself[ -]?drive\b"), 12),
    ("strong", re.compile(r"\b(?:boating|cruising)\s+holidays?\b"), 12),
    ("medium", re.compile(r"\bnarrowboats?\b"), 6),
    (
        "medium",
        re.compile(r"\bcruisers?|cruising|(?:canal|boat)\s+trips?|charter|launch\s+hire\b"),
        6,
    ),
    ("weak", re.compile(r"\bboats?|boatyard\b"), 2),
)
_NEGATIVE_RULES = (
    ("negative", re.compile(r"\bclubs?|associations?|societies?\b"), -6),
    (
        "negative",
        re.compile(r"\bresidential|private|dry\s+dock|fuel|repairs?|marine\s+services\b"),
        -6,
    ),
    ("negative", re.compile(r"\b(?:boat|canal)\s+trips?\b"), -6),
    ("negative", re.compile(r"\bkayak\b"), -12),
    ("negative", re.compile(r"\b(?:charter\s+boat|launch\s+hire)\b"), -6),
    (
        "negative",
        re.compile(r"\b(?:project|carving|memorial|bench|office|stone|welcome\s+post)\b"),
        -12,
    ),
)
_FIELD_WEIGHTS = (
    ("name", 5),
    ("operator", 3),
    ("brand", 3),
    ("alt_name", 3),
    ("description", 2),
    ("website", 1),
)
_KIND_PRIORS = {"marina": 0, "mooring": 2, "landmark": 0}


def _normalized(value: str) -> str:
    return re.sub(r"[^0-9a-z]+", " ", value.casefold())


def is_candidate(place: CatalogPlace) -> bool:
    """Return whether a named catalog place belongs in the review document."""
    if not place.name or not place.name.strip():
        return False
    if place.kind in {"marina", "mooring"}:
        return True
    if place.kind != "landmark":
        return False
    searchable = " ".join(
        value
        for value in (place.name, place.metadata.operator, place.metadata.description)
        if value
    ).casefold()
    return _CANDIDATE_SIGNAL.search(searchable) is not None


def _website_search_text(place: CatalogPlace) -> str:
    return " ".join(
        f"{urlsplit(link.url).netloc} {urlsplit(link.url).path}"
        for link in place.metadata.links
        if link.label == "Website"
    )


def score_place(place: CatalogPlace) -> tuple[int, list[str]]:
    """Return a clamped explainable likelihood score for one catalog place."""
    score = _KIND_PRIORS.get(place.kind, 0)
    reasons = [f"kind prior {place.kind} (+{score})"] if score else []
    values = {
        "name": place.name or "",
        "operator": place.metadata.operator or "",
        "brand": place.metadata.brand or "",
        "alt_name": place.metadata.alt_name or "",
        "description": place.metadata.description or "",
        "website": _website_search_text(place),
    }
    for field, field_weight in _FIELD_WEIGHTS:
        value = _normalized(values[field])
        for strength, pattern, rule_weight in (*_POSITIVE_RULES, *_NEGATIVE_RULES):
            match = pattern.search(value)
            if match is None:
                continue
            contribution = field_weight * rule_weight
            score += contribution
            reasons.append(
                f"{field} {strength} rule matched {match.group(0)!r} ({contribution:+d})"
            )
    return max(0, min(100, score)), reasons


def _record_for(place: CatalogPlace, score: int, reasons: list[str], rank: int) -> ReviewRecord:
    links = [ReviewLink(label=link.label, url=link.url) for link in place.metadata.links]
    metadata = place.metadata.model_dump(mode="json")
    metadata["links"] = [{"label": link.label, "url": link.url} for link in place.metadata.links]
    osm_url = next((link.url for link in place.metadata.links if link.label == "OpenStreetMap"), "")
    return ReviewRecord(
        identity=f"{place.osm_type.value}/{place.osm_id}/{place.kind}",
        osm_type=place.osm_type.value,
        osm_id=place.osm_id,
        kind=place.kind,
        name=place.name or "",
        lat=place.lat,
        lon=place.lon,
        metadata=metadata,
        links=links,
        website_urls=[link.url for link in place.metadata.links if link.label == "Website"],
        osm_url=osm_url,
        likelihood_score=score,
        rank=rank,
        likelihood_reasons=reasons,
        decision=None,
        reviewed_at=None,
    )


NETWORK_RADIUS_M = 250.0


def filter_catalog_to_network(
    catalog: CatalogArtifact,
    network_index: GraphSpatialIndex,
    *,
    radius_m: float = NETWORK_RADIUS_M,
) -> CatalogArtifact:
    """Return only catalog geometries within radius_m of a routable graph edge."""
    if not math.isfinite(radius_m) or radius_m < 0:
        raise ValueError("radius_m must be finite and non-negative")
    retained = tuple(
        place
        for place in catalog.places
        if (distance := network_index.distance_to_waterway(place.geometry_wkb)) is not None
        and distance <= radius_m
    )
    return CatalogArtifact(places=retained, metadata=catalog.metadata)


def build_document(
    catalog: CatalogArtifact,
    previous: ReviewDocument | None = None,
    *,
    generated_at: str | None = None,
    source_artifact: str = "",
) -> ReviewDocument:
    """Extract, rank, and serialize candidates from a normalized catalog."""
    ranked = sorted(
        ((place, *score_place(place)) for place in catalog.places if is_candidate(place)),
        key=lambda item: (-item[1], item[0].osm_type.value, item[0].osm_id, item[0].kind),
    )
    previous_records = {record.identity: record for record in previous.records} if previous else {}
    records = []
    for rank, (place, score, reasons) in enumerate(ranked, start=1):
        record = _record_for(place, score, reasons, rank)
        old = previous_records.get(record.identity)
        if old is not None:
            record = record.model_copy(
                update={"decision": old.decision, "reviewed_at": old.reviewed_at}
            )
        records.append(record)
    return ReviewDocument(
        format_version=1,
        source_artifact=source_artifact,
        catalog_revision=catalog.metadata["catalog_revision"],
        generated_at=datetime.now(UTC).isoformat() if generated_at is None else generated_at,
        records=records,
    )


__all__ = [
    "NETWORK_RADIUS_M",
    "build_document",
    "filter_catalog_to_network",
    "is_candidate",
    "score_place",
]
