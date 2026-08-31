import pickle

import networkx as nx
from pound.artifact import ROUTING_ARTIFACT_SCHEMA_VERSION
from pound.models import WayDimensions
from pound_build.artifact import write_artifact

from scripts.benchmark_compact_artifact import _route_cases_from_legacy, benchmark_artifacts


def _write_artifact(path, revision: str, *, length_m: float = 100.0) -> None:
    graph = nx.Graph()
    graph.add_node(1, lat=51.0, lon=-1.0, movable_bridge_ids=())
    graph.add_node(2, lat=51.001, lon=-1.001, movable_bridge_ids=())
    graph.add_edge(
        1,
        2,
        osm_way_id=12,
        name="Test Canal",
        kind="canal",
        length_m=length_m,
        dimensions=WayDimensions(),
        has_tunnel=False,
        has_movable_bridge=False,
        locks=0,
        geometry=[(51.0, -1.0), (51.001, -1.001)],
        movable_bridge_ids=(),
        tunnel_restrictions=(),
        access_caveats=(),
        candidate_eligible=True,
    )
    write_artifact(
        graph,
        (),
        {},
        {
            "artifact_revision": revision,
            "source": "fixture",
            "fetched_at": "2026-08-30T00:00:00Z",
            "built_at": "2026-08-30T00:00:00Z",
            "validation": {},
            "poi_summary": {},
        },
        path,
    )


def _write_detailed_artifact(path) -> None:
    graph = nx.Graph()
    graph.add_node(1, lat=51.0, lon=-1.0, movable_bridge_ids=())
    graph.add_node(2, lat=51.0005, lon=-1.0005, movable_bridge_ids=())
    graph.add_node(3, lat=51.001, lon=-1.001, movable_bridge_ids=())
    for u, v, geometry in (
        (1, 2, [(51.0, -1.0), (51.0005, -1.0005)]),
        (2, 3, [(51.0005, -1.0005), (51.001, -1.001)]),
    ):
        graph.add_edge(
            u,
            v,
            osm_way_id=u * 10 + v,
            name="Test Canal",
            kind="canal",
            length_m=50.04,
            dimensions=WayDimensions(),
            has_tunnel=False,
            has_movable_bridge=False,
            locks=0,
            geometry=geometry,
            movable_bridge_ids=(),
            tunnel_restrictions=(),
            access_caveats=(),
        )
    with path.open("wb") as stream:
        pickle.dump(
            {
                "graph": graph,
                "pois": [],
                "gazetteer": {},
                "metadata": {
                    "artifact_schema_version": ROUTING_ARTIFACT_SCHEMA_VERSION,
                    "artifact_revision": "detailed",
                },
            },
            stream,
        )


def test_benchmark_report_has_required_sections(tmp_path):
    before = tmp_path / "before.pkl"
    after = tmp_path / "after.pkl"
    _write_artifact(before, "before")
    _write_artifact(after, "after")

    report = benchmark_artifacts(before, after)

    assert set(report) == {
        "artifact_bytes",
        "graph_pickle_bytes",
        "unpickle_seconds",
        "compatibility_check_seconds",
        "graph_index_seconds",
        "candidate_index_seconds",
        "poi_index_seconds",
        "startup_seconds",
        "peak_rss_kib",
        "nodes",
        "edges",
        "geometry_coordinates",
        "candidate_samples",
        "boat_hire_snaps",
        "route_parity",
    }


def test_legacy_route_cases_reuse_selected_source_nodes():
    assert _route_cases_from_legacy(
        [
            (
                "test-reach",
                {
                    "_source_start": [51.0, -1.0],
                    "_source_end": [51.001, -1.001],
                },
            )
        ]
    ) == (
        {
            "name": "test-reach",
            "start": (51.0, -1.0),
            "end": (51.001, -1.001),
        },
    )


def test_route_parity_ignores_contracted_leg_count(tmp_path):
    before = tmp_path / "before.pkl"
    after = tmp_path / "after.pkl"
    _write_detailed_artifact(before)
    _write_artifact(after, "after", length_m=100.08)

    report = benchmark_artifacts(
        before,
        after,
        route_cases=(
            {
                "name": "test-reach",
                "start": (51.0, -1.0),
                "end": (51.001, -1.001),
            },
        ),
    )

    parity = report["route_parity"]

    assert parity["all_match"] is True
    assert len(parity["cases"]) == 1
    case = parity["cases"][0]
    assert case["name"] == "test-reach"
    assert case["before"] == {
        "available": True,
        "source_distance_m": 100.08,
        "infrastructure": {"locks": 0},
        "restrictions": [],
    }
    assert case["after"] == case["before"]
    assert case["matches"] == {
        "availability": True,
        "source_distance": True,
        "infrastructure": True,
        "restrictions": True,
        "geometry_bound": True,
    }
    assert case["geometry_deviation_m"] <= 1.0
