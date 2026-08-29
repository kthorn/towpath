import json

import networkx as nx

from pound.catalog.spatial import CatalogSpatialIndex
from pound.graph.spatial import GraphSpatialIndex
from pound.schemas import MapBounds
from scripts.catalog_query_benchmark import (
    MAX_QUERY_WORK,
    _request,
    _result_signature,
    build_benchmark_cases,
    result_payload,
)
from tests.web.conftest import catalog_place


class _CandidateCounter:
    def __init__(self, counts: dict[str, int]):
        self.counts = counts

    def viewport_candidate_count(self, bounds) -> int:
        return self.counts[f"{bounds.south}:{bounds.west}:{bounds.north}:{bounds.east}"]


def test_benchmark_cases_are_deterministic_and_include_required_contracts():
    counter = _CandidateCounter(
        {
            "51.7:-1.4:51.9:-1.1": 12,
            "52.0:-0.9:52.2:-0.6": 23,
            "51.3:-0.6:51.7:0.3": 88,
            "52.3:-2.1:52.6:-1.6": MAX_QUERY_WORK + 1,
            "53.3:-2.6:53.7:-1.9": 101,
        }
    )

    first = build_benchmark_cases("catalog-test", counter)
    second = build_benchmark_cases("catalog-test", counter)

    first_payload = [case.request.model_dump(mode="json") for case in first]
    second_payload = [case.request.model_dump(mode="json") for case in second]
    assert first_payload == second_payload
    assert [case.name for case in first] == [
        "densest_predefined_viewport",
        "locality_no_policy",
        "route_day",
        "waterway",
    ]
    assert first[0].candidate_count == 101
    assert first[0].viewport_name == "manchester"
    assert first[0].candidate_count <= MAX_QUERY_WORK
    assert first[1].request.policy.basis == "none"
    assert first[2].request.policy.basis == "route"
    assert first[2].request.day == 2
    assert first[3].request.policy.basis == "waterway"


def test_benchmark_signature_uses_source_viewport_adapter():
    place = catalog_place("pub", 1, 51.0, -1.0)
    index = CatalogSpatialIndex((place,), GraphSpatialIndex(nx.Graph()))
    request = _request(
        "catalog-test",
        bounds=MapBounds(south=50.9, west=-1.1, north=51.1, east=-0.9),
        kinds=["pub"],
        policy={"basis": "none", "radius_m": None},
    )

    assert _result_signature(index, request) == (1, False, (place.identity,))


def test_result_payload_is_sorted_json_with_required_latency_fields():
    payload = result_payload(
        candidate_count=17,
        matching_count=4,
        over_cap=False,
        latencies_ms=[3.0, 1.0, 2.0, 4.0],
        rss_kib=123,
    )

    assert list(payload) == [
        "candidate_count",
        "matching_count",
        "max_ms",
        "over_cap",
        "p50_ms",
        "p95_ms",
        "rss_kib",
    ]
    assert payload["candidate_count"] == 17
    assert payload["matching_count"] == 4
    assert payload["over_cap"] is False
    assert payload["p50_ms"] == 2.5
    assert payload["p95_ms"] == 3.85
    assert payload["max_ms"] == 4.0
    assert json.dumps({"route_day": payload}, sort_keys=True)
