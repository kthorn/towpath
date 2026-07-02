import json
from pathlib import Path

import pytest

from pound.ingest.ir import NodeKind, WaterwayKind
from pound.ingest.overpass import OXFORD_BBOX, build_query, fetch_oxford, parse
from tests.fixtures import oxford_fixture_path

FIXTURE = Path(__file__).parent.parent / "fixtures" / "oxford_overpass_sample.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_build_query_contains_bbox_and_filters():
    q = build_query((51.70, -1.35, 51.80, -1.20))
    assert "[out:json]" in q
    assert "(51.7,-1.35,51.8,-1.2)" in q
    assert "waterway" in q
    assert "lock_gate" in q
    assert "out geom;" in q


def test_parse_keeps_canal_ways():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    canal_ids = {w.osm_id for w in feats.ways if w.kind == WaterwayKind.CANAL}
    assert 1001 in canal_ids
    assert 1002 in canal_ids
    assert 1006 in canal_ids


def test_parse_keeps_lock_way():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    lock_ways = [w for w in feats.ways if w.kind == WaterwayKind.LOCK]
    assert any(w.osm_id == 1003 for w in lock_ways)


def test_parse_excludes_derelict():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    ids = {w.osm_id for w in feats.ways}
    assert 1004 not in ids  # disused:waterway
    assert 1005 not in ids  # waterway=derelict_canal


def test_parse_extracts_dimensions():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    w = next(w for w in feats.ways if w.osm_id == 1002)
    assert w.dimensions.max_beam_m == pytest.approx(2.1)
    assert w.dimensions.max_draft_m == pytest.approx(0.9)
    assert w.dimensions.max_height_m is None


def test_parse_flags_tunnel():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    w = next(w for w in feats.ways if w.osm_id == 1006)
    assert w.has_tunnel is True


def test_parse_keeps_lock_gate_and_lock_nodes():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    kinds = {n.kind for n in feats.nodes}
    assert NodeKind.LOCK_GATE in kinds
    assert NodeKind.LOCK in kinds


def test_parse_keeps_mooring_node():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    assert any(n.kind == NodeKind.MOORING for n in feats.nodes)


def test_parse_excludes_amenity_pub_node():
    """Amenity POIs (pub/shop/etc.) are a later ingest step — parse must drop them."""
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    assert not any("amenity" in n.tags and n.tags["amenity"] == "pub" for n in feats.nodes)


def test_parse_sets_source_and_bbox():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX, source="overpass")
    assert feats.source == "overpass"
    assert feats.bbox == OXFORD_BBOX
    assert feats.fetched_at  # non-empty ISO timestamp


def test_fetch_oxford_applies_prune_then_filter_chain(monkeypatch):
    """fetch_oxford wraps parse() output with prune -> filter_navigable_ways.
    parse() itself stays pure. We monkeypatch fetch_raw (the network call) so
    the chain runs on a fixture without hitting live Overpass."""
    from pound.ingest import overpass as _overpass

    raw = json.loads(Path(oxford_fixture_path()).read_text())
    # inject a boat=no way into the fixture's elements (so the filter has work to do)
    boat_no_way = {
        "type": "way",
        "id": 9999,
        "tags": {"waterway": "canal", "boat": "no"},
        "geometry": [{"lat": 51.7510, "lon": -1.2600}, {"lat": 51.7520, "lon": -1.2600}],
    }
    raw["elements"].append(boat_no_way)
    monkeypatch.setattr(_overpass, "fetch_raw", lambda *a, **kw: raw)

    # spy on chain functions (call through to real to preserve behaviour)
    real_prune = _overpass.prune_non_navigable_infra
    real_filter = _overpass.filter_navigable_ways
    called_prune = []
    called_filter = []

    def spy_prune(features):
        called_prune.append(features)
        return real_prune(features)

    def spy_filter(features):
        called_filter.append(features)
        return real_filter(features)

    monkeypatch.setattr(_overpass, "prune_non_navigable_infra", spy_prune)
    monkeypatch.setattr(_overpass, "filter_navigable_ways", spy_filter)

    features = fetch_oxford()
    # the boat=no way must be gone
    assert 9999 not in {w.osm_id for w in features.ways}
    # chain functions were called
    assert len(called_prune) == 1
    assert len(called_filter) == 1
    # fetch_oxford still returns a WaterwayFeatures
    assert features.source == "overpass"


def test_parse_geometry_carried_through():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    w = next(w for w in feats.ways if w.osm_id == 1001)
    assert len(w.geometry) == 3
    assert w.geometry[0] == (pytest.approx(51.75), pytest.approx(-1.26))
