import pytest

from pound.plan import plan_route
from pound.schemas import CanalConstraints


def get_result(**overrides):
    kwargs: dict[str, object] = {"start": "Oxford", "end": "Heyford", "days": 1}
    kwargs.update(overrides)
    return plan_route(CanalConstraints(**kwargs))  # type: ignore[call-arg]


def test_legs_connect_end_to_end():
    result = get_result()
    for a, b in zip(result.legs, result.legs[1:], strict=False):
        assert a.to_place == b.from_place


def test_totals_equal_sum_of_legs():
    result = get_result()
    assert result.total_km == pytest.approx(sum(leg.distance_km for leg in result.legs))
    assert result.total_locks == sum(leg.locks for leg in result.legs)
    assert result.total_minutes == sum(leg.est_minutes for leg in result.legs)


def test_day_cruising_matches_leg_sum():
    """Day cruising minutes equal the sum of that day's leg minutes (design §7.2)."""
    result = get_result(hours_per_day=6.0)
    for day in result.days:
        assert day.cruising_minutes == sum(leg.est_minutes for leg in day.legs)


def test_day_cruising_within_hours_budget():
    """Day cruising minutes fit within hours_per_day (design §7.2)."""
    hours_per_day = 6.0
    result = get_result(hours_per_day=hours_per_day)
    budget_minutes = hours_per_day * 60
    for day in result.days:
        assert day.cruising_minutes <= budget_minutes


def test_days_legs_partition_route_legs():
    result = get_result()
    flat = [leg for day in result.days for leg in day.legs]
    assert flat == result.legs


def test_leg_minutes_match_cost_formula():
    """Per-leg est_minutes must match the documented cost formula (design §7.2).

    est_minutes = round(distance_km / CRUISE_KMH * 60 + locks * LOCK_MINUTES).
    This is the structural invariant the real engine's per-leg totals will be
    checked against; the stub must already satisfy it so the Agent Core builds
    against a contract-consistent result.
    """
    from pound.plan import CRUISE_KMH, LOCK_MINUTES

    result = get_result()
    for leg in result.legs:
        expected = round(leg.distance_km / CRUISE_KMH * 60 + leg.locks * LOCK_MINUTES)
        assert leg.est_minutes == expected


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
