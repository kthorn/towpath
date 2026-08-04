from pathlib import Path

import pytest

from pound.review.models import ReviewDecision, ReviewDocument, ReviewLink, ReviewRecord
from pound.review.store import load_document, write_document
from pound.review.web import create_app


def _record(
    identity: str,
    rank: int,
    name: str,
    *,
    decision: ReviewDecision | None = None,
    website: str | None = None,
) -> ReviewRecord:
    osm_id = int(identity.split("/")[1])
    links = [
        ReviewLink(
            label="OpenStreetMap",
            url=f"https://www.openstreetmap.org/node/{osm_id}",
        )
    ]
    if website:
        links.insert(0, ReviewLink(label="Website", url=website))
    return ReviewRecord(
        identity=identity,
        osm_type="node",
        osm_id=osm_id,
        kind="marina",
        name=name,
        lat=51.0,
        lon=-1.0,
        metadata={"operator": "Canal & Co", "description": "A review <candidate>"},
        links=links,
        website_urls=[website] if website else [],
        osm_url=f"https://www.openstreetmap.org/node/{osm_id}",
        likelihood_score=80 - rank,
        rank=rank,
        likelihood_reasons=["name strong rule matched"],
        decision=decision,
        reviewed_at="2026-08-03T00:00:00Z" if decision else None,
    )


def _document(*, complete: bool = False) -> ReviewDocument:
    decisions: list[ReviewDecision | None] = [
        "vacation_hire" if complete else None,
        "not_vacation_hire" if complete else None,
        "vacation_hire",
        "not_vacation_hire",
        "uncertain",
    ]
    return ReviewDocument(
        format_version=1,
        source_artifact="test-catalog.pkl",
        catalog_revision="catalog-test",
        generated_at="2026-08-03T00:00:00Z",
        records=[
            _record(
                "node/1/marina",
                1,
                "Canal Boat Hire",
                decision=decisions[0],
                website="https://hire.example/",
            ),
            _record("node/2/marina", 2, "Second Marina", decision=decisions[1]),
            _record("node/3/marina", 3, "Reviewed Vacation", decision=decisions[2]),
            _record("node/4/marina", 4, "Reviewed Non Vacation", decision=decisions[3]),
            _record("node/5/marina", 5, "Reviewed Uncertain", decision=decisions[4]),
        ],
    )


@pytest.fixture
def review_path(tmp_path: Path) -> Path:
    path = tmp_path / "review.json"
    write_document(path, _document())
    return path


@pytest.fixture
def client(review_path: Path):
    return create_app(review_path).test_client()


def test_home_shows_two_panes_and_record_metadata(client):
    response = client.get("/?filter=unreviewed")

    assert response.status_code == 200
    assert b"Canal Boat Hire" in response.data
    assert b"https://hire.example/" in response.data
    assert b"iframe" in response.data
    assert b"Vacation hire" in response.data
    assert b"Canal &amp; Co" in response.data
    assert b"&lt;candidate&gt;" in response.data


def test_decision_is_saved_and_redirects_to_next_unreviewed(client, review_path):
    response = client.post(
        "/decision",
        data={
            "identity": "node/1/marina",
            "decision": "vacation_hire",
            "filter": "unreviewed",
        },
    )

    assert response.status_code == 302
    assert load_document(review_path).records[0].decision == "vacation_hire"
    assert "identity=node%2F2%2Fmarina" in response.headers["Location"]
    assert "filter=unreviewed" in response.headers["Location"]


def test_decision_redirect_wraps_to_first_unreviewed(client, review_path):
    response = client.post(
        "/decision",
        data={
            "identity": "node/2/marina",
            "decision": "uncertain",
            "filter": "all",
        },
    )

    assert response.status_code == 302
    assert load_document(review_path).records[1].decision == "uncertain"
    assert "identity=node%2F1%2Fmarina" in response.headers["Location"]


def test_invalid_decision_is_rejected_without_writing(client, review_path):
    response = client.post(
        "/decision",
        data={"identity": "node/1/marina", "decision": "maybe", "filter": "all"},
    )

    assert response.status_code == 400
    assert load_document(review_path).records[0].decision is None


def test_unknown_identity_is_rejected_without_writing(client, review_path):
    response = client.post(
        "/decision",
        data={"identity": "node/999/marina", "decision": "uncertain", "filter": "all"},
    )

    assert response.status_code == 400
    assert [record.decision for record in load_document(review_path).records] == [
        None,
        None,
        "vacation_hire",
        "not_vacation_hire",
        "uncertain",
    ]


@pytest.mark.parametrize(
    ("filter_name", "record_name"),
    [
        ("all", "Canal Boat Hire"),
        ("unreviewed", "Canal Boat Hire"),
        ("vacation_hire", "Reviewed Vacation"),
        ("not_vacation_hire", "Reviewed Non Vacation"),
        ("uncertain", "Reviewed Uncertain"),
    ],
)
def test_each_filter_selects_a_matching_record(client, filter_name, record_name):
    response = client.get(f"/?filter={filter_name}")

    assert response.status_code == 200
    assert f"<h1>{record_name}</h1>".encode() in response.data


def test_previous_and_next_links_use_ranked_neighbors(client):
    response = client.get("/?filter=all&identity=node/2/marina")

    assert response.status_code == 200
    assert b"identity=node%2F1%2Fmarina" in response.data
    assert b"identity=node%2F3%2Fmarina" in response.data


def test_no_website_shows_osm_fallback(client):
    response = client.get("/?filter=all&identity=node/2/marina")

    assert response.status_code == 200
    assert b"No website recorded" in response.data
    assert b"https://www.openstreetmap.org/node/2" in response.data
    assert b'target="_blank"' in response.data
    assert b'rel="noopener noreferrer"' in response.data


def test_completed_unreviewed_view_has_completion_message(tmp_path):
    path = tmp_path / "complete.json"
    write_document(path, _document(complete=True))

    response = create_app(path).test_client().get("/?filter=unreviewed")

    assert response.status_code == 200
    assert b"All records have been reviewed" in response.data


def test_unknown_filter_and_identity_are_bad_requests(client):
    assert client.get("/?filter=bogus").status_code == 400
    assert client.get("/?filter=all&identity=node/999/marina").status_code == 400


def test_store_is_loaded_once_and_path_is_not_request_controlled(review_path):
    app = create_app(review_path)

    assert app.extensions["boat_hire_review_store"].path == review_path
    response = app.test_client().get("/?filter=all&path=/tmp/other.json")

    assert response.status_code == 200
    assert app.extensions["boat_hire_review_store"].path == review_path
