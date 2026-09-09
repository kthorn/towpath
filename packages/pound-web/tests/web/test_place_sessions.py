import pytest
from pound_web.place_sessions import PlaceSessionError, PlaceSessions


def test_session_ownership_and_expiry():
    now = [0.0]
    store = PlaceSessions(clock=lambda: now[0])
    session = store.create()
    assert store.get(session.session_id, session.token) is session
    with pytest.raises(PlaceSessionError, match="session_unavailable"):
        store.get(session.session_id, "wrong")
    now[0] = 601
    with pytest.raises(PlaceSessionError, match="session_unavailable"):
        store.get(session.session_id, session.token)


def test_tasks_are_bound_single_use_and_expiring():
    now = [0.0]
    store = PlaceSessions(clock=lambda: now[0])
    session = store.create()
    store.start(session, "revision")
    task = store.issue(session, "search", {"query": "museum"})
    with pytest.raises(PlaceSessionError, match="stale_task"):
        store.complete(session, task["task_id"], "wrong", task["digest"], {})
    store.complete(session, task["task_id"], task["run_id"], task["digest"], {})
    with pytest.raises(PlaceSessionError, match="stale_task"):
        store.complete(session, task["task_id"], task["run_id"], task["digest"], {})
    task = store.issue(session, "search", {})
    now[0] = 21
    with pytest.raises(PlaceSessionError, match="task_expired"):
        store.complete(session, task["task_id"], task["run_id"], task["digest"], {})


def test_new_run_invalidates_old_task_and_limits_are_cumulative():
    store = PlaceSessions()
    session = store.create()
    store.start(session, "a")
    task = store.issue(session, "search", {})
    store.start(session, "b")
    with pytest.raises(PlaceSessionError):
        store.complete(session, task["task_id"], task["run_id"], task["digest"], {})
    for _ in range(9):
        store.issue(session, "search", {})
    with pytest.raises(PlaceSessionError, match="session_budget"):
        store.issue(session, "search", {})


