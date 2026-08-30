"""Contract tests for the canal-network API geometry cache."""

import pytest
from fastapi.testclient import TestClient

import pound.web.api as api_module


def test_identical_requests_compute_reachability_once(
    web_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    calls = {"count": 0}
    original = api_module.select_boat_hire_reachability

    def counting(*args: object, **kwargs: object):
        calls["count"] += 1
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(api_module, "select_boat_hire_reachability", counting)

    first = web_client.post("/api/canal-network", json={"days": 7, "hours_per_day": 6})
    second = web_client.post("/api/canal-network", json={"days": 7, "hours_per_day": 6})

    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    assert calls["count"] == 1


def test_changed_constraints_compute_again(
    web_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    calls = {"count": 0}
    original = api_module.select_boat_hire_reachability

    def counting(*args: object, **kwargs: object):
        calls["count"] += 1
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(api_module, "select_boat_hire_reachability", counting)

    web_client.post("/api/canal-network", json={"days": 7, "hours_per_day": 6})
    web_client.post("/api/canal-network", json={"days": 5, "hours_per_day": 6})

    assert calls["count"] == 2


def test_selected_identity_is_part_of_cache_key(
    web_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    calls = {"count": 0}
    original = api_module.select_boat_hire_reachability

    def counting(*args: object, **kwargs: object):
        calls["count"] += 1
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(api_module, "select_boat_hire_reachability", counting)

    web_client.post("/api/canal-network", json={"days": 7, "hours_per_day": 6})
    web_client.post(
        "/api/canal-network",
        json={"days": 7, "hours_per_day": 6, "selected_base_identity": "test-provider/base:test"},
    )
    # A selected request reuses the cached union and computes only the cheap
    # single-anchor highlight (one extra reachability call).
    assert calls["count"] == 2

    # Repeating either request must hit the caches and add no calls.
    web_client.post("/api/canal-network", json={"days": 7, "hours_per_day": 6})
    web_client.post(
        "/api/canal-network",
        json={"days": 7, "hours_per_day": 6, "selected_base_identity": "test-provider/base:test"},
    )
    assert calls["count"] == 2


def test_switching_bases_only_computes_highlights(
    web_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    calls = {"count": 0}
    original = api_module.select_boat_hire_reachability

    def counting(*args: object, **kwargs: object):
        calls["count"] += 1
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(api_module, "select_boat_hire_reachability", counting)
    payload = {"days": 7, "hours_per_day": 6}

    web_client.post("/api/canal-network", json=payload)
    assert calls["count"] == 1

    web_client.post(
        "/api/canal-network", json={**payload, "selected_base_identity": "test-provider/base:test"}
    )
    assert calls["count"] == 2

    web_client.post(
        "/api/canal-network", json={**payload, "selected_base_identity": "test-provider/base:two"}
    )
    assert calls["count"] == 3

    # Switching back to a previously selected base is a pure cache hit.
    web_client.post(
        "/api/canal-network", json={**payload, "selected_base_identity": "test-provider/base:test"}
    )
    assert calls["count"] == 3
