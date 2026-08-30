"""Contract tests for the canal-network API geometry cache."""

from collections.abc import Generator
from pathlib import Path

import networkx as nx
import pytest
from fastapi.testclient import TestClient

import pound.web.api as api_module
from pound.web.boat_hire import BOAT_HIRE_ENRICHMENT_FIELDS

from .conftest import build_web_client


@pytest.fixture
def dual_base_client(
    tmp_path: Path, route_graph: nx.Graph
) -> Generator[TestClient, None, None]:
    def row(location_id: str, latitude: str, longitude: str, osm_node_id: int) -> dict[str, str]:
        record = dict.fromkeys(BOAT_HIRE_ENRICHMENT_FIELDS, "")
        record.update(
            record_type="company_base",
            source_provider_id="test-provider",
            location_id=location_id,
            latitude=latitude,
            longitude=longitude,
            osm_url=f"https://www.openstreetmap.org/node/{osm_node_id}",
            exclude="",
        )
        return record

    rows = [
        row("base:test", "51.0", "-1.0", 1),
        row("base:two", "51.001", "-1.001", 2),
    ]
    yield from build_web_client(tmp_path, route_graph, boat_hire_rows=rows)


def test_identical_requests_compute_reachability_once(
    dual_base_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    calls = {"count": 0}
    original = api_module.select_boat_hire_reachability

    def counting(*args: object, **kwargs: object):
        calls["count"] += 1
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(api_module, "select_boat_hire_reachability", counting)

    first = dual_base_client.post("/api/canal-network", json={"days": 7, "hours_per_day": 6})
    second = dual_base_client.post("/api/canal-network", json={"days": 7, "hours_per_day": 6})

    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    assert calls["count"] == 1


def test_changed_constraints_compute_again(
    dual_base_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    calls = {"count": 0}
    original = api_module.select_boat_hire_reachability

    def counting(*args: object, **kwargs: object):
        calls["count"] += 1
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(api_module, "select_boat_hire_reachability", counting)

    dual_base_client.post("/api/canal-network", json={"days": 7, "hours_per_day": 6})
    dual_base_client.post("/api/canal-network", json={"days": 5, "hours_per_day": 6})

    assert calls["count"] == 2


def test_selected_identity_is_part_of_cache_key(
    dual_base_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    calls = {"count": 0}
    original = api_module.select_boat_hire_reachability

    def counting(*args: object, **kwargs: object):
        calls["count"] += 1
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(api_module, "select_boat_hire_reachability", counting)

    dual_base_client.post("/api/canal-network", json={"days": 7, "hours_per_day": 6})
    dual_base_client.post(
        "/api/canal-network",
        json={"days": 7, "hours_per_day": 6, "selected_base_identity": "test-provider/base:test"},
    )
    # A selected request reuses the cached union and computes only the cheap
    # single-anchor highlight (one extra reachability call).
    assert calls["count"] == 2

    # Repeating either request must hit the caches and add no calls.
    dual_base_client.post("/api/canal-network", json={"days": 7, "hours_per_day": 6})
    dual_base_client.post(
        "/api/canal-network",
        json={"days": 7, "hours_per_day": 6, "selected_base_identity": "test-provider/base:test"},
    )
    assert calls["count"] == 2


def test_switching_bases_only_computes_highlights(
    dual_base_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    calls = {"count": 0}
    original = api_module.select_boat_hire_reachability

    def counting(*args: object, **kwargs: object):
        calls["count"] += 1
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(api_module, "select_boat_hire_reachability", counting)
    payload = {"days": 7, "hours_per_day": 6}

    dual_base_client.post("/api/canal-network", json=payload)
    assert calls["count"] == 1

    dual_base_client.post(
        "/api/canal-network", json={**payload, "selected_base_identity": "test-provider/base:test"}
    )
    assert calls["count"] == 2

    dual_base_client.post(
        "/api/canal-network", json={**payload, "selected_base_identity": "test-provider/base:two"}
    )
    assert calls["count"] == 3

    # Switching back to a previously selected base is a pure cache hit.
    dual_base_client.post(
        "/api/canal-network", json={**payload, "selected_base_identity": "test-provider/base:test"}
    )
    assert calls["count"] == 3
