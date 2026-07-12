import copy
import json

import pytest

from pound.graph.build import build_graph
from pound.graph.gazetteer import attach_node_names, build_gazetteer
from pound.graph.locks import attach_locks
from pound.ingest.overpass import parse
from pound.route.cost import CRUISE_KMH, LOCK_MINUTES, time_min
from pound.route.plan import plan_canal_route, plan_route, plan_route_from_constraints
from pound.schemas import CanalConstraints, ResolvedConstraints
from tests.fixtures import oxford_fixture_path


def _graph_and_gaz():
    with open(oxford_fixture_path()) as f:
        raw = json.load(f)
    feats = parse(raw["elements"], None, osm_timestamp=raw["osm3s"]["timestamp_osm_base"])
    g, _ = attach_locks(build_graph(feats), feats)
    attach_node_names(g, feats)
    g.graph["gazetteer"] = build_gazetteer(feats)
    g.graph["fetched_at"] = feats.fetched_at  # plan_route reads graph_source_date here
    return g, feats


def resolve_first(name, g):
    from pound.route.resolve import resolve_place

    return resolve_place(name, g)


def _resolved(start="Oxford", end="Hayfield", **kwargs):
    g, _ = _graph_and_gaz()
    from pound.route.resolve import resolve_place

    return ResolvedConstraints(
        start_uid=resolve_place(start, g),
        end_uid=resolve_place(end, g),
        **kwargs,
    ), g


def test_route_connects_oxford_to_hayfield():
    (rc, g) = _resolved(days=1)
    r = plan_route(rc, graph=g)
    assert r.start == "Oxford"
    assert r.end == "Hayfield"
    assert r.legs[0].from_place == "Oxford"
    assert r.legs[-1].to_place == "Hayfield"
    for i in range(len(r.legs) - 1):
        assert r.legs[i].to_place == r.legs[i + 1].from_place


def test_totals_equal_sum_of_legs():
    (rc, g) = _resolved(days=1)
    r = plan_route(rc, graph=g)
    assert r.total_km == pytest.approx(sum(leg.distance_km for leg in r.legs))
    assert r.total_locks == sum(leg.locks for leg in r.legs)
    assert r.total_minutes == sum(leg.est_minutes for leg in r.legs)


def test_per_leg_minutes_match_cost_formula():
    (rc, g) = _resolved(days=1)
    r = plan_route(rc, graph=g)
    for leg in r.legs:
        expected = round(leg.distance_km / CRUISE_KMH * 60 + leg.locks * LOCK_MINUTES)
        assert leg.est_minutes == expected


def test_total_minutes_matches_time_min_over_edges():
    (rc, g) = _resolved(days=1)
    r = plan_route(rc, graph=g)
    # rounding accumulates across the 4 legs; the existing Scope C test uses abs=1
    assert r.total_minutes == pytest.approx(
        round(time_min(r.total_km * 1000, r.total_locks)), abs=1
    )


def test_locks_counted_on_lock_edge():
    (rc, g) = _resolved(days=1)
    r = plan_route(rc, graph=g)
    assert r.total_locks == 1


def test_warnings_flag_unknown_dims():
    (rc, g) = _resolved(days=1, boat_beam_m=2.0, boat_draft_m=0.8)
    r = plan_route(rc, graph=g)
    assert any("unknown" in w.lower() for w in r.warnings)


def test_graph_source_date_from_metadata():
    (rc, g) = _resolved(days=1)
    r = plan_route(rc, graph=g)
    assert r.graph_source_date == "2026-06-21T12:00:00Z"


def test_ring_raises_not_implemented():
    # Rings are not modelled in ResolvedConstraints (end_uid is required);
    # CanalConstraints(end=None) -> plan_route_from_constraints raises.
    g, _ = _graph_and_gaz()
    with pytest.raises(NotImplementedError, match="rings not yet supported"):
        plan_route_from_constraints(CanalConstraints(start="Oxford", end=None, days=1), graph=g)


def test_single_day_plan_wraps_legs():
    (rc, g) = _resolved(days=1)
    r = plan_route(rc, graph=g)
    assert len(r.days) == 1
    assert r.days[0].legs == r.legs
    assert r.days[0].cruising_minutes == r.total_minutes


def test_no_path_under_dimensions_raises_valueerror_not_traceback():
    g, _ = _graph_and_gaz()
    rc = ResolvedConstraints(
        start_uid=resolve_first("Oxford", g),
        end_uid=resolve_first("Hayfield", g),
        days=1,
        boat_beam_m=99.0,
        boat_draft_m=99.0,  # bigger than any edge
    )
    with pytest.raises(ValueError, match="no path between"):
        plan_route(rc, graph=g)


