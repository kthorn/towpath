import json
from pathlib import Path

import pytest
from shapely import wkt

from pound.ingest.ir import NodeKind, WaterwayKind
from pound.ingest.overpass import OXFORD_BBOX, build_query, fetch_oxford, parse
from tests.fixtures import oxford_fixture_path

FIXTURE = Path(__file__).parent.parent / "fixtures" / "oxford_overpass_sample.json"
POI_FIXTURE = Path(__file__).parent.parent / "fixtures" / "poi_overpass_sample.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def load_poi_fixture() -> dict:
    return json.loads(POI_FIXTURE.read_text())


def test_build_query_contains_bbox_and_filters():
    q = build_query((51.70, -1.35, 51.80, -1.20))
    assert "[out:json]" in q
    assert "(51.7,-1.35,51.8,-1.2)" in q
    assert "waterway" in q
    assert "lock_gate" in q
    assert "out geom;" in q


def test_build_query_requests_both_movable_bridge_tag_forms():
    query = build_query(OXFORD_BBOX)
    assert 'node["bridge:movable"]' in query
    assert 'node["bridge"="movable"]' in query
    assert 'way["bridge:movable"]' in query
    assert 'way["bridge"="movable"]' in query


def test_build_query_uses_explicit_poi_and_pedestrian_clauses():
    q = build_query(OXFORD_BBOX)
    for clause in (
        'nwr["waterway"="water_point"]',
        'nwr["amenity"~"^(sanitary_dump_station|fuel|pub|cafe|restaurant|taxi)$"]',
        'nwr["shop"~"^(supermarket|convenience|bakery|greengrocer|butcher|deli|general)$"]',
        'nwr["highway"~"^(footway|path|pedestrian|steps|bus_stop)$"]',
        'nwr["barrier"~"^(gate|stile|kissing_gate|cycle_barrier)$"]',
    ):
        assert clause in q
    assert 'nwr["access"' not in q
    assert 'nwr["foot"="no"]' not in q
    assert "nwr[amenity]" not in q
    assert "nwr[shop]" not in q
    assert 'nwr["amenity"="drinking_water"]' not in q
    assert 'nwr["amenity"="toilets"]' not in q
    assert 'nwr["amenity"="shower"]' not in q


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


def test_parse_flags_bridge_movable_way():
    features = parse(
        [
            {
                "type": "way",
                "id": 99,
                "tags": {"waterway": "canal", "bridge": "movable"},
                "geometry": [
                    {"lat": 51.75, "lon": -1.26},
                    {"lat": 51.751, "lon": -1.261},
                ],
            }
        ],
        OXFORD_BBOX,
    )
    assert features.ways[0].has_movable_bridge is True


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
    # inject non-public ways into the fixture's elements (so the filter has work to do)
    boat_no_way = {
        "type": "way",
        "id": 9999,
        "tags": {"waterway": "canal", "boat": "no"},
        "geometry": [{"lat": 51.7510, "lon": -1.2600}, {"lat": 51.7520, "lon": -1.2600}],
    }
    access_private_way = {
        "type": "way",
        "id": 9998,
        "tags": {"waterway": "canal", "access": "private"},
        "geometry": [{"lat": 51.7530, "lon": -1.2600}, {"lat": 51.7540, "lon": -1.2600}],
    }
    raw["elements"].extend([boat_no_way, access_private_way])
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
    # neither non-public way must survive
    assert {9998, 9999}.isdisjoint({way.osm_id for way in features.ways})
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


