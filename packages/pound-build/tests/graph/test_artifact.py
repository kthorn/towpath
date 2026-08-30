import pickle
from pathlib import Path

import networkx as nx
import pound_build.artifact as artifact_module
import pytest  # pyright: ignore[reportMissingImports]
from pound.artifact import (  # pyright: ignore[reportMissingImports]
    InvalidArtifactError,
    RuntimeArtifact,
    load_artifact,
)
from pound.models import (  # pyright: ignore[reportMissingImports]
    AccessCaveat,
    RuntimePoi,
    WayDimensions,
)
from pound_build.artifact import _prepare_build_artifact, prepare_artifact, write_artifact
from pound_build.ingest.ir import PointOfInterest


def _graph() -> nx.Graph:
    graph = nx.Graph()
    graph.add_node(0, lat=51.7520, lon=-1.2577, osm_node_ids={"100"}, movable_bridge_ids=())
    graph.add_node(1, lat=51.7520, lon=-1.2560, osm_node_ids={"101"}, movable_bridge_ids=())
    graph.add_edge(
        0,
        1,
        osm_way_id=200,
        name="Oxford Canal",
        kind="canal",
        length_m=117.0,
        dimensions=WayDimensions(),
        has_tunnel=False,
        has_movable_bridge=False,
        locks=0,
        geometry=[(51.7520, -1.2577), (51.7520, -1.2560)],
        movable_bridge_ids=(),
        tunnel_restrictions=(),
        access_caveats=(),
    )
    return graph


def _poi(**overrides) -> dict:
    values = {
        "osm_type": "node",
        "osm_id": 300,
        "category": "canal_service",
        "kind": "water_point",
        "name": "Tap",
        "lat": 51.7520,
        "lon": -1.2568,
        "source_tags": {"amenity": "drinking_water"},
        "geometry_source": "point",
        "nearest_waterway_distance_m": 0.0,
        "nearest_edge": (0, 1),
        "nearest_node_uid": 1,
        "projected_lat": 51.7520,
        "projected_lon": -1.2568,
    }
    values.update(overrides)
    return values


def _metadata(**overrides) -> dict:
    values = {
        "artifact_revision": "revision-1",
        "source": "overpass",
        "fetched_at": "2026-07-12T00:00:00Z",
        "built_at": "2026-07-12T01:00:00Z",
        "validation": {"self_loops": 0},
        "poi_summary": {"retained": 1},
    }
    values.update(overrides)
    return values


def test_prepare_converts_build_pois_to_durable_runtime_records():
    artifact = prepare_artifact(_graph(), [_poi()], {}, _metadata())

    assert isinstance(artifact, RuntimeArtifact)
    assert artifact.pois == (
        RuntimePoi(
            osm_type="node",
            osm_id=300,
            category="canal_service",
            kind="water_point",
            name="Tap",
            lat=51.7520,
            lon=-1.2568,
        ),
    )
    assert artifact.metadata["artifact_schema_version"] == 1


def test_write_publishes_runtime_payload_for_core_loader(tmp_path: Path):
    path = tmp_path / "graph.pkl"
    artifact = prepare_artifact(_graph(), [_poi()], {"Oxford": (51.752, -1.257)}, _metadata())

    write_artifact(artifact, path)

    with path.open("rb") as stream:
        payload = pickle.load(stream)
    assert set(payload) == {"graph", "pois", "gazetteer", "metadata"}
    loaded = load_artifact(path)
    assert nx.utils.graphs_equal(loaded.graph, artifact.graph)
    assert loaded.pois == artifact.pois
    assert loaded.gazetteer == artifact.gazetteer
    assert loaded.metadata == artifact.metadata


@pytest.mark.parametrize(
    ("graph", "pois", "match"),
    [
        (nx.DiGraph(), [_poi()], "graph"),
        (_graph(), [_poi(nearest_edge=(0, 2))], "nearest_edge"),
        (_graph(), [_poi(), _poi(name="duplicate")], "duplicate"),
    ],
)
def test_prepare_rejects_invalid_build_inputs(graph, pois, match):
    with pytest.raises(InvalidArtifactError, match=match):
        prepare_artifact(graph, pois, {}, _metadata())


def test_prepare_rejects_invalid_access_caveat():
    graph = _graph()
    graph.edges[0, 1]["access_caveats"] = (AccessCaveat(0, "boat", "discouraged", "discouraged"),)

    with pytest.raises(InvalidArtifactError, match="access_caveat"):
        prepare_artifact(graph, [_poi()], {}, _metadata())


@pytest.mark.parametrize("version", [True, 1.0])
def test_prepare_rejects_non_integer_schema_version(version):
    with pytest.raises(InvalidArtifactError, match="artifact_schema_version"):
        prepare_artifact(_graph(), [], {}, _metadata(artifact_schema_version=version))


@pytest.mark.parametrize(
    "gazetteer",
    [
        {1: (51.0, -1.0)},
        {"Oxford": "not a coordinate"},
        {"Oxford": (float("nan"), -1.0)},
        {"Oxford": (51.0, float("inf"))},
        {"Oxford": [(51.0, -1.0)]},
        {"Oxford": [(51.0, -1.0), (52.0, "bad")]},
    ],
)
def test_prepare_rejects_invalid_gazetteer(gazetteer):
    with pytest.raises(InvalidArtifactError, match="gazetteer"):
        prepare_artifact(_graph(), [], gazetteer, _metadata())


def test_prepare_accepts_duplicate_name_gazetteer():
    gazetteer = {"Oxford": [(51.0, -1.0), (52.0, -2.0)]}

    artifact = prepare_artifact(_graph(), [], gazetteer, _metadata())

    assert artifact.gazetteer == gazetteer


def test_prepare_generates_revision_once_when_absent(monkeypatch):
    monkeypatch.setattr(artifact_module, "uuid4", lambda: "generated-revision")
    metadata = _metadata()
    del metadata["artifact_revision"]

    artifact = prepare_artifact(_graph(), [_poi()], {}, metadata)

    assert artifact.metadata["artifact_revision"] == "generated-revision"


def test_trusted_build_poi_instance_is_accepted_without_revalidation(monkeypatch):
    poi = PointOfInterest.model_validate(_poi())
    monkeypatch.setattr(
        PointOfInterest,
        "model_dump",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("dumped POI")),
    )

    artifact = _prepare_build_artifact(_graph(), (poi,), {}, _metadata())

    assert artifact.pois[0].osm_id == poi.osm_id
