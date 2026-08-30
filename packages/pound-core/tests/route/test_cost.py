from pound.models import WayDimensions
from pound.route.cost import (
    CRUISE_KMH,
    DEFAULT_MOVABLE_BRIDGE_DELAY_MIN,
    LOCK_MINUTES,
    is_eligible,
    time_min,
)


def test_constants_match_design():
    assert CRUISE_KMH == 4.8
    assert LOCK_MINUTES == 12


def test_default_movable_bridge_delay_is_five_minutes():
    assert DEFAULT_MOVABLE_BRIDGE_DELAY_MIN == 5.0
    assert time_min(9_500.0, 2, movable_bridges=1, movable_bridge_delay_min=5.0) == 147.75
    assert time_min(9_500.0, 2, movable_bridges=1, movable_bridge_delay_min=0.0) == 142.75


def test_time_min_formula():
    # 9.5 km, 2 locks, no bridges: 9.5/4.8*60 + 2*12 = 142.75
    assert time_min(9500.0, 2, movable_bridge_delay_min=DEFAULT_MOVABLE_BRIDGE_DELAY_MIN) == 142.75
    # zero distance, zero locks
    assert time_min(0.0, 0, movable_bridge_delay_min=DEFAULT_MOVABLE_BRIDGE_DELAY_MIN) == 0.0


def test_is_eligible_passes_when_within_dims():
    edge = WayDimensions(max_beam_m=2.1, max_draft_m=0.9)
    eligible, unknown = is_eligible(
        boat_length_m=None,
        boat_beam_m=2.0,
        boat_draft_m=0.8,
        boat_height_m=None,
        edge_dims=edge,
    )
    assert eligible is True
    assert unknown is False


def test_is_eligible_blocks_when_boat_exceeds():
    edge = WayDimensions(max_beam_m=2.1)
    eligible, unknown = is_eligible(
        boat_length_m=None,
        boat_beam_m=2.2,
        boat_draft_m=None,
        boat_height_m=None,
        edge_dims=edge,
    )
    assert eligible is False
    assert unknown is False


def test_is_eligible_flags_unknown_when_edge_dim_missing():
    edge = WayDimensions()  # no dims recorded
    eligible, unknown = is_eligible(
        boat_length_m=15.0,
        boat_beam_m=2.0,
        boat_draft_m=0.8,
        boat_height_m=2.5,
        edge_dims=edge,
    )
    assert eligible is True  # missing tag => assume passable
    assert unknown is True  # but flag it
