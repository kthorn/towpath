import pickle
from dataclasses import FrozenInstanceError
from pathlib import Path

import networkx as nx
import pytest

import pound.graph.artifact as artifact_module
from pound.graph.artifact import (
    GraphArtifact,
    InvalidArtifactError,
    load_artifact,
    prepare_artifact,
    save_artifact,
    write_artifact,
)
from pound.ingest.ir import PointOfInterest


def _graph() -> nx.Graph:
    graph = nx.Graph()
    graph.add_node(0, lat=51.7520, lon=-1.2577, osm_node_ids={"100"})
    graph.add_node(1, lat=51.7520, lon=-1.2560, osm_node_ids={"101"})
    graph.add_edge(
        0,
        1,
        osm_way_id=200,
        name="Oxford Canal",
        kind="canal",
        length_m=117.0,
        dimensions=None,
        has_tunnel=False,
        has_movable_bridge=False,
        locks=0,
        geometry=[(51.7520, -1.2577), (51.7520, -1.2560)],
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


def _write(path: Path, payload: dict) -> None:
    with path.open("wb") as stream:
        pickle.dump(payload, stream)


def _valid_payload() -> dict:
    return {"graph": _graph(), "pois": [_poi()], "metadata": _metadata()}


def _assert_rebuild_error(path: Path, match: str) -> None:
    with pytest.raises(InvalidArtifactError, match=match) as exc_info:
        load_artifact(path)
    assert "rebuild" in str(exc_info.value).lower()


def test_save_and_load_return_frozen_graph_artifact_with_parsed_pois(tmp_path: Path):
    path = tmp_path / "graph.pkl"

    save_artifact(_graph(), [_poi()], path, _metadata())

    artifact = load_artifact(path)
    assert isinstance(artifact, GraphArtifact)
    assert artifact.graph.number_of_edges() == 1
    assert artifact.pois == (PointOfInterest.model_validate(_poi()),)
    assert artifact.metadata == _metadata()
    with pytest.raises(FrozenInstanceError):
        artifact.pois = ()


def test_save_serializes_exact_top_level_keys_and_generates_one_revision(
    tmp_path: Path, monkeypatch
):
    path = tmp_path / "graph.pkl"
    revisions = iter(["generated-revision", AssertionError("uuid4 called twice")])
    monkeypatch.setattr(artifact_module, "uuid4", lambda: next(revisions))
    metadata = _metadata()
    del metadata["artifact_revision"]

    save_artifact(_graph(), [_poi()], path, metadata)

    with path.open("rb") as stream:
        payload = pickle.load(stream)
    assert set(payload) == {"graph", "pois", "metadata"}
    assert payload["metadata"]["artifact_revision"] == "generated-revision"
    assert payload["pois"] == [PointOfInterest.model_validate(_poi())]


def test_validated_poi_instance_is_not_dumped_or_reparsed(monkeypatch):
    poi = PointOfInterest.model_validate(_poi())
    monkeypatch.setattr(
        PointOfInterest,
        "model_dump",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("dumped POI")),
    )

    artifact = GraphArtifact(graph=_graph(), pois=(poi,), metadata=_metadata())

    assert artifact.pois[0] is poi


def test_prepare_and_write_artifact_split_validation_from_serialization(tmp_path: Path):
    path = tmp_path / "graph.pkl"

    artifact = prepare_artifact(_graph(), [_poi()], _metadata())
    write_artifact(artifact, path)

    assert isinstance(artifact, GraphArtifact)
    loaded = load_artifact(path)
    assert nx.utils.graphs_equal(loaded.graph, artifact.graph)
    assert loaded.pois == artifact.pois
    assert loaded.metadata == artifact.metadata


@pytest.mark.parametrize("keys", [{"graph", "metadata"}, {"graph", "pois", "metadata", "x"}])
def test_load_rejects_nonexact_top_level_keys(tmp_path: Path, keys: set[str]):
    path = tmp_path / "graph.pkl"
    payload = _valid_payload()
    _write(path, {key: payload.get(key) for key in keys})

    _assert_rebuild_error(path, "top-level keys")


@pytest.mark.parametrize("missing", sorted(_metadata()))
def test_load_requires_every_metadata_field(tmp_path: Path, missing: str):
    path = tmp_path / "graph.pkl"
    payload = _valid_payload()
    del payload["metadata"][missing]
    _write(path, payload)

    _assert_rebuild_error(path, missing)


def test_load_rejects_unexpected_metadata_fields(tmp_path: Path):
    path = tmp_path / "graph.pkl"
    payload = _valid_payload()
    payload["metadata"]["version"] = 1
    _write(path, payload)

    _assert_rebuild_error(path, "metadata fields")


