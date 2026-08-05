import networkx as nx
import pytest

from pound.catalog.metadata import NormalizedLink
from pound.graph.spatial import GraphSpatialIndex
from pound.review.ranking import (
    build_document,
    filter_catalog_to_network,
    is_candidate,
    score_place,
)
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
        ("Canal trips", 0, "canal trips"),
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
    generic = place("marina", "Ordinary Marina")
    hire = place("marina", "Canal Boat Hire", operator="Holiday Narrowboats")
    club = place("marina", "Canal Boat Club", operator="Canal Cruising Association")

    generic_score, generic_reasons = score_place(generic)
    hire_score, hire_reasons = score_place(hire)
    club_score, club_reasons = score_place(club)

    assert generic_score == 0
    assert generic_reasons == []
    assert hire_score > club_score > generic_score
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


@pytest.mark.parametrize(
    ("name", "kind", "operator", "website", "expected_score", "reason"),
    (
        ("Canal Boat Project", "landmark", None, None, 10, "project"),
        ("Kayak and Boat Hire", "landmark", None, None, 10, "kayak"),
        ("Canal Boat Carving Welcome Post", "landmark", None, None, 10, "carving"),
        ("Skipton Boat Trips", "landmark", "Pennine Boat Trips", None, 16, "boat trips"),
        ("Sweet William Charter Boat", "marina", None, None, 10, "charter boat"),
        ("Kings Staithe", "marina", "Wroxham Launch Hire", None, 0, "launch hire"),
        ("Charter Stone", "landmark", None, None, 0, "stone"),
        (
            "Richardsons Boating Holidays",
            "marina",
            None,
            None,
            70,
            "boating holidays",
        ),
        (
            "Canal Cruising Company",
            "marina",
            None,
            "https://www.canalcruising.co.uk/",
            36,
            "cruising",
        ),
        (
            "Wherry Hathor",
            "landmark",
            "Wherry Yacht Charitable Charter Trust",
            "https://www.wherryyachtcharter.org",
            24,
            "charter",
        ),
    ),
)
def test_feedback_rules_demote_false_positives_without_harming_positives(
    name, kind, operator, website, expected_score, reason
):
    candidate = place(kind, name, operator=operator, website=website)

    score, reasons = score_place(candidate)

    assert score == expected_score
    assert any(reason in detail for detail in reasons)


def test_network_filter_removes_distant_places_and_preserves_retained_decisions():
    graph = nx.Graph()
    graph.add_node(1, lat=51.0, lon=-1.0)
    graph.add_node(2, lat=51.0, lon=-0.99)
    graph.add_edge(1, 2)
    network_index = GraphSpatialIndex(graph)
    near = place("marina", "Near Marina", osm_id=1, lat=51.0, lon=-1.0)
    far = place("marina", "Far Marina", osm_id=2, lat=52.0, lon=-1.0)
    catalog = catalog_with(near, far)

    filtered = filter_catalog_to_network(catalog, network_index)
    previous = build_document(catalog)
    previous = previous.model_copy(
        update={
            "records": [
                record.model_copy(
                    update={
                        "decision": (
                            "vacation_hire" if record.name == "Near Marina" else "not_vacation_hire"
                        ),
                        "reviewed_at": (
                            "2026-08-04T00:00:00Z"
                            if record.name == "Near Marina"
                            else "2026-08-04T00:01:00Z"
                        ),
                    }
                )
                for record in previous.records
            ]
        }
    )

    document = build_document(filtered, previous=previous)

    assert [record.name for record in filtered.places] == ["Near Marina"]
    assert [record.name for record in document.records] == ["Near Marina"]
    assert document.records[0].decision == "vacation_hire"
    assert document.records[0].reviewed_at == "2026-08-04T00:00:00Z"
