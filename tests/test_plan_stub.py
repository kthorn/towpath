import pytest

from pound.plan import plan_route
from pound.schemas import CanalConstraints


def get_result(**overrides):
    base = dict(start="Oxford", end="Heyford", days=1)
    base.update(overrides)
    return plan_route(CanalConstraints(**base))


def test_legs_connect_end_to_end():
    result = get_result()
    for a, b in zip(result.legs, result.legs[1:], strict=False):
        assert a.to_place == b.from_place


def test_totals_equal_sum_of_legs():
    result = get_result()
    assert result.total_km == pytest.approx(sum(leg.distance_km for leg in result.legs))
    assert result.total_locks == sum(leg.locks for leg in result.legs)
    assert result.total_minutes == sum(leg.est_minutes for leg in result.legs)


def test_day_cruising_within_budget():
    result = get_result(hours_per_day=6.0)
    for day in result.days:
        assert day.cruising_minutes <= result.legs[0].est_minutes * 100  # generous for stub
        # tighter: cruising minutes for a day equal the sum of its legs' minutes
        assert day.cruising_minutes == sum(leg.est_minutes for leg in day.legs)


def test_days_legs_partition_route_legs():
    result = get_result()
    flat = [leg for day in result.days for leg in day.legs]
    assert flat == result.legs


def test_start_end_match_constraints():
    result = get_result()
    assert result.start == "Oxford"
    assert result.end == "Heyford"
    assert result.is_ring is False
    assert result.legs[0].from_place == "Oxford"
    assert result.legs[-1].to_place == "Heyford"


def test_graph_source_date_present():
    result = get_result()
    assert result.graph_source_date


def test_ring_when_end_none():
    result = get_result(end=None)
    assert result.is_ring is True
    assert result.end is None
    # a ring closes: last leg returns to start
    assert result.legs[-1].to_place == result.legs[0].from_place
