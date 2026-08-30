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
    # A selected request computes the union and the focused highlight (two calls);
    # a changed identity is a different cache key, so both must recompute.
    assert calls["count"] == 3

    # Repeating either request must hit the cache and add no calls.
    web_client.post("/api/canal-network", json={"days": 7, "hours_per_day": 6})
    web_client.post(
        "/api/canal-network",
        json={"days": 7, "hours_per_day": 6, "selected_base_identity": "test-provider/base:test"},
    )
    assert calls["count"] == 3