def test_resolve_and_transfer_api(web_client):
    from pound.catalog.resolve import PlaceNameIndex

    # Synthetic Bletchley source record on the same fixture graph as manual candidates.
    index = web_client.app.state.place_name_index
    web_client.app.state.place_name_index = PlaceNameIndex(
        tuple(
            place.model_copy(update={"name": "Bletchley Park"}) if place.kind == "museum" else place
            for place in index.places
        ),
        index.revision,
    )
    auth = web_client.post("/api/place-sessions").json()
    headers = {"Authorization": f"Bearer {auth['token']}"}
    base = f"/api/place-sessions/{auth['session_id']}"
    result = web_client.post(
        base + "/resolve", headers=headers, json={"query": "Bletchley Park"}
    ).json()
    assert result["status"] == "resolved"
    assert result["osm"]["options"][0]["source_id"] == "osm:node:202"
    selected = web_client.post(
        base + "/select",
        headers=headers,
        json={"run_id": result["run_id"], "option_ref": result["osm"]["options"][0]["option_ref"]},
    )
    assert selected.status_code == 200, selected.text
    task = selected.json()["task"]
    assert task["kind"] == "walking"
    assert task["payload"]["mode"] == "WALK"
    assert len(task["payload"]["candidates"]) <= 5
    statuses = [
        {"candidate_id": c["candidate_id"], "outward": "available", "return": "unavailable"}
        for c in task["payload"]["candidates"]
    ]
    payload = {
        "run_id": task["run_id"],
        "digest": task["digest"],
        "status": "complete",
        "transfers": statuses,
    }
    endpoint = base + "/tasks/" + task["task_id"] + "/result"
    response = web_client.post(endpoint, headers=headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["transfers"] == statuses
    assert web_client.post(endpoint, headers=headers, json=payload).status_code == 409


def test_google_fallback_keeps_provider_content_out_of_results(web_client):
    auth = web_client.post("/api/place-sessions").json()
    headers = {"Authorization": f"Bearer {auth['token']}"}
    base = f"/api/place-sessions/{auth['session_id']}"
    result = web_client.post(base + "/resolve", headers=headers, json={"query": "absent"}).json()
    assert result["status"] == "pending"
    task = result["task"]
    payload = {
        "run_id": task["run_id"],
        "digest": task["digest"],
        "status": "matches",
        "option_refs": ["choice-1"],
    }
    endpoint = base + "/tasks/" + task["task_id"] + "/result"
    rejected = web_client.post(endpoint, headers=headers, json=payload | {"name": "Google content"})
    assert rejected.status_code == 422
    assert "Google content" not in rejected.text
    response = web_client.post(endpoint, headers=headers, json=payload)
    assert response.status_code == 200
    assert response.json()["option_refs"] == ["choice-1"]
    selected = web_client.post(
        base + "/select",
        headers=headers,
        json={
            "run_id": task["run_id"],
            "option_ref": "choice-1",
            "coordinate": {"lat": 51.002, "lon": -1.002},
        },
    )
    assert selected.status_code == 200
    assert "attraction_coordinate" not in selected.text
    assert web_client.get(base + "/events").status_code == 401


def test_validation_unknown_candidate_and_stale_revision(web_client):
    auth = web_client.post("/api/place-sessions").json()
    headers = {"Authorization": f"Bearer {auth['token']}"}
    base = f"/api/place-sessions/{auth['session_id']}"
    response = web_client.post(base + "/resolve", headers=headers, json={"query": "museum 202"})
    result = response.json()
    web_client.app.state.artifact_revision = "changed"
    response = web_client.post(
        base + "/select",
        headers=headers,
        json={"run_id": result["run_id"], "option_ref": result["osm"]["options"][0]["option_ref"]},
    )
    assert response.status_code == 409


def session_request(client, query="absent"):
    auth = client.post("/api/place-sessions").json()
    headers = {"Authorization": f"Bearer {auth['token']}"}
    base = f"/api/place-sessions/{auth['session_id']}"
    result = client.post(base + "/resolve", headers=headers, json={"query": query}).json()
    return headers, base, result


def test_manual_recovery_and_unknown_candidate_rejection(web_client):
    headers, base, result = session_request(web_client)
    selected = web_client.post(
        base + "/manual",
        headers=headers,
        json={"run_id": result["run_id"], "coordinate": {"lat": 51.0, "lon": -1.0}},
    )
    assert selected.status_code == 200
    task = selected.json()["task"]
    payload = {
        "run_id": task["run_id"],
        "digest": task["digest"],
        "status": "complete",
        "transfers": [{"candidate_id": "made-up", "outward": "available", "return": "available"}],
    }
    assert (
        web_client.post(
            base + "/tasks/" + task["task_id"] + "/result", headers=headers, json=payload
        ).status_code
        == 422
    )


def test_coordinate_confusion_and_payload_limit(web_client):
    headers, base, result = session_request(web_client)
    assert (
        web_client.post(
            base + "/manual",
            headers=headers,
            json={"run_id": result["run_id"], "coordinate": {"lat": -1.0, "lon": 51.0}},
        ).status_code
        == 400
    )
    assert (
        web_client.post(base + "/resolve", headers=headers, content=b"x" * 16385).status_code == 413
    )


def test_events_and_result_reject_expired_and_changed_artifact(web_client):
    headers, base, result = session_request(web_client)
    assert web_client.get(base + "/events", headers=headers).headers["cache-control"] == "no-store"
    registry = web_client.app.state.place_sessions
    session = next(iter(registry.sessions.values()))
    session.task["deadline"] = -1
    assert web_client.get(base + "/result", headers=headers).status_code == 409
    web_client.app.state.artifact_revision = "stale"
    assert web_client.get(base + "/events", headers=headers).status_code == 409


def test_provider_selection_coordinate_is_bound_to_option(web_client):
    headers, base, result = session_request(web_client)
    task = result["task"]
    response = web_client.post(
        base + "/tasks/" + task["task_id"] + "/result",
        headers=headers,
        json={
            "run_id": task["run_id"],
            "digest": task["digest"],
            "status": "matches",
            "option_refs": ["choice-1"],
        },
    )
    assert response.status_code == 200
    payload = {
        "run_id": task["run_id"],
        "option_ref": "choice-1",
        "coordinate": {"lat": 51.0, "lon": -1.0},
    }
    assert web_client.post(base + "/select", headers=headers, json=payload).status_code == 200
    payload["coordinate"] = {"lat": 52.0, "lon": -2.0}
    assert web_client.post(base + "/select", headers=headers, json=payload).status_code == 409


def test_osm_query_work_has_cumulative_session_limit():
    store = PlaceSessions()
    session = store.create()
    for _ in range(20):
        store.start(session, "r")
    with pytest.raises(PlaceSessionError, match="session_budget"):
        store.start(session, "r")


def test_expiry_remains_terminal_and_detached_session_cannot_complete():
    now = [0.0]
    store = PlaceSessions(clock=lambda: now[0])
    session = store.create()
    store.start(session, "r")
    task = store.issue(session, "search", {})
    session.result = {"status": "pending", "task": task}
    now[0] = 21
    with pytest.raises(PlaceSessionError):
        store.complete(session, task["task_id"], task["run_id"], task["digest"], {})
    assert session.result == {"status": "unavailable", "reason": "task_expired"}
    task = store.issue(session, "search", {})
    del store.sessions[session.session_id]
    with pytest.raises(PlaceSessionError, match="session_unavailable"):
        store.complete(session, task["task_id"], task["run_id"], task["digest"], {})


def test_manual_coordinates_can_start_without_a_name_lookup(web_client):
    auth = web_client.post("/api/place-sessions").json()
    headers = {"Authorization": f"Bearer {auth['token']}"}
    base = f"/api/place-sessions/{auth['session_id']}"
    response = web_client.post(
        base + "/manual", headers=headers, json={"coordinate": {"lat": 51.0, "lon": -1.0}}
    )
    assert response.status_code == 200
    assert response.json()["run_id"]
    assert response.json()["task"]["kind"] == "walking"


def test_resolution_metrics_exclude_query_and_provider_content(web_client, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="pound_web.place_api"):
        session_request(web_client, "private user query")
    records = [r for r in caplog.records if r.name == "pound_web.place_api"]
    assert any(getattr(r, "outcome", None) == "not_found" for r in records)
    assert "private user query" not in repr([r.__dict__ for r in records])


def test_provider_work_deadline_excludes_user_selection_wait():
    now = [0.0]
    store = PlaceSessions(clock=lambda: now[0])
    session = store.create()
    store.start(session, "r")
    for _ in range(3):
        task = store.issue(session, "search", {})
        now[0] += 19
        store.complete(session, task["task_id"], task["run_id"], task["digest"], {})
        now[0] += 30  # user selection time is not provider work
    task = store.issue(session, "search", {})
    assert task["timeout_ms"] == 3000
    now[0] += 4
    with pytest.raises(PlaceSessionError, match="task_expired"):
        store.complete(session, task["task_id"], task["run_id"], task["digest"], {})
    with pytest.raises(PlaceSessionError, match="operation_budget"):
        store.issue(session, "search", {})


def test_malformed_digest_and_unicode_credentials_are_rejected(web_client):
    store = PlaceSessions()
    session = store.create()
    with pytest.raises(PlaceSessionError, match="session_unavailable"):
        store.get(session.session_id, "é" * 32)
    headers, base, result = session_request(web_client)
    task = result["task"]
    response = web_client.post(
        base + "/tasks/" + task["task_id"] + "/result",
        headers=headers,
        json={"run_id": task["run_id"], "digest": "é" * 64, "status": "not_found"},
    )
    assert response.status_code == 422


def test_manual_only_session_requires_name_before_google_search(web_client):
    auth = web_client.post("/api/place-sessions").json()
    headers = {"Authorization": f"Bearer {auth['token']}"}
    base = f"/api/place-sessions/{auth['session_id']}"
    selected = web_client.post(
        base + "/manual", headers=headers, json={"coordinate": {"lat": 51.0, "lon": -1.0}}
    ).json()
    response = web_client.post(
        base + "/google", headers=headers, json={"run_id": selected["run_id"]}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "name_required"
