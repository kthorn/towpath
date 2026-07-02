import json
from pathlib import Path

import pytest

from pound.ingest.ir import NodeKind
from pound.ingest.osm import TAGS_FILTER_EXPR, read_pbf
from tests.fixtures import oxford_fixture_path

pytestmark = pytest.mark.bulk


def _tiny_pbf_path() -> Path:
    return Path(__file__).parent.parent / "fixtures" / "tiny_bulk.osm"


def test_tags_filter_expr_is_pinned():
    assert "w/waterway=canal" in TAGS_FILTER_EXPR
    assert "n/place" in TAGS_FILTER_EXPR
    # bare dimension-alias lines (would pull roads) must be absent
    assert "w/maxwidth" not in TAGS_FILTER_EXPR
    assert "w/bridge:movable" not in TAGS_FILTER_EXPR
    assert "w/waterway=lock_gate" not in TAGS_FILTER_EXPR


def test_read_pbf_populates_node_ids_and_features():
    feats = read_pbf(_tiny_pbf_path())
    assert feats.source == "geofabrik"
    # three routable ways; derelict dropped
    assert len(feats.ways) == 3
    assert all(w.node_ids for w in feats.ways)  # pyosmium gives way-node refs
    way_ids = {w.osm_id for w in feats.ways}
    assert way_ids == {1001, 1002, 1003}
    assert 1005 not in way_ids  # derelict filtered at read time


def test_read_pbf_captures_place_and_lock_gate_nodes():
    feats = read_pbf(_tiny_pbf_path())
    places = [n for n in feats.nodes if n.kind == NodeKind.PLACE]
    gates = [n for n in feats.nodes if n.kind == NodeKind.LOCK_GATE]
    assert {n.osm_id for n in places} == {1, 4}
    assert {n.osm_id for n in gates} == {5}


def test_tags_filter_round_trip_matches_overpass_shape(monkeypatch, tmp_path):
    """OQ-D1 divergence-fails-loudly: the filtered PBF reproduces the OVERPASS
    reader's WaterwayFeatures shape for the Oxford-equivalent fixture. Needs
    the osmium-tool CLI; gated by the bulk marker."""
    import shutil

    if shutil.which("osmium") is None:
        pytest.skip("osmium-tool CLI not installed")

    from pound.ingest.overpass import parse

    raw = json.loads(Path(oxford_fixture_path()).read_text())
    overpass_feats = parse(raw["elements"], None, osm_timestamp=raw["osm3s"]["timestamp_osm_base"])

    bulk_feats = read_pbf(_tiny_pbf_path())

    overpass_kinds = sorted({w.kind.value for w in overpass_feats.ways})
    bulk_kinds = sorted({w.kind.value for w in bulk_feats.ways})
    assert overpass_kinds == bulk_kinds
    overpass_places = {n.tags["name"] for n in overpass_feats.nodes if n.kind == NodeKind.PLACE}
    bulk_places = {n.tags["name"] for n in bulk_feats.nodes if n.kind == NodeKind.PLACE}
    assert overpass_places == bulk_places == {"Oxford", "Hayfield"}


def test_read_england_applies_prune_then_filter_chain(monkeypatch, tmp_path):
    """read_england wraps read_pbf output with prune -> filter_navigable_ways.
    read_pbf itself is unchanged. We monkeypatch run_tags_filter and read_pbf
    to avoid the osmium CLI and the PBF-format-despite-XML-content issue."""
    from pound.ingest import osm as _osm

    fixture_features = _osm.read_pbf(_tiny_pbf_path())

    # Patch run_tags_filter (no-op — not needed since read_pbf is also patched)
    monkeypatch.setattr(_osm, "run_tags_filter", lambda in_pbf, out_pbf: None)
    # Patch read_pbf to return fixture features regardless of the filtered path
    # (the filtered path has a .pbf extension but would contain XML — this avoids
    # the format-detection issue while still testing the chain wiring).
    monkeypatch.setattr(_osm, "read_pbf", lambda p: fixture_features.model_copy())

    stub_pbf = tmp_path / "stub.osm.pbf"
    stub_pbf.touch()

    # spy on chain functions (call through to real to preserve behaviour)
    real_prune = _osm.prune_non_navigable_infra
    real_filter = _osm.filter_navigable_ways
    called_prune = []
    called_filter = []

    def spy_prune(features):
        called_prune.append(features)
        return real_prune(features)

    def spy_filter(features):
        called_filter.append(features)
        return real_filter(features)

    monkeypatch.setattr(_osm, "prune_non_navigable_infra", spy_prune)
    monkeypatch.setattr(_osm, "filter_navigable_ways", spy_filter)

    out = _osm.read_england(stub_pbf)
    # chain functions were called
    assert len(called_prune) == 1
    assert len(called_filter) == 1
    # without any boat=no ways, output matches fixture
    assert {w.osm_id for w in out.ways} == {w.osm_id for w in fixture_features.ways}
