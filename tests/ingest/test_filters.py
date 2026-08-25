import pytest

from pound.ingest.filters import (
    classify_node,
    classify_way,
    extract_access_caveats,
    extract_dimensions,
    filter_navigable_ways,
    is_derelict,
    is_navigable,
)
from pound.ingest.ir import (
    AccessCaveat,
    NodeKind,
    WaterwayFeatures,
    WaterwayKind,
    WaterwayNode,
    WaterwayWay,
    WayDimensions,
)

# --- classify_way ---


@pytest.mark.parametrize(
    "tags,expected",
    [
        ({"waterway": "canal"}, WaterwayKind.CANAL),
        ({"waterway": "river"}, WaterwayKind.RIVER),
        ({"waterway": "fairway"}, WaterwayKind.FAIRWAY),
        ({"waterway": "lock"}, WaterwayKind.LOCK),
        ({"lock": "yes"}, WaterwayKind.LOCK),
        ({"waterway": "canal", "lock": "yes"}, WaterwayKind.LOCK),  # staircase chamber
        ({"waterway": "derelict_canal"}, None),
        ({"waterway": "stream"}, None),
        ({}, None),
        ({"highway": "residential"}, None),
    ],
)
def test_classify_way(tags, expected):
    assert classify_way(tags) == expected


# --- is_derelict ---


def test_is_derelict_explicit_value():
    assert is_derelict({"waterway": "derelict_canal"}) is True


def test_is_derelict_disused_prefix():
    assert is_derelict({"waterway": "canal", "disused:waterway": "canal"}) is True


def test_is_derelict_abandoned_prefix():
    assert is_derelict({"abandoned:waterway": "canal"}) is True


def test_is_derelict_clean_canal():
    assert is_derelict({"waterway": "canal", "name": "Oxford Canal"}) is False


def test_is_derelict_empty():
    assert is_derelict({}) is False


# --- extract_dimensions ---


def test_extract_dimensions_all_aliases():
    tags = {
        "maxwidth": "2.1",
        "maxlength": "22.0",
        "maxdraught": "0.9",
        "maxheight": "1.9",
    }
    d = extract_dimensions(tags)
    assert d == WayDimensions(max_beam_m=2.1, max_length_m=22.0, max_draft_m=0.9, max_height_m=1.9)


def test_extract_dimensions_alternate_aliases():
    tags = {"width": "2.2", "maxdraft": "0.8", "maxclosedheight": "1.8", "depth": "0.7"}
    d = extract_dimensions(tags)
    assert d.max_beam_m == pytest.approx(2.2)
    assert d.max_draft_m == pytest.approx(0.8)
    assert d.max_height_m == pytest.approx(1.8)


def test_extract_dimensions_missing_returns_none():
    d = extract_dimensions({"waterway": "canal"})
    assert d == WayDimensions()


def test_extract_dimensions_bad_value_ignored():
    d = extract_dimensions({"maxwidth": "n/a"})
    assert d.max_beam_m is None


def test_extract_dimensions_first_alias_wins():
    d = extract_dimensions({"maxwidth": "2.1", "width": "9.9"})
    assert d.max_beam_m == pytest.approx(2.1)


# --- classify_node ---


@pytest.mark.parametrize(
    "tags,expected",
    [
        ({"waterway": "lock_gate"}, NodeKind.LOCK_GATE),
        ({"lock": "yes"}, NodeKind.LOCK),
        ({"waterway": "lock"}, NodeKind.LOCK),
        ({"bridge:movable": "swing"}, NodeKind.MOVABLE_BRIDGE),
        ({"bridge": "movable"}, NodeKind.MOVABLE_BRIDGE),
        ({"mooring": "yes"}, NodeKind.MOORING),
        ({"leisure": "marina"}, NodeKind.MARINA),
        ({}, None),
        ({"amenity": "pub"}, None),  # amenities are a later ingest step
    ],
)
def test_classify_node(tags, expected):
    assert classify_node(tags) == expected


# --- is_navigable ---


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"boat": "no"}, False),
        ({"boat": "unsuitable"}, False),
        ({"boat": "canoe"}, False),
        ({"boat": "private"}, False),
        ({"boat": "permit"}, False),
        ({"access": "no"}, False),
        ({"access": "private"}, False),
        ({"access": "permit"}, False),
        ({"boat": "yes", "access": "private"}, False),
        ({"boat": "permit", "access": "yes"}, False),
        ({"boat": "yes"}, True),
        ({"boat": "permissive"}, True),
        ({"boat": "designated"}, True),
        ({"access": "permissive"}, True),
        ({"access": "designated"}, True),
        ({"boat": "discouraged"}, True),
        ({"access": "discouraged"}, True),
        ({"boat": "unknown"}, True),
        ({"access": "customers"}, True),
        ({"boat": "No"}, True),
        ({}, True),
    ],
)
def test_is_navigable_applies_the_public_access_deny_lists(tags, expected):
    assert is_navigable(tags) is expected


