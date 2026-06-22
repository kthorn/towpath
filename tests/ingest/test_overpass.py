import json
from pathlib import Path

import pytest

from pound.ingest.ir import NodeKind, WaterwayKind
from pound.ingest.overpass import OXFORD_BBOX, build_query, parse

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


def test_parse_geometry_carried_through():
    feats = parse(load_fixture()["elements"], OXFORD_BBOX)
    w = next(w for w in feats.ways if w.osm_id == 1001)
    assert len(w.geometry) == 3
    assert w.geometry[0] == (pytest.approx(51.75), pytest.approx(-1.26))
