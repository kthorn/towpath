import pytest
from pound.ingest.ir import PoiCategory
from pound.ingest.pois import classify_poi, corridor_m, normalize_source_tags


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"waterway": "water_point"}, [(PoiCategory.CANAL_SERVICE, "water_point")]),
        ({"amenity": "sanitary_dump_station"}, [(PoiCategory.CANAL_SERVICE, "sanitary_disposal")]),
        ({"waterway": "sanitary_station"}, [(PoiCategory.CANAL_SERVICE, "sanitary_disposal")]),
        ({"amenity": "fuel"}, [(PoiCategory.CANAL_SERVICE, "fuel")]),
        ({"waterway": "fuel"}, [(PoiCategory.CANAL_SERVICE, "fuel")]),
        ({"leisure": "marina"}, [(PoiCategory.CANAL_SERVICE, "marina")]),
        ({"mooring": "yes"}, [(PoiCategory.CANAL_SERVICE, "mooring")]),
        ({"amenity": "pub"}, [(PoiCategory.PROVISIONS, "pub")]),
        ({"amenity": "cafe"}, [(PoiCategory.PROVISIONS, "cafe")]),
        ({"amenity": "restaurant"}, [(PoiCategory.PROVISIONS, "restaurant")]),
        ({"shop": "supermarket"}, [(PoiCategory.PROVISIONS, "supermarket")]),
        ({"shop": "convenience"}, [(PoiCategory.PROVISIONS, "convenience")]),
        ({"shop": "bakery"}, [(PoiCategory.PROVISIONS, "bakery")]),
        ({"shop": "greengrocer"}, [(PoiCategory.PROVISIONS, "greengrocer")]),
        ({"shop": "butcher"}, [(PoiCategory.PROVISIONS, "butcher")]),
        ({"shop": "deli"}, [(PoiCategory.PROVISIONS, "deli")]),
        ({"shop": "general"}, [(PoiCategory.PROVISIONS, "general")]),
        ({"railway": "station"}, [(PoiCategory.TRANSPORT, "rail_station")]),
        ({"railway": "halt"}, [(PoiCategory.TRANSPORT, "rail_halt")]),
        ({"highway": "bus_stop"}, [(PoiCategory.TRANSPORT, "bus_stop")]),
        ({"public_transport": "platform", "bus": "yes"}, [(PoiCategory.TRANSPORT, "bus_stop")]),
        (
            {"public_transport": "stop_position", "bus": "yes"},
            [(PoiCategory.TRANSPORT, "bus_stop")],
        ),
        ({"amenity": "taxi"}, [(PoiCategory.TRANSPORT, "taxi_rank")]),
        ({"entrance": "main"}, [(PoiCategory.PEDESTRIAN_ACCESS, "entrance")]),
        ({"highway": "footway"}, [(PoiCategory.PEDESTRIAN_ACCESS, "path_connection")]),
        ({"highway": "path"}, [(PoiCategory.PEDESTRIAN_ACCESS, "path_connection")]),
        ({"highway": "pedestrian"}, [(PoiCategory.PEDESTRIAN_ACCESS, "path_connection")]),
        (
            {"highway": "footway", "bridge": "yes"},
            [(PoiCategory.PEDESTRIAN_ACCESS, "pedestrian_bridge")],
        ),
        ({"highway": "steps"}, [(PoiCategory.PEDESTRIAN_ACCESS, "steps")]),
        ({"barrier": "gate"}, [(PoiCategory.PEDESTRIAN_ACCESS, "gate")]),
        ({"barrier": "stile"}, [(PoiCategory.PEDESTRIAN_ACCESS, "stile")]),
        ({"barrier": "kissing_gate"}, [(PoiCategory.PEDESTRIAN_ACCESS, "kissing_gate")]),
        ({"barrier": "cycle_barrier"}, [(PoiCategory.PEDESTRIAN_ACCESS, "cycle_barrier")]),
    ],
)
def test_classify_poi_allowlist(tags, expected):
    result = classify_poi(tags)

    assert [(item.category, item.kind) for item in result] == expected
    assert result.skips == ()


