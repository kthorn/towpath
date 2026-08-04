import pytest

from pound.review.store import ReviewFileError, ReviewStore, load_document, write_document
from tests.review.fixtures import sample_document


def test_document_round_trips_and_preserves_null_decision(tmp_path):
    document = sample_document(decision=None)
    path = tmp_path / "review.json"
    write_document(path, document)

    loaded = load_document(path)

    assert loaded == document
    assert loaded.records[0].decision is None


def test_store_updates_one_decision_and_timestamp(tmp_path):
    path = tmp_path / "review.json"
    write_document(path, sample_document(decision=None))

    store = ReviewStore(path)
    updated = store.save_decision("node/1/marina", "vacation_hire")

    assert updated.records[0].decision == "vacation_hire"
    assert updated.records[0].reviewed_at
    assert load_document(path).records[0].decision == "vacation_hire"


def test_invalid_json_is_rejected_without_replacement(tmp_path):
    path = tmp_path / "review.json"
    path.write_text('{"format_version": 1}', encoding="utf-8")

    with pytest.raises(ReviewFileError):
        load_document(path)
