import pytest

from pound.ingest.overpass import OXFORD_BBOX, fetch_oxford


@pytest.mark.network
def test_live_overpass_oxford_returns_features():
    feats = fetch_oxford()
    assert feats.source == "overpass"
    assert feats.bbox == OXFORD_BBOX
    # a real Oxford extract should contain at least some canal ways
    assert len(feats.ways) > 0
    assert any(w.kind.value == "canal" for w in feats.ways)
