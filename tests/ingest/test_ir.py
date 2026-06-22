import pytest

from pound.ingest.ir import (
    NodeKind,
    WaterwayFeatures,
    WaterwayKind,
    WaterwayNode,
    WaterwayWay,
    WayDimensions,
)


def test_waterway_way_defaults():
    w = WaterwayWay(
        osm_id=1,
        kind=WaterwayKind.CANAL,
        name="Oxford Canal",
        tags={"waterway": "canal"},
        node_ids=[101, 102],
        geometry=[(51.75, -1.26), (51.751, -1.261)],
        dimensions=WayDimensions(),
    )
    assert w.has_tunnel is False
    assert w.has_movable_bridge is False


def test_waterway_features_round_trip():
    feats = WaterwayFeatures(
        ways=[
            WaterwayWay(
                osm_id=1,
                kind=WaterwayKind.CANAL,
                name="Oxford Canal",
                tags={"waterway": "canal"},
                node_ids=[],
                geometry=[(51.75, -1.26)],
                dimensions=WayDimensions(max_beam_m=2.1),
            )
        ],
        nodes=[
            WaterwayNode(
                osm_id=10, lat=51.75, lon=-1.26, tags={"waterway": "lock_gate"},
                kind=NodeKind.LOCK_GATE,
            )
        ],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=(51.70, -1.35, 51.80, -1.20),
    )
    dumped = feats.model_dump_json()
    restored = WaterwayFeatures.model_validate_json(dumped)
    assert restored == feats
    assert restored.ways[0].dimensions.max_beam_m == pytest.approx(2.1)
