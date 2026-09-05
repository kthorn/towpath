"""Offline ingest to serialized artifact to complete branch-route collection."""

import copy

from pound.graph.artifact import load_artifact, save_artifact
from pound.ingest.cli import _build_graph_phases
from pound.ingest.overpass import parse
from pound.ingest.profile import BuildProfiler
from pound.route.round_trip import discover_round_trips
from pound.schemas import TurnaroundCandidatesRequest


def test_osm_build_and_reload_routes_to_precise_winding_holes(tmp_path):
    elements = [
        {
            "type": "way",
            "id": 10,
            "tags": {"waterway": "canal", "name": "Stem"},
            "geometry": [{"lat": 51, "lon": -1.01}, {"lat": 51, "lon": -1}],
        },
        {
            "type": "way",
            "id": 20,
            "tags": {"waterway": "canal", "name": "North"},
            "geometry": [{"lat": 51, "lon": -1}, {"lat": 51.01, "lon": -1}],
        },
        {
            "type": "way",
            "id": 30,
            "tags": {"waterway": "canal", "name": "South"},
            "geometry": [{"lat": 51, "lon": -1}, {"lat": 50.99, "lon": -1}],
        },
        {
            "type": "node",
            "id": 200,
            "lat": 51.005,
            "lon": -1,
            "tags": {"waterway": "turning_point", "name": "North hole"},
        },
        {
            "type": "node",
            "id": 300,
            "lat": 50.995,
            "lon": -1,
            "tags": {"waterway": "turning_point", "name": "South hole"},
        },
    ]
    features = parse(elements, None, osm_timestamp="2026-09-05T00:00:00Z")
    graph, _ = _build_graph_phases(features, BuildProfiler())
    assert len(graph.graph["turnarounds"]) == 3  # two holes and the assumed junction
    metadata = dict(
        artifact_revision="fixture",
        source="overpass",
        fetched_at=features.fetched_at,
        built_at=features.fetched_at,
        validation={},
        poi_summary={},
    )
    file = tmp_path / "graph.pkl"
    save_artifact(graph, [], file, metadata)
    loaded = load_artifact(file)
    before = copy.deepcopy(loaded.graph.graph)
    origin = next(uid for uid, node in graph.nodes(data=True) if node["lon"] == -1.01)
    result = discover_round_trips(
        TurnaroundCandidatesRequest(
            artifact_revision="fixture",
            start_uid=origin,
            days=1,
            hours_per_day=6,
        ),
        graph=loaded.graph,
    )
    assert {r.turnaround.display_name for r in result.routes} == {"North hole", "South hole"}
    for route in result.routes:
        coordinates = route.journey.geometry.coordinates
        assert coordinates == coordinates[::-1]
        assert len(coordinates) == 5
        assert coordinates[2] == (route.turnaround.coordinate.lon, route.turnaround.coordinate.lat)
        assert route.turnaround.sources[0]["attribution"]
    assert loaded.graph.graph == before
