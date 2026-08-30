from typing import Any, Literal, cast

import networkx as nx
import pytest  # pyright: ignore[reportMissingImports]
from pound.catalog.metadata import CatalogMetadata
from pound.catalog.models import CatalogPlace
from pound.catalog.spatial import (
    CatalogQueryLimitError,
    CatalogQueryPolicy,
    CatalogSpatialIndex,
)
from pound.graph.spatial import GraphSpatialIndex
from pound.ingest.ir import OsmElementType
from pound.schemas import MapBounds
from pyproj import Transformer  # pyright: ignore[reportMissingImports]
from shapely import transform, wkb
from shapely.geometry import LineString, Point

_TO_BNG = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
_TO_WGS84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)


def _graph() -> nx.Graph:
    graph = nx.Graph()
    graph.add_node(1, lat=51.0, lon=-1.0)
    graph.add_node(2, lat=51.0, lon=-0.99)
    graph.add_edge(1, 2, geometry=[(51.0, -1.0), (51.0, -0.99)])
    return graph


def _place(
    kind: str,
    *,
    osm_id: int,
    lat: float,
    lon: float,
    geometry=None,
    name: str | None = None,
    alt_name: str | None = None,
    osm_type: OsmElementType = OsmElementType.NODE,
) -> CatalogPlace:
    if geometry is None:
        geometry = Point(lon, lat)
    primary_name = name or f"{kind} {osm_id}"
    return CatalogPlace(
        osm_type=osm_type,
        osm_id=osm_id,
        kind=kind,
        name=primary_name,
        lat=lat,
        lon=lon,
        metadata=CatalogMetadata(name=primary_name, alt_name=alt_name),
        geometry_wkb=wkb.dumps(geometry, output_dimension=2),
        geometry_source="point" if geometry.geom_type == "Point" else "line",
    )


def _bounds(
    *,
    south: float = 50.9,
    west: float = -1.1,
    north: float = 51.1,
    east: float = -0.9,
) -> MapBounds:
    return MapBounds(south=south, west=west, north=north, east=east)


def _policy(
    basis: Literal["route", "waterway", "none"] = "none",
    radius_m: float | None = None,
) -> CatalogQueryPolicy:
    return CatalogQueryPolicy(basis, radius_m)


def _route_bng() -> LineString:
    return transform(
        LineString([(-1.1, 51.0), (-0.9, 51.0)]),
        cast(Any, _TO_BNG.transform),
        interleaved=False,
    )


def test_catalog_index_caches_metric_geometry_and_does_not_build_unused_tree():
    index = CatalogSpatialIndex(
        (_place("pub", osm_id=1, lat=51.0, lon=-1.0),),
        GraphSpatialIndex(_graph()),
    )

    assert not hasattr(index, "geometry_tree")
    assert len(index.metric_geometries) == 1
    assert index.metric_tree is not None


def test_catalog_viewport_filters_kinds_viewport_and_keeps_deterministic_order():
    index = CatalogSpatialIndex(
        (
            _place("pub", osm_id=9, lat=51.0, lon=-1.0),
            _place("museum", osm_id=3, lat=51.0, lon=-1.0),
            _place("pub", osm_id=2, lat=52.0, lon=-2.0),
        ),
        GraphSpatialIndex(_graph()),
    )

    result = index.query_viewport(
        kinds=frozenset({"pub"}),
        bounds=_bounds(),
        text="",
        policy=_policy(),
        route_bng=None,
        day_bng=None,
        work_budget=100,
        result_budget=10,
    )

    assert [match.place.identity for match in result.matches] == [(OsmElementType.NODE, 9, "pub")]
    assert result.work_used == 2


def test_unbounded_catalog_viewport_orders_by_kind_and_osm_identity():
    node_pub = _place("pub", osm_id=9, lat=51.0, lon=-1.0)
    way_pub = _place(
        "pub",
        osm_id=2,
        lat=51.0,
        lon=-1.0,
        osm_type=OsmElementType.WAY,
    )
    museum = _place("museum", osm_id=7, lat=51.0, lon=-1.0)

    result = CatalogSpatialIndex(
        (node_pub, way_pub, museum),
        GraphSpatialIndex(_graph()),
    ).query_viewport(
        kinds=frozenset({"pub", "museum"}),
        bounds=_bounds(),
        text="",
        policy=_policy(),
        route_bng=None,
        day_bng=None,
        work_budget=100,
        result_budget=10,
    )

    assert [match.place.identity for match in result.matches] == [
        museum.identity,
        node_pub.identity,
        way_pub.identity,
    ]


