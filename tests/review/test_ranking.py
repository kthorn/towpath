from pound.catalog.metadata import NormalizedLink
from pound.review.ranking import build_document, is_candidate, score_place
from tests.review.fixtures import catalog_with, place


def test_all_named_marinas_and_moorings_are_candidates():
    catalog = catalog_with(
        place("marina", "Ordinary Marina"),
        place("mooring", "Canal Mooring"),
        place("pub", "Boat Inn"),
    )

    document = build_document(catalog)

    assert {record.kind for record in document.records} == {"marina", "mooring"}


def test_boat_landmark_is_candidate_but_unrelated_landmark_is_not():
    catalog = catalog_with(
        place("landmark", "Skipton Boat Trips"),
        place("landmark", "Village War Memorial"),
    )

    document = build_document(catalog)

    assert [record.name for record in document.records] == ["Skipton Boat Trips"]


def test_approved_landmark_signals_are_candidates_and_score_with_reasons():
    cases = (
        ("Canal trips", 30, "canal trips"),
        ("Pulteney Cruisers Ltd", 30, "cruisers"),
        ("Canal Boat Centre", 70, "canal boat"),
        ("Self-Drive", 60, "self drive"),
    )

    for name, expected_score, expected_phrase in cases:
        candidate = place("landmark", name)

        assert is_candidate(candidate)
        score, reasons = score_place(candidate)

        assert score == expected_score
        assert any(expected_phrase in reason for reason in reasons)


def test_strong_hire_phrase_outranks_generic_marina_and_exposes_reasons():
    hire = place("marina", "Canal Boat Hire", operator="Holiday Narrowboats")
    club = place("marina", "Canal Boat Club", operator="Canal Cruising Association")

    hire_score, hire_reasons = score_place(hire)
    club_score, club_reasons = score_place(club)

    assert hire_score > club_score
    assert any("boat hire" in reason for reason in hire_reasons)
    assert any("club" in reason or "association" in reason for reason in club_reasons)


def test_ranking_is_stable_for_equal_scores_and_previous_decisions_survive():
    first = place("marina", "A Marina", osm_id=1)
    second = place("marina", "B Marina", osm_id=2)
    previous = build_document(catalog_with(first), generated_at="2026-08-03T00:00:00Z")
    previous = previous.model_copy(
        update={
            "records": [
                previous.records[0].model_copy(
                    update={"decision": "uncertain", "reviewed_at": "2026-08-03T00:01:00Z"}
                )
            ]
        }
    )

    document = build_document(
        catalog_with(second, first),
        previous=previous,
        generated_at="2026-08-04T00:00:00Z",
    )

    assert [record.name for record in document.records] == ["A Marina", "B Marina"]
    assert document.records[0].decision == "uncertain"
    assert document.records[0].reviewed_at == "2026-08-03T00:01:00Z"


def test_links_preserve_all_labels_but_website_urls_only_include_websites():
    candidate = place("marina", "Linked Marina", osm_id=3, website="https://hire.example/boats")
    candidate = candidate.model_copy(
        update={
            "metadata": candidate.metadata.model_copy(
                update={
                    "links": [
                        *candidate.metadata.links,
                        NormalizedLink("Wikipedia", "https://en.wikipedia.org/wiki/Boats"),
                        NormalizedLink("Wikidata", "https://www.wikidata.org/wiki/Q42"),
                    ]
                }
            )
        }
    )

    record = build_document(catalog_with(candidate)).records[0]

    assert [(link.label, link.url) for link in record.links] == [
        ("Website", "https://hire.example/boats"),
        ("OpenStreetMap", "https://www.openstreetmap.org/node/3"),
        ("Wikipedia", "https://en.wikipedia.org/wiki/Boats"),
        ("Wikidata", "https://www.wikidata.org/wiki/Q42"),
    ]
    assert record.website_urls == ["https://hire.example/boats"]
    assert record.osm_url == "https://www.openstreetmap.org/node/3"