def test_parse_emits_deduplicated_ordered_poi_candidates_with_normalized_tags():
    feats = parse(load_poi_fixture()["elements"], OXFORD_BBOX)
    identities = [(str(p.osm_type), p.osm_id, p.kind) for p in feats.poi_candidates]
    assert identities == [
        ("node", 2001, "water_point"),
        ("node", 2002, "pub"),
        ("node", 2003, "supermarket"),
        ("node", 2004, "rail_station"),
        ("node", 2005, "bus_stop"),
        ("node", 2006, "entrance"),
        ("node", 2007, "gate"),
        ("relation", 2301, "fuel"),
        ("way", 2101, "marina"),
        ("way", 2102, "cafe"),
        ("way", 2103, "path_connection"),
    ]
    by_identity = {(p.osm_type, p.osm_id, p.kind): p for p in feats.poi_candidates}
    water = by_identity[("node", 2001, "water_point")]
    assert water.tags == {"waterway": "water_point", "drinking_water": "yes"}
    assert water.geometry_source == "point"
    assert wkt.loads(water.geometry_wkt).geom_type == "Point"
    pub = by_identity[("node", 2002, "pub")]
    assert pub.tags == {"amenity": "pub", "opening_hours": "Mo-Su 12:00-22:00"}
    marina = by_identity[("way", 2101, "marina")]
    assert marina.geometry_source == "area"
    assert wkt.loads(marina.geometry_wkt).geom_type == "Polygon"
    path = by_identity[("way", 2103, "path_connection")]
    assert path.geometry_source == "derived_path"
    assert wkt.loads(path.geometry_wkt).geom_type == "LineString"
    relation = by_identity[("relation", 2301, "fuel")]
    assert relation.geometry_source == "area"
    assert wkt.loads(relation.geometry_wkt).geom_type == "Polygon"
    assert len(wkt.loads(relation.geometry_wkt).interiors) == 1


def test_parse_reports_unknown_and_incomplete_area_geometry_without_center_fallback():
    feats = parse(load_poi_fixture()["elements"], OXFORD_BBOX)
    assert feats.poi_ingest_report.skipped_counts == {
        "missing_area_geometry": 1,
        "invalid_geometry": 1,
        "unknown_value": 1,
    }
    assert feats.poi_ingest_report.skipped_examples["unknown_value"] == ["node/2009:shop=magic"]
    assert feats.poi_ingest_report.skipped_examples["missing_area_geometry"] == ["way/2104"]
    assert feats.poi_ingest_report.skipped_examples["invalid_geometry"] == ["way/2105"]
    assert not any(p.osm_id in (2104, 2105) for p in feats.poi_candidates)
    assert not any(p.osm_id in (2008, 2010, 2011, 2012) for p in feats.poi_candidates)


@pytest.mark.parametrize(
    ("relation", "extra_elements"),
    [
        ({"members": [{"type": "way", "ref": 999, "role": "outer"}]}, []),
        (
            {"members": [{"type": "way", "ref": 2401, "role": "outer"}]},
            [{"type": "way", "id": 2401, "geometry": []}],
        ),
        ({"members": []}, []),
        (
            {"members": [{"type": "way", "ref": 2402, "role": "outer"}]},
            [
                {
                    "type": "way",
                    "id": 2402,
                    "geometry": [{"lat": 51.7, "lon": -1.2}, {"lat": 51.8, "lon": -1.2}],
                }
            ],
        ),
        (
            {
                "members": [
                    {"type": "way", "ref": 2403, "role": "outer"},
                    {"type": "way", "ref": 2404, "role": "inner"},
                ]
            },
            [
                {
                    "type": "way",
                    "id": 2403,
                    "geometry": [
                        {"lat": 51.7, "lon": -1.2},
                        {"lat": 51.7, "lon": -1.1},
                        {"lat": 51.8, "lon": -1.1},
                        {"lat": 51.8, "lon": -1.2},
                        {"lat": 51.7, "lon": -1.2},
                    ],
                },
                {
                    "type": "way",
                    "id": 2404,
                    "geometry": [
                        {"lat": 52.0, "lon": -1.0},
                        {"lat": 52.0, "lon": -0.9},
                        {"lat": 52.1, "lon": -0.9},
                        {"lat": 52.1, "lon": -1.0},
                        {"lat": 52.0, "lon": -1.0},
                    ],
                },
            ],
        ),
        (
            {"members": [{"type": "way", "ref": 2405, "role": "label"}]},
            [
                {
                    "type": "way",
                    "id": 2405,
                    "geometry": [
                        {"lat": 51.7, "lon": -1.2},
                        {"lat": 51.7, "lon": -1.1},
                        {"lat": 51.8, "lon": -1.1},
                        {"lat": 51.8, "lon": -1.2},
                        {"lat": 51.7, "lon": -1.2},
                    ],
                }
            ],
        ),
    ],
)
def test_parse_rejects_incomplete_relation_geometry(relation, extra_elements):
    element = {
        "type": "relation",
        "id": 2500,
        "tags": {"type": "multipolygon", "amenity": "pub"},
        **relation,
    }
    feats = parse([*extra_elements, element], OXFORD_BBOX)
    assert feats.poi_candidates == []
    assert feats.poi_ingest_report.skipped_counts["incomplete_relation_geometry"] == 1
    assert feats.poi_ingest_report.skipped_examples["incomplete_relation_geometry"] == [
        "relation/2500"
    ]