def test_catalog_viewport_uses_full_geometry_for_route_and_day_distances():
    index = CatalogSpatialIndex(
        (
            _place(
                "pub",
                osm_id=1,
                lat=51.003,
                lon=-0.995,
                geometry=LineString([(-0.995, 51.0), (-0.995, 51.003)]),
            ),
        ),
        GraphSpatialIndex(_graph()),
    )

    result = index.query_viewport(
        kinds=frozenset({"pub"}),
        bounds=_bounds(),
        text="",
        policy=CatalogQueryPolicy("route", 20),
        route_bng=_route_bng(),
        day_bng=transform(
            LineString([(-1.1, 51.003), (-0.9, 51.003)]),
            cast(Any, _TO_BNG.transform),
            interleaved=False,
        ),
        work_budget=100,
        result_budget=10,
    )

    assert len(result.matches) == 1
    match = result.matches[0]
    assert match.full_route_distance_m == pytest.approx(0, abs=0.1)
    assert match.selected_geometry_distance_m is not None
    assert match.selected_geometry_distance_m < 10


def test_catalog_viewport_applies_waterway_policy_and_exposes_distance():
    graph_index = GraphSpatialIndex(_graph())
    place = _place("marina", osm_id=1, lat=51.001, lon=-0.995)
    result = CatalogSpatialIndex((place,), graph_index).query_viewport(
        kinds=frozenset({"marina"}),
        bounds=_bounds(),
        text="",
        policy=CatalogQueryPolicy("waterway", 120),
        route_bng=None,
        day_bng=None,
        work_budget=100,
        result_budget=10,
    )

    assert len(result.matches) == 1
    assert result.matches[0].waterway_distance_m == pytest.approx(111, abs=3)
    assert result.matches[0].distance_m == pytest.approx(111, abs=3)


def test_catalog_viewport_waterway_missing_does_not_match_but_locality_does():
    place = _place("marina", osm_id=1, lat=51.001, lon=-0.995)
    no_waterway = CatalogSpatialIndex((place,), GraphSpatialIndex(nx.Graph()))

    bounded = no_waterway.query_viewport(
        kinds=frozenset({"marina"}),
        bounds=_bounds(),
        text="",
        policy=CatalogQueryPolicy("waterway", 2_000),
        route_bng=None,
        day_bng=None,
        work_budget=100,
        result_budget=10,
    )
    locality = no_waterway.query_viewport(
        kinds=frozenset({"marina"}),
        bounds=_bounds(),
        text="",
        policy=_policy(),
        route_bng=None,
        day_bng=None,
        work_budget=100,
        result_budget=10,
    )

    assert bounded.matches == ()
    assert [match.place for match in locality.matches] == [place]
    assert locality.matches[0].waterway_distance_m is None


def test_catalog_viewport_includes_exact_waterway_radius_boundary():
    graph_index = GraphSpatialIndex(_graph())
    place = _place("pub", osm_id=1, lat=51.001, lon=-0.995)
    metric_place = wkb.loads(place.geometry_wkb)
    distance = graph_index.distance_to_waterway(metric_place)
    assert distance is not None

    result = CatalogSpatialIndex((place,), graph_index).query_viewport(
        kinds=frozenset({"pub"}),
        bounds=_bounds(),
        text="",
        policy=CatalogQueryPolicy("waterway", distance),
        route_bng=None,
        day_bng=None,
        work_budget=100,
        result_budget=10,
    )

    assert len(result.matches) == 1


@pytest.mark.parametrize("text", ["STRASSE", "straße", "  strasse  "])
def test_catalog_viewport_casefolds_primary_names(text):
    place = _place("pub", osm_id=1, lat=51.0, lon=-1.0, name="Straße Arms")
    result = CatalogSpatialIndex((place,), GraphSpatialIndex(_graph())).query_viewport(
        kinds=frozenset({"pub"}),
        bounds=_bounds(),
        text=text,
        policy=_policy(),
        route_bng=None,
        day_bng=None,
        work_budget=100,
        result_budget=10,
    )

    assert [match.place for match in result.matches] == [place]


def test_catalog_viewport_matches_alternate_name_by_substring():
    place = _place(
        "pub",
        osm_id=1,
        lat=51.0,
        lon=-1.0,
        name="Navigation Inn",
        alt_name="Towpath Arms",
    )
    result = CatalogSpatialIndex((place,), GraphSpatialIndex(_graph())).query_viewport(
        kinds=frozenset({"pub"}),
        bounds=_bounds(),
        text="PATH AR",
        policy=_policy(),
        route_bng=None,
        day_bng=None,
        work_budget=100,
        result_budget=10,
    )

    assert [match.place for match in result.matches] == [place]


@pytest.mark.parametrize("text", [None, "", "   "])
def test_catalog_viewport_treats_empty_text_as_no_filter(text):
    place = _place("pub", osm_id=1, lat=51.0, lon=-1.0)
    result = CatalogSpatialIndex((place,), GraphSpatialIndex(_graph())).query_viewport(
        kinds=frozenset({"pub"}),
        bounds=_bounds(),
        text=text,
        policy=_policy(),
        route_bng=None,
        day_bng=None,
        work_budget=100,
        result_budget=10,
    )

    assert [match.place for match in result.matches] == [place]


