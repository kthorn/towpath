import pytest

from pound.catalog.metadata import NormalizedLink, normalize_external_link, normalize_metadata


def test_normalize_metadata_keeps_safe_user_facing_fields():
    metadata = normalize_metadata(
        {
            "name": "The Navigation",
            "website": "https://example.test/pub",
            "contact:website": "https://example.test/contact",
            "opening_hours": "Mo-Su 11:00-23:00",
            "note": "mapper-only note",
            "fixme": "check this",
        },
        kind="pub",
    )

    assert metadata.name == "The Navigation"
    assert metadata.links == [
        NormalizedLink(label="Website", url="https://example.test/contact"),
        NormalizedLink(label="Website", url="https://example.test/pub"),
    ]
    assert metadata.opening_hours == "Mo-Su 11:00-23:00"


def test_normalize_metadata_deduplicates_equivalent_websites():
    metadata = normalize_metadata(
        {
            "website": "https://example.test/contact",
            "contact:website": "HTTPS://example.test/contact",
        },
        kind="pub",
    )

    assert metadata.links == [NormalizedLink(label="Website", url="https://example.test/contact")]


def test_normalize_metadata_keeps_typed_common_fields_and_address():
    metadata = normalize_metadata(
        {
            "name": "Canal Stores",
            "alt_name": "The Stores",
            "brand": "Canal Co",
            "operator": "Towpath Ltd",
            "addr:housenumber": "12",
            "addr:street": "Canal Street",
            "addr:place": "Wharf",
            "addr:city": "Oxford",
            "addr:postcode": "OX1 1AA",
            "access": "customers",
            "fee": "no",
            "wheelchair": "yes",
            "phone": "+44 1865 123456",
            "contact:phone": "+44 1865 123456",
            "email": "hello@example.test",
            "contact:email": "hello@example.test",
            "description": "A useful shop for boaters.",
        },
        kind="general",
    )

    assert metadata.name == "Canal Stores"
    assert metadata.alt_name == "The Stores"
    assert metadata.brand == "Canal Co"
    assert metadata.operator == "Towpath Ltd"
    assert metadata.address is not None
    assert metadata.address.house_number == "12"
    assert metadata.address.street == "Canal Street"
    assert metadata.address.place == "Wharf"
    assert metadata.address.city == "Oxford"
    assert metadata.address.postcode == "OX1 1AA"
    assert metadata.access == "customers"
    assert metadata.fee == "no"
    assert metadata.wheelchair == "yes"
    assert metadata.phone == "+44 1865 123456"
    assert metadata.email == "hello@example.test"
    assert metadata.description == "A useful shop for boaters."
    assert isinstance(metadata.kind_details, dict)


def test_normalize_external_link_accepts_only_safe_http_urls():
    assert normalize_external_link("Website", " HTTPS://example.test/a?q=1 ") == NormalizedLink(
        label="Website", url="https://example.test/a?q=1"
    )
    assert normalize_external_link("Website", "mailto:hello@example.test") is None
    assert normalize_external_link("Website", "https://user:secret@example.test") is None
    assert normalize_external_link("Website", "https://") is None
    assert normalize_external_link("Website", "https://example.test:not-a-port") is None
    assert normalize_external_link("Website", "<script>alert(1)</script>") is None
    assert normalize_external_link("Website", "https://example.test/" + "x" * 2048) is None


def test_normalize_metadata_rejects_malformed_references_and_overlong_values():
    metadata = normalize_metadata(
        {
            "name": "   ",
            "description": "d" * 2001,
            "wikidata": "not-a-qid",
            "wikipedia": "not a language reference",
            "website": "javascript:alert(1)",
        },
        kind="museum",
    )

    assert metadata.name is None
    assert metadata.description is None
    assert metadata.links == []


def test_normalize_metadata_canonicalizes_wikipedia_and_wikidata():
    metadata = normalize_metadata(
        {"wikipedia": "en:Oxford", "wikidata": "Q42"},
        kind="landmark",
    )

    assert metadata.links == [
        NormalizedLink(label="Wikipedia", url="https://en.wikipedia.org/wiki/Oxford"),
        NormalizedLink(label="Wikidata", url="https://www.wikidata.org/wiki/Q42"),
    ]


def test_normalize_metadata_omits_unallowlisted_and_empty_values():
    metadata = normalize_metadata(
        {
            "note": "internal",
            "fixme": "internal",
            "source": "survey",
            "random": "do not expose",
            "contact:phone": "",
            "operator": "  ",
        },
        kind="pub",
    )

    assert metadata.model_dump(exclude_none=True) == {"links": [], "kind_details": {}}


def test_normalize_metadata_rejects_unknown_kind():
    with pytest.raises(ValueError, match="unknown catalog kind"):
        normalize_metadata({"name": "Mystery"}, kind="unknown")