def test_parse_rejects_nested_relation_cycle_and_accepts_complete_nested_relation():
    ring = {
        "type": "way",
        "id": 2601,
        "geometry": [
            {"lat": 51.7, "lon": -1.2},
            {"lat": 51.7, "lon": -1.1},
            {"lat": 51.8, "lon": -1.1},
            {"lat": 51.8, "lon": -1.2},
            {"lat": 51.7, "lon": -1.2},
        ],
    }
    nested = {
        "type": "relation",
        "id": 2602,
        "members": [{"type": "way", "ref": 2601, "role": "outer"}],
    }
    tagged = {
        "type": "relation",
        "id": 2603,
        "tags": {"amenity": "cafe"},
        "members": [{"type": "relation", "ref": 2602, "role": "outer"}],
    }
    cycle_a = {
        "type": "relation",
        "id": 2610,
        "tags": {"amenity": "pub"},
        "members": [{"type": "relation", "ref": 2611, "role": "outer"}],
    }
    cycle_b = {
        "type": "relation",
        "id": 2611,
        "members": [{"type": "relation", "ref": 2610, "role": "outer"}],
    }
    feats = parse([ring, nested, tagged, cycle_a, cycle_b], OXFORD_BBOX)
    assert [(p.osm_id, p.kind) for p in feats.poi_candidates] == [(2603, "cafe")]
    assert feats.poi_ingest_report.skipped_examples["incomplete_relation_geometry"] == [
        "relation/2610"
    ]


def test_parse_resolves_inline_member_geometry_and_way_node_references():
    node_elements = [
        {"type": "node", "id": 2701, "lat": 51.70, "lon": -1.20},
        {"type": "node", "id": 2702, "lat": 51.70, "lon": -1.10},
        {"type": "node", "id": 2703, "lat": 51.80, "lon": -1.10},
        {"type": "node", "id": 2704, "lat": 51.80, "lon": -1.20},
    ]
    node_ref_way = {
        "type": "way",
        "id": 2710,
        "nodes": [2701, 2702, 2703, 2704, 2701],
        "tags": {"shop": "general"},
    }
    inline_relation = {
        "type": "relation",
        "id": 2720,
        "tags": {"amenity": "cafe"},
        "members": [
            {
                "type": "way",
                "ref": 2721,
                "role": "outer",
                "geometry": [
                    {"lat": 51.70, "lon": -1.20},
                    {"lat": 51.70, "lon": -1.10},
                    {"lat": 51.80, "lon": -1.10},
                    {"lat": 51.80, "lon": -1.20},
                    {"lat": 51.70, "lon": -1.20},
                ],
            }
        ],
    }
    feats = parse([*node_elements, node_ref_way, inline_relation], OXFORD_BBOX)
    assert [(p.osm_id, p.kind) for p in feats.poi_candidates] == [
        (2720, "cafe"),
        (2710, "general"),
    ]
    assert all(wkt.loads(p.geometry_wkt).geom_type == "Polygon" for p in feats.poi_candidates)


def test_parse_polygonizes_a_relation_outer_ring_split_across_member_ways():
    ways = [
        {
            "type": "way",
            "id": 2801,
            "geometry": [
                {"lat": 51.70, "lon": -1.20},
                {"lat": 51.70, "lon": -1.10},
                {"lat": 51.80, "lon": -1.10},
            ],
        },
        {
            "type": "way",
            "id": 2802,
            "geometry": [
                {"lat": 51.80, "lon": -1.10},
                {"lat": 51.80, "lon": -1.20},
                {"lat": 51.70, "lon": -1.20},
            ],
        },
    ]
    relation = {
        "type": "relation",
        "id": 2810,
        "tags": {"amenity": "restaurant"},
        "members": [
            {"type": "way", "ref": 2801, "role": "outer"},
            {"type": "way", "ref": 2802, "role": "outer"},
        ],
    }
    feats = parse([*ways, relation], OXFORD_BBOX)
    assert [(p.osm_id, p.kind) for p in feats.poi_candidates] == [(2810, "restaurant")]
    assert wkt.loads(feats.poi_candidates[0].geometry_wkt).geom_type == "Polygon"
