"""Strict, user-facing metadata normalization for catalog records."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pound.catalog.manifest import CATALOG_KINDS

MAX_LINK_LENGTH = 2_048
_MAX_TEXT_LENGTH = 256
_MAX_DESCRIPTION_LENGTH = 2_000
_WIKIPEDIA_LANGUAGE = re.compile(r"^[a-z]{2,12}$")
_WIKIDATA_ID = re.compile(r"^Q[1-9][0-9]*$")


@dataclass(frozen=True)
class NormalizedLink:
    label: str
    url: str


class CatalogAddress(BaseModel):
    """Normalized address components from the bounded OSM metadata surface."""

    model_config = ConfigDict(extra="forbid", strict=True)

    house_number: str | None = Field(default=None, max_length=256)
    street: str | None = Field(default=None, max_length=256)
    place: str | None = Field(default=None, max_length=256)
    city: str | None = Field(default=None, max_length=256)
    postcode: str | None = Field(default=None, max_length=64)


class CatalogMetadata(BaseModel):
    """User-facing metadata with no arbitrary raw-tag escape hatch."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str | None = Field(default=None, max_length=256)
    alt_name: str | None = Field(default=None, max_length=256)
    brand: str | None = Field(default=None, max_length=256)
    operator: str | None = Field(default=None, max_length=256)
    address: CatalogAddress | None = None
    opening_hours: str | None = Field(default=None, max_length=512)
    access: str | None = Field(default=None, max_length=128)
    fee: str | None = Field(default=None, max_length=128)
    wheelchair: str | None = Field(default=None, max_length=128)
    phone: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=320)
    description: str | None = Field(default=None, max_length=2_000)
    links: list[NormalizedLink] = Field(default_factory=list)
    kind_details: dict[str, str] = Field(default_factory=dict)

    @field_validator("links")
    @classmethod
    def validate_links(cls, links: list[NormalizedLink]) -> list[NormalizedLink]:
        for link in links:
            if normalize_external_link(link.label, link.url) != link:
                raise ValueError("links must contain normalized HTTP(S) URLs")
        return links


def _clean_text(value: object, *, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > limit or "<" in value or ">" in value:
        return None
    if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
        return None
    return value


def normalize_external_link(label: str, value: str) -> NormalizedLink | None:
    """Return a credential-free absolute HTTP(S) link, or reject it."""
    clean_label = _clean_text(label, limit=64)
    clean_value = _clean_text(value, limit=MAX_LINK_LENGTH)
    if clean_label is None or clean_value is None:
        return None

    try:
        parsed = urlsplit(clean_value)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    try:
        _port = parsed.port
    except ValueError:
        return None
    if parsed.hostname is None or any(character.isspace() for character in clean_value):
        return None
    normalized_url = parsed._replace(scheme=parsed.scheme.lower()).geturl()
    return NormalizedLink(label=clean_label, url=normalized_url)


def _canonical_wikipedia(value: object) -> NormalizedLink | None:
    reference = _clean_text(value, limit=MAX_LINK_LENGTH)
    if reference is None:
        return None

    if "://" in reference:
        try:
            parsed = urlsplit(reference)
        except ValueError:
            return None
        host = parsed.hostname or ""
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or parsed.username is not None
            or parsed.password is not None
            or not host.endswith(".wikipedia.org")
            or not _WIKIPEDIA_LANGUAGE.fullmatch(host.removesuffix(".wikipedia.org"))
            or not parsed.path.startswith("/wiki/")
        ):
            return None
        title = unquote(parsed.path.removeprefix("/wiki/"))
        if not title or parsed.query or parsed.fragment:
            return None
        language = host.removesuffix(".wikipedia.org")
    else:
        language, separator, title = reference.partition(":")
        if not separator or not _WIKIPEDIA_LANGUAGE.fullmatch(language):
            return None

    clean_title = _clean_text(title, limit=512)
    if clean_title is None or "://" in clean_title:
        return None
    encoded_title = quote(clean_title.replace(" ", "_"), safe="()_,-./:")
    return NormalizedLink(
        label="Wikipedia",
        url=f"https://{language}.wikipedia.org/wiki/{encoded_title}",
    )


def _canonical_wikidata(value: object) -> NormalizedLink | None:
    reference = _clean_text(value, limit=256)
    if reference is None:
        return None

    if "://" in reference:
        try:
            parsed = urlsplit(reference)
        except ValueError:
            return None
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or parsed.hostname != "www.wikidata.org"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith("/wiki/")
        ):
            return None
        reference = unquote(parsed.path.removeprefix("/wiki/"))

    if not _WIKIDATA_ID.fullmatch(reference):
        return None
    return NormalizedLink(label="Wikidata", url=f"https://www.wikidata.org/wiki/{reference}")


def _first_value(tags: Mapping[str, str], *keys: str, limit: int) -> str | None:
    for key in keys:
        value = _clean_text(tags.get(key), limit=limit)
        if value is not None:
            return value
    return None


def normalize_metadata(tags: Mapping[str, str], *, kind: str) -> CatalogMetadata:
    """Normalize the manifest's allowlisted fields into ``CatalogMetadata``.

    ``kind_details`` is intentionally empty until the manifest measures and
    approves kind-specific raw keys; arbitrary source tags never cross this
    boundary.
    """
    if kind not in CATALOG_KINDS:
        raise ValueError(f"unknown catalog kind: {kind}")

    address_values = {
        "house_number": _clean_text(tags.get("addr:housenumber"), limit=256),
        "street": _clean_text(tags.get("addr:street"), limit=256),
        "place": _clean_text(tags.get("addr:place"), limit=256),
        "city": _clean_text(tags.get("addr:city"), limit=256),
        "postcode": _clean_text(tags.get("addr:postcode"), limit=64),
    }
    address = CatalogAddress(**address_values) if any(address_values.values()) else None

    links: list[NormalizedLink] = []
    contact_website = normalize_external_link("Website", tags.get("contact:website", ""))
    website = normalize_external_link("Website", tags.get("website", ""))
    if contact_website is not None:
        links.append(contact_website)
    if website is not None and website != contact_website:
        links.append(website)

    wikipedia = _canonical_wikipedia(tags.get("wikipedia"))
    wikidata = _canonical_wikidata(tags.get("wikidata"))
    if wikipedia is not None:
        links.append(wikipedia)
    if wikidata is not None:
        links.append(wikidata)

    return CatalogMetadata(
        name=_clean_text(tags.get("name"), limit=_MAX_TEXT_LENGTH),
        alt_name=_clean_text(tags.get("alt_name"), limit=_MAX_TEXT_LENGTH),
        brand=_clean_text(tags.get("brand"), limit=_MAX_TEXT_LENGTH),
        operator=_clean_text(tags.get("operator"), limit=_MAX_TEXT_LENGTH),
        address=address,
        opening_hours=_clean_text(tags.get("opening_hours"), limit=512),
        access=_clean_text(tags.get("access"), limit=128),
        fee=_clean_text(tags.get("fee"), limit=128),
        wheelchair=_clean_text(tags.get("wheelchair"), limit=128),
        phone=_first_value(tags, "contact:phone", "phone", limit=128),
        email=_first_value(tags, "contact:email", "email", limit=320),
        description=_clean_text(tags.get("description"), limit=_MAX_DESCRIPTION_LENGTH),
        links=links,
        kind_details={},
    )
