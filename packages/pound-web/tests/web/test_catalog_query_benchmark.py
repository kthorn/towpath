import json
from pathlib import Path

import networkx as nx
import pytest
from pound.catalog.spatial import CatalogSpatialIndex
from pound.graph.spatial import GraphSpatialIndex
from pound_web.boat_hire import load_boat_hire_seeds
from pound_web.places import PlacesIndex

from scripts.catalog_query_benchmark import (
    MAX_QUERY_WORK,
    build_benchmark_cases,
    result_payload,
)

from .conftest import catalog_place, write_boat_hire_enrichment


class _CandidateCounter:
    def __init__(self, counts: dict[str, int]):
        self.counts = counts

    def viewport_candidate_count(self, bounds) -> int:
        return self.counts[f"{bounds.south}:{bounds.west}:{bounds.north}:{bounds.east}"]


class _BenchmarkPlacesIndex:
    def __init__(self, catalog_index):
        self.catalog_index = catalog_index


@pytest.fixture
def places_index(tmp_path: Path) -> PlacesIndex:
    graph_index = GraphSpatialIndex(nx.Graph())
    catalog_index = CatalogSpatialIndex(
        (catalog_place("pub", 1, 51.0, -1.0),),
        graph_index,
    )
    seeds = load_boat_hire_seeds(write_boat_hire_enrichment(tmp_path / "boat-hire-enrichment.csv"))
    return PlacesIndex(catalog_index, graph_index, seeds)


def test_benchmark_builds_nearby_point_line_and_batch_cases(places_index):
    cases = build_benchmark_cases(places_index)

    assert {case.name for case in cases} >= {
        "nearby-point",
        "nearby-line",
        "nearby-multi-target",
    }


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

    first = build_benchmark_cases(_BenchmarkPlacesIndex(counter))
    second = build_benchmark_cases(_BenchmarkPlacesIndex(counter))

    first_payload = [case.request.model_dump(mode="json") for case in first]
    second_payload = [case.request.model_dump(mode="json") for case in second]
    assert first_payload == second_payload
    assert [case.name for case in first] == [
        "densest_predefined_viewport",
        "locality_no_policy",
        "nearby-line",
        "nearby-multi-target",
        "nearby-point",
        "route_day",
        "waterway",
    ]
    assert first[0].candidate_count == 101
    assert first[0].viewport_name == "manchester"
    assert first[0].candidate_count <= MAX_QUERY_WORK
    assert first[1].request.policy.basis == "none"
    assert first[5].request.policy.basis == "route"
    assert first[5].request.day_geometry is not None
    assert first[6].request.policy.basis == "waterway"


def test_result_payload_uses_outcome_not_over_cap():
    row = result_payload(
        candidate_work=17,
        outcome="ok",
        result_count=4,
        latencies_ms=[3.0, 1.0, 2.0, 4.0],
        rss_kib=123,
    )

    assert "matching_count" not in row
    assert "over_cap" not in row
    assert row["result_count"] == 4
    assert set(row) >= {"candidate_work", "p50_ms", "p95_ms", "max_ms", "outcome"}
    assert json.dumps({"nearby-point": row}, sort_keys=True)
