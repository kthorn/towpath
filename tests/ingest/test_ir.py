import pytest
from pydantic import ValidationError

from pound.ingest.ir import (
    NodeKind,
    OsmElementType,
    PoiCandidate,
    PoiCategory,
    PoiIngestReport,
    PointOfInterest,
    WaterwayFeatures,
    WaterwayKind,
    WaterwayNode,
    WaterwayWay,
    WayDimensions,
)


def test_poi_candidate_round_trip_and_identity():
    candidate = PoiCandidate(
        osm_type=OsmElementType.NODE,
        osm_id=42,
        category=PoiCategory.CANAL_SERVICE,
        kind="fuel",
        name="Canal Fuel",
        tags={"amenity": "fuel"},
        geometry_wkt="POINT (-1.26 51.75)",
        geometry_source="point",
    )

    assert candidate.identity == (OsmElementType.NODE, 42, "fuel")
    assert PoiCandidate.model_validate_json(candidate.model_dump_json()) == candidate


@pytest.mark.parametrize(
    ("field", "value"),
    [("lat", 91), ("lat", -91), ("lon", 181), ("lon", -181),
     ("projected_lat", 91), ("projected_lon", 181)],
)
def test_point_of_interest_rejects_out_of_bounds_coordinates(field, value):
    values = _point_of_interest_values()
    values[field] = value

    with pytest.raises(ValidationError):
        PointOfInterest(**values)


def test_point_of_interest_rejects_negative_distance():
    values = _point_of_interest_values()
    values["nearest_waterway_distance_m"] = -0.1

    with pytest.raises(ValidationError):
        PointOfInterest(**values)


@pytest.mark.parametrize("nearest_edge", [(7, 7), (8, 7), (-1, 7)])
def test_point_of_interest_rejects_invalid_attachment_tuple(nearest_edge):
    values = _point_of_interest_values()
    values["nearest_edge"] = nearest_edge

    with pytest.raises(ValidationError):
        PointOfInterest(**values)


def test_point_of_interest_has_source_identity():
    poi = PointOfInterest(**_point_of_interest_values())

    assert poi.identity == (OsmElementType.WAY, 99, "marina")


def test_poi_ingest_report_caps_deduplicates_and_sorts_examples():
    report = PoiIngestReport(
        skipped_counts={"unknown_value": 7},
        skipped_examples={
            "unknown_value": ["way/9", "node/3", "node/1", "node/2", "node/1", "way/8", "way/7"]
        },
    )

    assert report.skipped_examples == {
        "unknown_value": ["node/1", "node/2", "node/3", "way/7", "way/8"]
    }


def test_waterway_features_defaults_to_empty_poi_data():
    features = WaterwayFeatures(
        ways=[], nodes=[], source="overpass", fetched_at="2026-07-12T00:00:00Z", bbox=None
    )

    assert features.poi_candidates == []
    assert features.poi_ingest_report == PoiIngestReport()


def _point_of_interest_values():
    return {
        "osm_type": OsmElementType.WAY,
        "osm_id": 99,
        "category": PoiCategory.CANAL_SERVICE,
        "kind": "marina",
        "name": "Oxford Marina",
        "lat": 51.75,
        "lon": -1.26,
        "source_tags": {"leisure": "marina"},
        "geometry_source": "area",
        "nearest_waterway_distance_m": 25.0,
        "nearest_edge": (7, 8),
        "nearest_node_uid": 7,
        "projected_lat": 51.7501,
        "projected_lon": -1.2601,
    }


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