def test_catalog_viewport_returns_empty_for_text_without_match():
    place = _place("pub", osm_id=1, lat=51.0, lon=-1.0)
    result = CatalogSpatialIndex((place,), GraphSpatialIndex(_graph())).query_viewport(
        kinds=frozenset({"pub"}),
        bounds=_bounds(),
        text="museum",
        policy=_policy(),
        route_bng=None,
        day_bng=None,
        work_budget=100,
        result_budget=10,
    )

    assert result.matches == ()


def test_nearby_uses_full_area_geometry_not_representative_point():
    target_bng = Point(*_TO_BNG.transform(-1.0, 52.0))
    target_x, target_y = target_bng.x, target_bng.y
    wide_geometry = transform(
        LineString(
            [(target_x + 99.9991, target_y - 1_000), (target_x + 99.9991, target_y + 1_000)]
        ),
        cast(Any, _TO_WGS84.transform),
        interleaved=False,
    )
    wide = _place(
        "marina",
        osm_id=1,
        lat=52.0,
        lon=-0.9,
        geometry=wide_geometry,
        name="Wide marina",
    )
    index = CatalogSpatialIndex((wide,), GraphSpatialIndex(nx.Graph()))

    result = index.query_nearby(
        target_bng=target_bng,
        radius_m=100.0,
        kinds=frozenset({"marina"}),
        text="",
        work_budget=100,
        result_budget=10,
    )

    assert [match.place.name for match in result.matches] == ["Wide marina"]
    assert result.matches[0].distance_m == pytest.approx(100.0)


def test_nearby_enforces_remaining_work_and_result_budgets():
    index = CatalogSpatialIndex(
        (_place("pub", osm_id=1, lat=51.0, lon=-1.0),),
        GraphSpatialIndex(_graph()),
    )
    query = {
        "target_bng": Point(*_TO_BNG.transform(-1.0, 51.0)),
        "radius_m": 2_000.0,
        "kinds": frozenset({"pub"}),
        "text": "",
    }

    with pytest.raises(CatalogQueryLimitError, match="work") as work_error:
        index.query_nearby(**query, work_budget=0, result_budget=10)
    assert work_error.value.limit == "work"
    assert work_error.value.work_used == 1

    with pytest.raises(CatalogQueryLimitError, match="result") as result_error:
        index.query_nearby(**query, work_budget=100, result_budget=0)
    assert result_error.value.limit == "result"
    assert result_error.value.work_used == 1


def test_nearby_orders_matches_by_distance_then_identity():
    target = Point(*_TO_BNG.transform(-1.0, 51.0))
    places = (
        _place("pub", osm_id=9, lat=51.001, lon=-1.0),
        _place("museum", osm_id=7, lat=51.001, lon=-1.0),
        _place("pub", osm_id=2, lat=51.001, lon=-1.0, osm_type=OsmElementType.WAY),
    )

    result = CatalogSpatialIndex(places, GraphSpatialIndex(_graph())).query_nearby(
        target_bng=target,
        radius_m=2_000,
        kinds=frozenset({"pub", "museum"}),
        text="",
        work_budget=100,
        result_budget=10,
    )

    assert [match.place.identity for match in result.matches] == [
        places[1].identity,
        places[0].identity,
        places[2].identity,
    ]


def test_catalog_viewport_enforces_remaining_work_and_result_budgets():
    index = CatalogSpatialIndex(
        (_place("pub", osm_id=1, lat=51.0, lon=-1.0),),
        GraphSpatialIndex(_graph()),
    )
    query = {
        "kinds": frozenset({"pub"}),
        "bounds": _bounds(),
        "text": "",
        "policy": _policy(),
        "route_bng": None,
        "day_bng": None,
    }

    with pytest.raises(CatalogQueryLimitError, match="work"):
        index.query_viewport(**query, work_budget=0, result_budget=10)
    with pytest.raises(CatalogQueryLimitError, match="result"):
        index.query_viewport(**query, work_budget=100, result_budget=0)


def test_catalog_source_rejects_unknown_or_too_many_kinds():
    index = CatalogSpatialIndex(
        (_place("pub", osm_id=1, lat=51.0, lon=-1.0),),
        GraphSpatialIndex(_graph()),
    )

    with pytest.raises(ValueError, match="unknown"):
        index.query_viewport(
            kinds=frozenset({"unknown"}),
            bounds=_bounds(),
            text="",
            policy=_policy(),
            route_bng=None,
            day_bng=None,
            work_budget=100,
            result_budget=10,
        )

    with pytest.raises(ValueError, match="16"):
        index.query_nearby(
            target_bng=Point(*_TO_BNG.transform(-1.0, 51.0)),
            radius_m=100,
            kinds=frozenset(f"kind-{number}" for number in range(17)),
            text="",
            work_budget=100,
            result_budget=10,
        )
