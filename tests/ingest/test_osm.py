import json
from pathlib import Path

import pytest
from shapely import wkt

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
    for clause in (
        'nwr/waterway=water_point',
        'nwr/amenity=pub,cafe,restaurant,fuel,sanitary_dump_station,taxi',
        'nwr/shop=supermarket,convenience,bakery,greengrocer,butcher,deli,general',
        'nwr/highway=footway,path,pedestrian,steps,bus_stop',
    ):
        assert clause in TAGS_FILTER_EXPR
    assert "amenity=drinking_water" not in TAGS_FILTER_EXPR
    assert "amenity=toilets" not in TAGS_FILTER_EXPR
    assert "amenity=shower" not in TAGS_FILTER_EXPR


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
    assert {n.osm_id for n in places} == {1, 4, 6}
    assert {n.osm_id for n in gates} == {5}


def test_read_pbf_emits_bulk_pois_with_area_assembly_and_deduplication():
    feats = read_pbf(_tiny_pbf_path())
    identities = [(str(p.osm_type), p.osm_id, p.kind) for p in feats.poi_candidates]
    assert identities == [
        ("node", 2001, "water_point"), ("node", 2002, "pub"),
        ("node", 2003, "supermarket"), ("node", 2004, "rail_station"),
        ("node", 2005, "bus_stop"), ("node", 2006, "entrance"),
        ("node", 2007, "gate"), ("relation", 2301, "fuel"),
        ("way", 2101, "marina"), ("way", 2102, "cafe"),
        ("way", 2103, "path_connection"),
    ]
    geometries = {p.osm_id: wkt.loads(p.geometry_wkt).geom_type for p in feats.poi_candidates}
    assert geometries[2001] == "Point"
    assert geometries[2101] == geometries[2301] == "Polygon"
    assert geometries[2103] == "LineString"
    assert not any(p.osm_id in {2008, 2010, 2011, 2012} for p in feats.poi_candidates)
    assert feats.poi_ingest_report.skipped_examples["incomplete_relation_geometry"] == [
        "relation/2302"
    ]
    assert not any(p.osm_id == 2302 for p in feats.poi_candidates)


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
    assert overpass_places == bulk_places == {"Oxford", "Hayfield", "Marston"}


def test_bulk_poi_candidates_match_overpass_after_source_fields_are_excluded():
    from pound.ingest.overpass import parse

    fixture = Path(__file__).parent.parent / "fixtures" / "poi_overpass_sample.json"
    overpass = parse(json.loads(fixture.read_text())["elements"], None)
    bulk = read_pbf(_tiny_pbf_path())

    def source_neutral(candidate):
        return (
            str(candidate.osm_type), candidate.osm_id, str(candidate.category), candidate.kind,
            candidate.name, candidate.tags, candidate.geometry_source,
        )

    assert [source_neutral(candidate) for candidate in bulk.poi_candidates] == [
        source_neutral(candidate) for candidate in overpass.poi_candidates
    ]
    bulk_geometries = {candidate.identity: wkt.loads(candidate.geometry_wkt)
                       for candidate in bulk.poi_candidates}
    overpass_geometries = {candidate.identity: wkt.loads(candidate.geometry_wkt)
                           for candidate in overpass.poi_candidates}
    assert bulk_geometries.keys() == overpass_geometries.keys()
    assert all(
        bulk_geometries[identity].equals(overpass_geometries[identity])
        for identity in bulk_geometries
    )


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


def test_read_pbf_aligns_node_ids_with_geometry_when_one_ref_lacks_location(tmp_path):
    """The noded build zips node_ids with geometry 1-to-1. If a way references
    a node whose location is invalid/unset, read_pbf must EXCLUDE that ref from
    BOTH lists (not include it in node_ids alone), so the two stay paired by
    construction. tiny_bulk.osm has every node locatable, so this needs a PBF
    whose raw refs > locatable refs."""
    from pound.ingest.osm import read_pbf

    # Minimal OSM XML: way 1001 refs nodes 1, 2, 3 where node 2 has NO lat/lon.
    # Locatable refs = {1, 3}; raw refs = {1, 2, 3}. node_ids must == [1, 3]
    # and geometry must have 2 points, paired (1->coord1, 3->coord3).
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="alignment fixture">
  <node id="1" lat="51.7500000" lon="-1.2600000" version="1"/>
  <node id="2" version="1"/>
  <node id="3" lat="51.7520000" lon="-1.2620000" version="1"/>
  <way id="1001" version="1">
    <nd ref="1"/><nd ref="2"/><nd ref="3"/>
    <tag k="waterway" v="canal"/><tag k="name" v="Alignment Way"/>
  </way>
</osm>
"""
    pbf = tmp_path / "unaligned.osm"
    pbf.write_text(xml)
    feats = read_pbf(pbf)
    assert len(feats.ways) == 1
    way = feats.ways[0]
    assert len(way.node_ids) == len(way.geometry)
    assert way.node_ids == [1, 3]
    expected_geom = [(51.75, -1.26), (51.752, -1.262)]
    assert way.geometry == expected_geom
