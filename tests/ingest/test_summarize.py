from pound.ingest.ir import (
    NodeKind,
    OsmElementType,
    PoiCategory,
    PoiIngestReport,
    PointOfInterest,
    WaterwayFeatures,
    WaterwayKind,
    WaterwayNode,
    WaterwayWay,
    WayDimensions,
)
from pound.ingest.summarize import summarize, summarize_pois


def _canal(osm_id, dims=None, tunnel=False, movable=False):
    return WaterwayWay(
        osm_id=osm_id,
        kind=WaterwayKind.CANAL,
        name="Oxford Canal",
        tags={"waterway": "canal"},
        node_ids=[],
        geometry=[(51.75, -1.26)],
        dimensions=dims or WayDimensions(),
        has_tunnel=tunnel,
        has_movable_bridge=movable,
    )


def _lock_way(osm_id):
    return WaterwayWay(
        osm_id=osm_id,
        kind=WaterwayKind.LOCK,
        name="A Lock",
        tags={"waterway": "lock"},
        node_ids=[],
        geometry=[(51.75, -1.26)],
        dimensions=WayDimensions(),
    )


def _node(osm_id, kind):
    return WaterwayNode(osm_id=osm_id, lat=51.75, lon=-1.26, tags={}, kind=kind)


def test_summarize_counts_ways_by_kind():
    feats = WaterwayFeatures(
        ways=[_canal(1), _canal(2), _lock_way(3)],
        nodes=[],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=(51.70, -1.35, 51.80, -1.20),
    )
    r = summarize(feats)
    assert r["way_count"] == 3
    assert r["ways_by_kind"] == {"canal": 2, "lock": 1}


def test_summarize_counts_nodes_by_kind():
    feats = WaterwayFeatures(
        ways=[],
        nodes=[_node(1, NodeKind.LOCK_GATE), _node(2, NodeKind.MOORING), _node(3, NodeKind.LOCK)],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=None,
    )
    r = summarize(feats)
    assert r["node_count"] == 3
    assert r["nodes_by_kind"] == {"lock_gate": 1, "mooring": 1, "lock": 1}


def test_summarize_lock_count_combines_lock_ways_and_lock_nodes():
    feats = WaterwayFeatures(
        ways=[_lock_way(1), _canal(2)],
        nodes=[_node(10, NodeKind.LOCK), _node(11, NodeKind.LOCK_GATE)],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=None,
    )
    r = summarize(feats)
    # 1 lock way + 1 lock node (lock_gate counted separately, not as a lock)
    assert r["lock_count"] == 2


def test_summarize_missing_dimensions_for_routable_only():
    feats = WaterwayFeatures(
        ways=[
            _canal(1, dims=WayDimensions(max_beam_m=2.1)),  # has a dim
            _canal(2),  # no dims
            _lock_way(3),  # lock way, no dims — should NOT count against routable
        ],
        nodes=[],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=None,
    )
    r = summarize(feats)
    assert r["routable_ways_missing_all_dimensions"] == 1


def test_summarize_tunnel_and_movable_bridge_flags():
    feats = WaterwayFeatures(
        ways=[_canal(1, tunnel=True), _canal(2, movable=True)],
        nodes=[],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=None,
    )
    r = summarize(feats)
    assert r["tunnel_ways"] == 1
    assert r["movable_bridge_ways"] == 1


def test_summarize_provenance_fields():
    feats = WaterwayFeatures(
        ways=[],
        nodes=[],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=(51.70, -1.35, 51.80, -1.20),
    )
    r = summarize(feats)
    assert r["source"] == "overpass"
    assert r["fetched_at"] == "2026-06-21T12:00:00+00:00"
    assert r["bbox"] == [51.70, -1.35, 51.80, -1.20]


def test_summarize_pois_combines_retained_and_reader_attachment_diagnostics():
    pois = [
        PointOfInterest(
            osm_type=OsmElementType.NODE,
            osm_id=1,
            category=PoiCategory.CANAL_SERVICE,
            kind="water_point",
            name="Canal Tap",
            lat=51.75,
            lon=-1.26,
            source_tags={"waterway": "water_point", "drinking_water": "yes"},
            geometry_source="point",
            nearest_waterway_distance_m=0,
            nearest_edge=(0, 1),
            nearest_node_uid=0,
            projected_lat=51.75,
            projected_lon=-1.26,
        )
    ]
    ingest = PoiIngestReport(
        skipped_counts={
            "invalid_geometry": 2,
            "incomplete_relation_geometry": 1,
            "unknown_value": 3,
        },
        skipped_examples={
            "unknown_value": ["node/9:shop=magic", "node/8:shop=magic"],
            "invalid_geometry": ["way/7"],
        },
    )

    summary = summarize_pois(
        pois,
        ingest,
        {"rejected_by_corridor": 4, "invalid_geometry": 1, "empty_geometry": 2},
    )

    assert summary["retained"] == 1
    assert summary["by_category"] == {"canal_service": 1}
    assert summary["by_kind"] == {"water_point": 1}
    assert summary["rejected_by_corridor"] == 4
    assert summary["malformed_geometry"] == 5
    assert summary["incomplete_relation"] == 1
    assert summary["unknown_tag_value"] == 3
    assert summary["skipped_examples"] == {
        "invalid_geometry": ["way/7"],
        "unknown_value": ["node/8:shop=magic", "node/9:shop=magic"],
    }