@pytest.mark.parametrize(
    "tags, expected",
    [
        ({"access": "no", "boat": "yes"}, False),
        ({"access": "no", "boat": "private"}, False),
    ],
)
def test_is_navigable_applies_access_no_before_boat(tags, expected):
    assert is_navigable(tags) is expected


def test_is_navigable_none_tags():
    # boundary: tags is None
    assert is_navigable(None) is True


def test_extract_access_caveats_keeps_only_retained_explicit_caveats():
    assert extract_access_caveats(7, {"boat": "yes"}) == ()
    assert extract_access_caveats(7, {"boat": "private"}) == ()
    assert extract_access_caveats(7, {"boat": "discouraged", "access": "customers"}) == (
        AccessCaveat(7, "access", "customers", "unknown"),
        AccessCaveat(7, "boat", "discouraged", "discouraged"),
    )


# --- filter_navigable_ways ---


def _way(osm_id, kind, tags=None, geom=None, node_ids=None):
    return WaterwayWay(
        osm_id=osm_id,
        kind=kind,
        name=tags.get("name") if tags else None,
        tags=tags or {},
        node_ids=node_ids or [],
        geometry=geom or [(51.0, -1.0), (51.001, -1.001)],
        dimensions=WayDimensions(),
    )


def _features(ways, nodes=None):
    return WaterwayFeatures(
        ways=ways,
        nodes=nodes or [],
        source="test",
        fetched_at="2026-06-28T00:00:00Z",
        bbox=None,
    )


def test_filter_navigable_ways_drops_boat_no_keeps_yes_and_missing():
    ways = [
        _way(1, WaterwayKind.CANAL, {"waterway": "canal", "boat": "no"}),
        _way(2, WaterwayKind.CANAL, {"waterway": "canal", "boat": "yes"}),
        _way(3, WaterwayKind.CANAL, {"waterway": "canal"}),  # missing boat
    ]
    out = filter_navigable_ways(_features(ways))
    assert [w.osm_id for w in out.ways] == [2, 3]


def test_filter_navigable_ways_drops_non_public_boat_values():
    ways = [
        _way(1, WaterwayKind.CANAL, {"waterway": "canal", "boat": "unsuitable"}),
        _way(2, WaterwayKind.RIVER, {"waterway": "river", "boat": "canoe"}),
        _way(3, WaterwayKind.CANAL, {"waterway": "canal", "boat": "private"}),
        _way(4, WaterwayKind.CANAL, {"waterway": "canal", "boat": "permit"}),
    ]
    out = filter_navigable_ways(_features(ways))
    assert [w.osm_id for w in out.ways] == []


def test_filter_navigable_ways_drops_non_public_access_values():
    ways = [
        _way(1, WaterwayKind.CANAL, {"waterway": "canal", "access": "no"}),
        _way(2, WaterwayKind.CANAL, {"waterway": "canal", "access": "private"}),
        _way(3, WaterwayKind.CANAL, {"waterway": "canal", "access": "permit"}),
    ]
    out = filter_navigable_ways(_features(ways))
    assert [w.osm_id for w in out.ways] == []


def test_filter_navigable_ways_drops_lock_yes_with_boat_no():
    # kind-agnostic: a non-navigable lock (tagging contradiction) is not routable
    ways = [
        _way(1, WaterwayKind.LOCK, {"waterway": "canal", "lock": "yes", "boat": "no"}),
        _way(2, WaterwayKind.LOCK, {"waterway": "canal", "lock": "yes", "boat": "yes"}),
    ]
    out = filter_navigable_ways(_features(ways))
    assert [w.osm_id for w in out.ways] == [2]


def test_filter_navigable_ways_does_not_drop_derelict():
    # is_derelict stays inline in the readers; filter_navigable_ways is public-access-only.
    # A `disused:waterway=canal` way with `boat=yes` survives here (the reader's
    # inline is_derelict drops it later, but this function must NOT second-guess).
    ways = [
        _way(
            1,
            WaterwayKind.CANAL,
            {"waterway": "canal", "disused:waterway": "canal", "boat": "yes"},
        ),
    ]
    out = filter_navigable_ways(_features(ways))
    assert [w.osm_id for w in out.ways] == [1]


def test_filter_navigable_ways_does_not_mutate_input():
    ways = [
        _way(1, WaterwayKind.CANAL, {"waterway": "canal", "boat": "no"}),
        _way(2, WaterwayKind.CANAL, {"waterway": "canal"}),
    ]
    features = _features(ways)
    original_ids = [w.osm_id for w in features.ways]
    out = filter_navigable_ways(features)
    # input untouched
    assert [w.osm_id for w in features.ways] == original_ids
    # output is a different object with a rebuilt list
    assert out is not features
    assert out.ways is not features.ways


def test_filter_navigable_ways_preserves_nodes():
    ways = [_way(1, WaterwayKind.CANAL, {"waterway": "canal", "boat": "no"})]
    nodes = [
        WaterwayNode(osm_id=99, lat=51.0, lon=-1.0, tags={}, kind=NodeKind.MOORING),
    ]
    out = filter_navigable_ways(_features(ways, nodes=nodes))
    assert out.nodes == nodes
