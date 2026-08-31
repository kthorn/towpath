import pickle

import networkx as nx
import pytest
from pound.artifact import ROUTING_ARTIFACT_SCHEMA_VERSION
from pound.models import WayDimensions
from pound_build.artifact import write_artifact

import scripts.benchmark_compact_artifact as benchmark
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


def test_current_phase_builds_graph_index_without_candidate_index(tmp_path, monkeypatch):
    path = tmp_path / "artifact.pkl"
    _write_artifact(path, "artifact")
    from pound.graph import spatial

    original_graph_index = spatial.GraphSpatialIndex
    original_candidate_index = spatial.CandidateSpatialIndex
    graph_index_flags: list[bool] = []
    candidate_index_calls = 0

    def graph_index(graph, *, build_candidate_index: bool = True):
        graph_index_flags.append(build_candidate_index)
        return original_graph_index(graph, build_candidate_index=build_candidate_index)

    def candidate_index(graph):
        nonlocal candidate_index_calls
        candidate_index_calls += 1
        return original_candidate_index(graph)

    monkeypatch.setattr(spatial, "GraphSpatialIndex", graph_index)
    monkeypatch.setattr(spatial, "CandidateSpatialIndex", candidate_index)

    metrics, _ = benchmark._current_artifact_report(path)

    assert graph_index_flags == [False]
    assert candidate_index_calls == 1
    assert metrics["candidate_samples"] > 0


def _metrics(nodes: int) -> dict[str, float | int | None]:
    return {
        "artifact_bytes": nodes,
        "graph_pickle_bytes": nodes,
        "unpickle_seconds": 0.1,
        "compatibility_check_seconds": 0.2,
        "graph_index_seconds": 0.3,
        "candidate_index_seconds": 0.4,
        "poi_index_seconds": 0.5,
        "startup_seconds": None,
        "peak_rss_kib": nodes,
        "nodes": nodes,
        "edges": nodes,
        "geometry_coordinates": nodes,
        "candidate_samples": nodes,
    }


def test_benchmark_aggregates_independent_child_reports(monkeypatch, tmp_path):
    calls = []

    def current_report(path, *, catalog=None, enrichment=None, route_cases=()):
        calls.append((path, catalog, enrichment, tuple(route_cases)))
        return _metrics(1 if path.name == "before.pkl" else 2), []

    monkeypatch.setattr(benchmark, "_current_artifact_report_subprocess", current_report)

    report = benchmark_artifacts(
        tmp_path / "before.pkl", tmp_path / "after.pkl", catalog=tmp_path / "catalog.pkl"
    )

    assert calls == [
        (tmp_path / "before.pkl", None, None, ()),
        (tmp_path / "after.pkl", tmp_path / "catalog.pkl", None, ()),
    ]
    assert report["nodes"] == {"before": 1, "after": 2}
    assert report["peak_rss_kib"] == {"before": 1, "after": 2}


def test_unavailable_legacy_route_is_attempted_and_fails_if_new_route_is_available():
    case = {"name": "unavailable", "start": (51.0, -1.0), "end": (51.001, -1.001)}
    before = benchmark._unavailable_route_record(case)
    after = {
        "available": True,
        "source_distance_m": 100.0,
        "infrastructure": {"locks": 0},
        "restrictions": [],
        "_geometry": [[-1.0, 51.0], [-1.001, 51.001]],
    }

    route_cases = _route_cases_from_legacy([("unavailable", before)])
    parity = benchmark._route_parity([("unavailable", before)], [("unavailable", after)])

    assert route_cases == (case,)
    assert parity["cases"][0]["after"]["available"] is True
    assert parity["all_match"] is False


def test_route_parity_fails_for_a_missing_after_record():
    before = benchmark._unavailable_route_record(
        {"name": "unavailable", "start": (51.0, -1.0), "end": (51.001, -1.001)}
    )

    parity = benchmark._route_parity([("unavailable", before)], [])

    assert parity["all_match"] is False
    assert all(value is False for value in parity["cases"][0]["matches"].values())


def test_shared_snap_report_requires_base62_and_complete_identity_coverage():
    from pound_web.boat_hire import BoatHireSeed  # pyright: ignore[reportMissingImports]

    from scripts.verify_boat_hire_snaps import (  # pyright: ignore[reportMissingImports]
        build_boat_hire_snap_report,
    )

    base62 = BoatHireSeed("canal-holidays", "base:62", 51.0, -1.0)
    other = BoatHireSeed("provider", "base:one", 51.0, -1.0)
    entry = {
        "identity": base62.identity,
        "old_edge": [1, 2],
        "old_snap_distance_m": 0.0,
        "new_edge": [3, 4],
        "new_snap_distance_m": 0.0,
    }

    with pytest.raises(ValueError, match="base:62"):
        build_boat_hire_snap_report((other,), ())
    with pytest.raises(ValueError, match="identity coverage"):
        build_boat_hire_snap_report((base62, other), (entry,))


def test_fallback_snap_report_requires_base62_and_old_identity_coverage(tmp_path, monkeypatch):
    from pound_web import boat_hire  # pyright: ignore[reportMissingImports]
    from pound_web.boat_hire import BoatHireSeed  # pyright: ignore[reportMissingImports]

    after = tmp_path / "after.pkl"
    _write_artifact(after, "after")
    base62 = BoatHireSeed("canal-holidays", "base:62", 51.0, -1.0)
    other = BoatHireSeed("provider", "base:one", 51.0, -1.0)
    old_base62 = {
        "identity": base62.identity,
        "edge": [1, 2],
        "snap_distance_m": 0.0,
    }

    monkeypatch.setattr(boat_hire, "load_boat_hire_seeds", lambda _path: (other,))
    with pytest.raises(ValueError, match="base:62"):
        benchmark._combined_boat_hire_report((), after, tmp_path / "seeds.csv")

    monkeypatch.setattr(boat_hire, "load_boat_hire_seeds", lambda _path: (base62, other))
    with pytest.raises(ValueError, match="identity coverage"):
        benchmark._combined_boat_hire_report((old_base62,), after, tmp_path / "seeds.csv")


@pytest.mark.parametrize(
    ("route_match", "snap_key"),
    [
        (False, None),
        (True, "old_threshold_breaches"),
        (True, "threshold_breaches"),
        (True, "required_exception_changes"),
    ],
)
def test_benchmark_command_fails_for_semantic_or_snap_failures(
    monkeypatch, tmp_path, route_match, snap_key
):
    snaps = {
        "old_threshold_breaches": [],
        "threshold_breaches": [],
        "required_exception_changes": [],
    }
    if snap_key is not None:
        snaps[snap_key] = ["provider/base:one"]
    monkeypatch.setattr(
        benchmark,
        "benchmark_artifacts",
        lambda *_args, **_kwargs: {
            "route_parity": {"all_match": route_match},
            "boat_hire_snaps": snaps,
        },
    )

    assert (
        benchmark.main(
            ["--before", str(tmp_path / "before.pkl"), "--after", str(tmp_path / "after.pkl")]
        )
        == 1
    )