def test_single_day_over_budget_warns():
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0  # ~162 min leg, ~3 h budget at 1 h/day
    rc = ResolvedConstraints(
        start_uid=resolve_first("Oxford", g),
        end_uid=resolve_first("Hayfield", g),
        days=1,
        hours_per_day=1.0,
    )
    r = plan_route(rc, graph=g)
    assert len(r.days) == 1  # forced single day via max_days cap
    assert r.days[0].cruising_minutes > 1.0 * 60
    assert any("exceed hours_per_day" in w for w in r.warnings)


def _long_resolved(days, hours_per_day, g):
    return ResolvedConstraints(
        start_uid=resolve_first("Oxford", g),
        end_uid=resolve_first("Hayfield", g),
        days=days,
        hours_per_day=hours_per_day,
    )


def test_multiday_splits_legs_within_budget():
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0
    # 4 edges ~162 min each; hours_per_day=3 -> 180 min budget. Greedy emits
    # one edge per day (each +next would exceed 180) -> 4 days, each in budget.
    rc = _long_resolved(days=4, hours_per_day=3.0, g=g)
    r = plan_route(rc, graph=g)
    assert len(r.days) == 4
    for day in r.days:
        assert day.cruising_minutes <= 3.0 * 60
        assert day.legs


def test_days_partition_legs_exactly():
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0
    rc = _long_resolved(days=4, hours_per_day=3.0, g=g)
    r = plan_route(rc, graph=g)
    flat = [leg for day in r.days for leg in day.legs]
    assert flat == r.legs


def test_days_not_padded_beyond_route():
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0
    rc = _long_resolved(days=5, hours_per_day=3.0, g=g)
    r = plan_route(rc, graph=g)
    assert len(r.days) == 4  # 4 edges need 4 days; days=5 does not pad with empties
    assert all(day.legs for day in r.days)


def test_days_count_never_exceeds_constraints_days():
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0
    rc = _long_resolved(days=2, hours_per_day=3.0, g=g)
    r = plan_route(rc, graph=g)
    assert len(r.days) <= 2


def test_day_index_sequential():
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0
    rc = _long_resolved(days=4, hours_per_day=3.0, g=g)
    r = plan_route(rc, graph=g)
    assert [d.day for d in r.days] == [1, 2, 3, 4]


def test_plan_route_from_constraints_bridge():
    g, _ = _graph_and_gaz()
    r = plan_route_from_constraints(
        CanalConstraints(start="Oxford", end="Hayfield", days=1), graph=g
    )
    assert r.start == "Oxford"
    assert r.end == "Hayfield"
    assert r.legs  # non-empty


def test_days_none_infers_no_cap():
    # days omitted (None) => hours_per_day alone drives chunking; no cap.
    # 4 ~162-min edges at 3 h/day => 4 days; None cap behaves like max_days=inf.
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 13000.0
    rc = ResolvedConstraints(
        start_uid=resolve_first("Oxford", g),
        end_uid=resolve_first("Hayfield", g),
        days=None,
        hours_per_day=3.0,
    )
    r = plan_route(rc, graph=g)
    assert len(r.days) == 4  # uncapped -> one day per edge, no folding


def test_days_none_with_more_time_fits_in_fewer_days():
    g, _ = _graph_and_gaz()
    g = copy.deepcopy(g)
    for _, _, d in g.edges(data=True):
        d["length_m"] = 1000.0  # tiny edges; whole route fits one day
    rc = ResolvedConstraints(
        start_uid=resolve_first("Oxford", g),
        end_uid=resolve_first("Hayfield", g),
        days=None,
        hours_per_day=6.0,
    )
    r = plan_route(rc, graph=g)
    assert len(r.days) == 1


@pytest.mark.parametrize("planner", [plan_route, plan_canal_route])
def test_same_handle_returns_an_empty_route_with_valid_labels(planner):
    _, graph = _resolved()
    uid = resolve_first("Oxford", graph)
    constraints = ResolvedConstraints(start_uid=uid, end_uid=uid)

    response = planner(constraints, graph=graph)
    route = response.route if hasattr(response, "route") else response

    assert route.start == "Oxford"
    assert route.end == "Oxford"
    assert route.total_km == 0
    assert route.total_locks == 0
    assert route.total_minutes == 0
    assert route.legs == []
    assert route.days == []
    if hasattr(response, "geometry"):
        node = graph.nodes[uid]
        point = (node["lon"], node["lat"])
        assert response.geometry.coordinates == [point, point]