def test_classify_poi_returns_multiple_kinds_in_rule_order():
    result = classify_poi({"leisure": "marina", "amenity": "fuel", "shop": "general"})

    assert [(item.category, item.kind) for item in result] == [
        (PoiCategory.CANAL_SERVICE, "fuel"),
        (PoiCategory.CANAL_SERVICE, "marina"),
        (PoiCategory.PROVISIONS, "general"),
    ]


@pytest.mark.parametrize(
    "tags",
    [
        {"amenity": "parking"},
        {"amenity": "toilets"},
        {"amenity": "shower"},
        {"amenity": "drinking_water"},
    ],
)
def test_classify_poi_ignores_non_poi_amenities_without_diagnostics(tags):
    result = classify_poi(tags)

    assert result == []
    assert result.skips == ()


def test_only_waterway_water_point_drives_water_point_classification():
    result = classify_poi({"waterway": "water_point", "drinking_water": "yes"})

    assert result[0].kind == "water_point"
    assert classify_poi({"amenity": "drinking_water"}) == []


@pytest.mark.parametrize(
    "tags",
    [{"access": "private", "entrance": "main"}, {"foot": "no", "entrance": "yes"}],
)
def test_classify_poi_excludes_private_or_no_foot_entrances(tags):
    result = classify_poi(tags)

    assert result == []
    assert [skip.reason for skip in result.skips] == ["explicitly_unavailable"]


def test_mooring_no_is_explicitly_unavailable():
    result = classify_poi({"mooring": "no"})

    assert result == []
    assert [skip.reason for skip in result.skips] == ["explicitly_unavailable"]


@pytest.mark.parametrize("public_transport", ["platform", "stop_position"])
def test_bus_platform_requires_bus_evidence(public_transport):
    result = classify_poi({"public_transport": public_transport})

    assert result == []
    assert [skip.reason for skip in result.skips] == ["insufficient_bus_evidence"]


@pytest.mark.parametrize(
    "tags",
    [
        {"amenity": "school"},
        {"shop": "books"},
        {"railway": "tram_stop"},
        {"waterway": "dock"},
        {"barrier": "bollard"},
    ],
)
def test_unknown_allowlist_values_return_structured_diagnostic(tags):
    result = classify_poi(tags)

    key, value = next(iter(tags.items()))
    assert [(skip.reason, skip.key, skip.value) for skip in result.skips] == [
        ("unknown_value", key, value)
    ]


def test_precedence_deduplicates_bus_and_sanitary_classifications():
    result = classify_poi(
        {
            "highway": "bus_stop",
            "public_transport": "platform",
            "bus": "yes",
            "amenity": "sanitary_dump_station",
            "waterway": "sanitary_station",
        }
    )

    assert [(item.category, item.kind) for item in result] == [
        (PoiCategory.CANAL_SERVICE, "sanitary_disposal"),
        (PoiCategory.TRANSPORT, "bus_stop"),
    ]


def test_normalize_source_tags_keeps_only_operational_and_driving_tags():
    classification = classify_poi({"waterway": "water_point"})[0]
    normalized = normalize_source_tags(
        {
            "waterway": "water_point",
            "access": "permissive",
            "foot": "yes",
            "wheelchair": "limited",
            "opening_hours": "24/7",
            "fee": "no",
            "operator": "CRT",
            "brand": "Canal Services",
            "drinking_water": "yes",
            "toilets": "yes",
            "description": "discard me",
        },
        classification,
    )

    assert normalized == {
        "waterway": "water_point",
        "access": "permissive",
        "foot": "yes",
        "wheelchair": "limited",
        "opening_hours": "24/7",
        "fee": "no",
        "operator": "CRT",
        "brand": "Canal Services",
        "drinking_water": "yes",
    }


@pytest.mark.parametrize(
    ("category", "distance"),
    [
        (PoiCategory.CANAL_SERVICE, 250.0),
        (PoiCategory.PEDESTRIAN_ACCESS, 250.0),
        (PoiCategory.PROVISIONS, 1000.0),
        (PoiCategory.TRANSPORT, 1000.0),
    ],
)
def test_corridor_m(category, distance):
    assert corridor_m(category) == distance
