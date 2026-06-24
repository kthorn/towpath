import json

import pytest

from pound.graph.build import build_graph
from pound.graph.locks import attach_locks
from pound.ingest.overpass import parse
from pound.route.cost import CRUISE_KMH, LOCK_MINUTES, time_min
from pound.route.plan import plan_route
from pound.schemas import CanalConstraints
from tests.fixtures import oxford_fixture_path


def _plan(**kwargs):
    with open(oxford_fixture_path()) as f:
        raw = json.load(f)
    features = parse(raw["elements"], None)
    features.fetched_at = raw["osm3s"]["timestamp_osm_base"]
    g, _ = attach_locks(build_graph(features), features)
    constraints = CanalConstraints(start="Oxford", end="Hayfield", days=1, **kwargs)
    return plan_route(constraints, _graph=g, _features=features)


def test_route_connects_oxford_to_hayfield():
    r = _plan()
    assert r.start == "Oxford"
    assert r.end == "Hayfield"
    assert r.is_ring is False
    assert r.legs[0].from_place == "Oxford"
    assert r.legs[-1].to_place == "Hayfield"
    # legs connect end-to-end (§7.2)
    for i in range(len(r.legs) - 1):
        assert r.legs[i].to_place == r.legs[i + 1].from_place


def test_totals_equal_sum_of_legs():
    r = _plan()
    assert r.total_km == pytest.approx(sum(leg.distance_km for leg in r.legs))
    assert r.total_locks == sum(leg.locks for leg in r.legs)
    assert r.total_minutes == sum(leg.est_minutes for leg in r.legs)


def test_per_leg_minutes_match_cost_formula():
    r = _plan()
    for leg in r.legs:
        expected = round(leg.distance_km / CRUISE_KMH * 60 + leg.locks * LOCK_MINUTES)
        assert leg.est_minutes == expected


def test_total_minutes_matches_time_min_over_edges():
    # independent recomputation from the raw edge lengths/locks
    r = _plan()
    assert r.total_minutes == round(time_min(r.total_km * 1000, r.total_locks))


def test_locks_counted_on_lock_edge():
    r = _plan()
    # way 1003 (lock) is on the path; exactly one lock edge
    assert r.total_locks == 1


def test_warnings_flag_unknown_dims():
    # 1001 and 1003 lack dims; with a boat that has dims, those legs flag
    r = _plan(boat_beam_m=2.0, boat_draft_m=0.8)
    assert any("unknown" in w.lower() for w in r.warnings)


def test_graph_source_date_from_metadata():
    r = _plan()
    assert r.graph_source_date == "2026-06-21T12:00:00Z"


def test_ring_raises_not_implemented():
    with open(oxford_fixture_path()) as f:
        raw = json.load(f)
    features = parse(raw["elements"], None)
    features.fetched_at = raw["osm3s"]["timestamp_osm_base"]
    g, _ = attach_locks(build_graph(features), features)
    with pytest.raises(NotImplementedError, match="rings not yet supported"):
        plan_route(CanalConstraints(start="Oxford", end=None, days=1), _graph=g, _features=features)


def test_single_day_plan_wraps_legs():
    r = _plan()
    assert len(r.days) == 1
    assert r.days[0].legs == r.legs
    assert r.days[0].cruising_minutes == r.total_minutes


def _long_plan(days: int, hours_per_day: float):
    """Synthetic long route: scale the Oxford edge lengths so the 3-edge path
    needs multiple days. Tests the chunking ALGORITHM, not Oxford data.

    The Oxford fixture's edges are not all the same raw length, so after
    scaling we normalize every edge to ~13 km; each leg then fits comfortably
    inside a 3-hour budget while the total still needs three days.
    """
    import copy

    with open(oxford_fixture_path()) as f:
        raw = json.load(f)
    features = parse(raw["elements"], None)
    features.fetched_at = raw["osm3s"]["timestamp_osm_base"]
    g, _ = attach_locks(build_graph(features), features)
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0  # ~13 km -> ~162 min/edge
    constraints = CanalConstraints(
        start="Oxford", end="Hayfield", days=days, hours_per_day=hours_per_day
    )
    return plan_route(constraints, _graph=g, _features=features)


def test_multiday_splits_legs_within_budget():
    # 3 edges ~162 min each; hours_per_day=3 -> 180 min budget.
    # Greedy: day1=162, day2=162, day3=162 (each +next would exceed 180).
    r = _long_plan(days=3, hours_per_day=3.0)
    assert len(r.days) == 3
    for day in r.days:
        assert day.cruising_minutes <= 3.0 * 60
        assert day.legs  # non-empty (OQ-8: no padding)


def test_days_partition_legs_exactly():
    r = _long_plan(days=3, hours_per_day=3.0)
    flat = [leg for day in r.days for leg in day.legs]
    assert flat == r.legs


def test_days_not_padded_beyond_route():
    # OQ-8: days=5 but route needs only 3 -> emit 3, NOT 5 with empty trailers.
    r = _long_plan(days=5, hours_per_day=3.0)
    assert len(r.days) == 3
    assert all(day.legs for day in r.days)


def test_days_count_never_exceeds_constraints_days():
    r = _long_plan(days=2, hours_per_day=3.0)
    assert len(r.days) <= 2


def test_day_index_sequential():
    r = _long_plan(days=3, hours_per_day=3.0)
    assert [d.day for d in r.days] == [1, 2, 3]