@pytest.mark.parametrize("graph", [nx.DiGraph(), nx.MultiGraph(), "not a graph"])
def test_load_rejects_directed_or_non_graph_payloads(tmp_path: Path, graph):
    path = tmp_path / "graph.pkl"
    payload = _valid_payload()
    payload["graph"] = graph
    _write(path, payload)

    _assert_rebuild_error(path, "graph")


@pytest.mark.parametrize(
    ("where", "attribute"),
    [("node", "lat"), ("node", "lon"), ("node", "osm_node_ids"), ("edge", "geometry")],
)
def test_load_rejects_missing_required_graph_attributes(
    tmp_path: Path, where: str, attribute: str
):
    path = tmp_path / "graph.pkl"
    payload = _valid_payload()
    data = payload["graph"].nodes[0] if where == "node" else payload["graph"].edges[0, 1]
    del data[attribute]
    _write(path, payload)

    _assert_rebuild_error(path, attribute)


@pytest.mark.parametrize("geometry", [[], [(51.0, -1.0)], [(float("nan"), -1.0)], ["bad", "data"]])
def test_load_rejects_malformed_edge_geometry(tmp_path: Path, geometry):
    path = tmp_path / "graph.pkl"
    payload = _valid_payload()
    payload["graph"].edges[0, 1]["geometry"] = geometry
    _write(path, payload)

    _assert_rebuild_error(path, "geometry")


def test_load_rejects_duplicate_poi_identities(tmp_path: Path):
    path = tmp_path / "graph.pkl"
    payload = _valid_payload()
    payload["pois"].append(_poi(name="Duplicate"))
    _write(path, payload)

    _assert_rebuild_error(path, "duplicate")


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"nearest_edge": (0, 2)}, "nearest_edge"),
        ({"nearest_edge": (1, 0)}, "canonical"),
        ({"nearest_node_uid": 2}, "nearest_node_uid"),
    ],
)
def test_load_rejects_bad_poi_attachments(tmp_path: Path, change: dict, match: str):
    path = tmp_path / "graph.pkl"
    payload = _valid_payload()
    payload["pois"][0].update(change)
    _write(path, payload)

    _assert_rebuild_error(path, match)


def test_load_rejects_attachment_to_non_navigable_edge(tmp_path: Path):
    path = tmp_path / "graph.pkl"
    payload = _valid_payload()
    payload["graph"].edges[0, 1]["boat"] = "no"
    _write(path, payload)

    _assert_rebuild_error(path, "navigable")


@pytest.mark.parametrize(
    ("category", "distance"),
    [
        ("canal_service", 250.01),
        ("pedestrian_access", 250.01),
        ("provisions", 1000.01),
        ("transport", 1000.01),
    ],
)
def test_load_rejects_poi_distances_over_category_corridor(
    tmp_path: Path, category: str, distance: float
):
    path = tmp_path / "graph.pkl"
    payload = _valid_payload()
    payload["pois"][0].update(category=category, nearest_waterway_distance_m=distance)
    _write(path, payload)

    _assert_rebuild_error(path, "distance")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("lat", float("nan")),
        ("lon", float("inf")),
        ("projected_lat", -91.0),
        ("projected_lon", 181.0),
        ("nearest_waterway_distance_m", float("nan")),
    ],
)
def test_load_rejects_nonfinite_or_out_of_bounds_values(
    tmp_path: Path, field: str, value: float
):
    path = tmp_path / "graph.pkl"
    payload = _valid_payload()
    payload["pois"][0][field] = value
    _write(path, payload)

    _assert_rebuild_error(path, field)


def test_load_rejects_unexpected_poi_fields(tmp_path: Path):
    path = tmp_path / "graph.pkl"
    payload = _valid_payload()
    payload["pois"][0]["unexpected"] = True
    _write(path, payload)

    _assert_rebuild_error(path, "unexpected")


def test_load_rejects_projection_more_than_one_centimetre_from_edge(tmp_path: Path):
    path = tmp_path / "graph.pkl"
    payload = _valid_payload()
    payload["pois"][0]["projected_lat"] = 51.7530
    _write(path, payload)

    _assert_rebuild_error(path, "projected")


def test_load_wraps_invalid_pickle_with_rebuild_guidance(tmp_path: Path):
    path = tmp_path / "graph.pkl"
    path.write_bytes(b"not a pickle")

    _assert_rebuild_error(path, "pickle")


def test_explicit_revision_is_preserved_without_generating_one(tmp_path: Path, monkeypatch):
    path = tmp_path / "graph.pkl"
    monkeypatch.setattr(
        artifact_module,
        "uuid4",
        lambda: (_ for _ in ()).throw(AssertionError("uuid4 should not be called")),
    )

    save_artifact(_graph(), [_poi()], path, _metadata())

    assert load_artifact(path).metadata["artifact_revision"] == "revision-1"
