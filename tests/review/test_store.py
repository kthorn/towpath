import json
from threading import Event, Lock, Thread

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


def test_failed_atomic_replace_preserves_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "review.json"
    write_document(path, sample_document(decision=None))
    original = path.read_bytes()

    def fail_replace(_temporary_path, _destination):
        raise OSError("replace failed")

    monkeypatch.setattr("pound.review.store.os.replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        write_document(path, sample_document(decision="vacation_hire"))

    assert path.read_bytes() == original


def test_invalid_json_is_rejected_without_replacement(tmp_path):
    path = tmp_path / "review.json"
    path.write_text('{"format_version": 1}', encoding="utf-8")

    with pytest.raises(ReviewFileError):
        load_document(path)


@pytest.mark.parametrize("field", ["link", "website_urls", "osm_url"])
def test_review_file_rejects_non_http_urls(tmp_path, field):
    path = tmp_path / "review.json"
    payload = sample_document().model_dump(mode="json")
    record = payload["records"][0]
    if field == "link":
        record["links"][0]["url"] = "javascript:alert(1)"
    elif field == "website_urls":
        record[field] = ["javascript:alert(1)"]
    else:
        record[field] = "javascript:alert(1)"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ReviewFileError, match="HTTP\\(S\\)"):
        load_document(path)


def test_store_serializes_concurrent_decisions(tmp_path, monkeypatch):
    path = tmp_path / "review.json"
    first_record = sample_document(decision=None).records[0]
    second_record = first_record.model_copy(
        update={"identity": "node/2/marina", "osm_id": 2, "name": "Second Marina", "rank": 2}
    )
    document = sample_document(decision=None).model_copy(
        update={"records": [first_record, second_record]}
    )
    write_document(path, document)
    store = ReviewStore(path)

    first_write_started = Event()
    second_write_started = Event()
    release_first_write = Event()
    call_lock = Lock()
    call_count = 0
    original_write_document = write_document

    def pause_first_write(target_path, updated):
        nonlocal call_count
        with call_lock:
            call_count += 1
            is_first_write = call_count == 1
        if is_first_write:
            first_write_started.set()
            assert release_first_write.wait(timeout=5)
        else:
            second_write_started.set()
        original_write_document(target_path, updated)

    monkeypatch.setattr("pound.review.store.write_document", pause_first_write)
    failures = []

    def save(identity, decision):
        try:
            store.save_decision(identity, decision)
        except Exception as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    first = Thread(target=save, args=("node/1/marina", "vacation_hire"))
    second = Thread(target=save, args=("node/2/marina", "not_vacation_hire"))
    first.start()
    assert first_write_started.wait(timeout=5)
    second.start()
    try:
        assert not second_write_started.wait(timeout=1)
    finally:
        release_first_write.set()
        first.join(timeout=5)
        second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert not failures
    assert [record.decision for record in load_document(path).records] == [
        "vacation_hire",
        "not_vacation_hire",
    ]
