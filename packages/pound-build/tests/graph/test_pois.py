from copy import deepcopy

import networkx as nx
import pytest  # pyright: ignore[reportMissingImports]
from pound.models import OsmElementType, PoiCategory  # pyright: ignore[reportMissingImports]
from pound_build.graph.pois import PoiAttachmentIndex, PoiBuildAccumulator, attach_pois
from pound_build.ingest.ir import PoiCandidate
from pyproj import Transformer  # pyright: ignore[reportMissingImports]
from shapely.errors import GEOSException
from shapely.geometry import LineString, Point, Polygon

TO_BNG = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
TO_WGS84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)


def _wgs84_point(easting: float, northing: float) -> tuple[float, float]:
    return TO_WGS84.transform(easting, northing)


def _graph(*, non_navigable_shortcut: bool = False) -> nx.Graph:
    # Deliberately asymmetric coordinates: an axis swap takes these outside BNG.
    lon0, lat0 = -1.25, 51.75
    e0, n0 = TO_BNG.transform(lon0, lat0)
    lon1, lat1 = _wgs84_point(e0 + 400, n0 + 100)
    graph = nx.Graph()
    graph.add_node(9, lat=lat0, lon=lon0)
    graph.add_node(2, lat=lat1, lon=lon1)
    graph.add_edge(9, 2, geometry=[(lat0, lon0), (lat1, lon1)], navigable=True)
    if non_navigable_shortcut:
        lon2, lat2 = _wgs84_point(e0, n0 + 300)
        graph.add_node(1, lat=lat2, lon=lon2)
        graph.add_edge(
            9,
            1,
            geometry=[(lat0, lon0), (lat2, lon2)],
            navigable=False,
        )
    return graph


def _candidate(
    geometry,
    *,
    osm_id: int = 1,
    category: PoiCategory = PoiCategory.CANAL_SERVICE,
    kind: str = "fuel",
    geometry_source: str = "point",
) -> PoiCandidate:
    return PoiCandidate(
        osm_type=OsmElementType.NODE,
        osm_id=osm_id,
        category=category,
        kind=kind,
        name="A name",
        tags={"amenity": "fuel", "opening_hours": "24/7"},
        geometry_wkt=geometry.wkt if hasattr(geometry, "wkt") else geometry,
        geometry_source=geometry_source,
    )


def _offset_from_edge(graph: nx.Graph, metres: float, along: float = 0.5) -> Point:
    edge = LineString(
        [
            TO_BNG.transform(graph.nodes[9]["lon"], graph.nodes[9]["lat"]),
            TO_BNG.transform(graph.nodes[2]["lon"], graph.nodes[2]["lat"]),
        ]
    )
    point = edge.interpolate(along, normalized=True)
    # Unit normal in BNG, so the requested boundary is exact in metres.
    (x0, y0), (x1, y1) = edge.coords
    length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    lon, lat = _wgs84_point(
        point.x - metres * (y1 - y0) / length,
        point.y + metres * (x1 - x0) / length,
    )
    return Point(lon, lat)


@pytest.mark.parametrize(
    ("category", "boundary"),
    [(PoiCategory.CANAL_SERVICE, 250.0), (PoiCategory.TRANSPORT, 1000.0)],
)
def test_corridor_boundaries_are_inclusive_in_epsg27700(category, boundary):
    graph = _graph()
    inside = attach_pois(graph, [_candidate(_offset_from_edge(graph, boundary), category=category)])
    outside = attach_pois(
        graph, [_candidate(_offset_from_edge(graph, boundary + 0.1), category=category)]
    )

    assert len(inside.pois) == 1
    assert inside.pois[0].nearest_waterway_distance_m == pytest.approx(boundary, abs=0.01)
    assert outside.pois == ()
    assert outside.summary["rejected_by_corridor"] == 1


def test_polygon_uses_full_geometry_for_distance_and_inside_representative_point():
    graph = _graph()
    near = _offset_from_edge(graph, 20)
    far = _offset_from_edge(graph, 300)
    # Concave polygon whose representative point is much farther away than its near tip.
    polygon = Polygon(
        [near.coords[0], far.coords[0], (far.x + 0.002, far.y), (near.x + 0.0001, near.y)]
    )
    result = attach_pois(graph, [_candidate(polygon, geometry_source="area")])

    assert len(result.pois) == 1
    poi = result.pois[0]
    assert polygon.covers(Point(poi.lon, poi.lat))
    assert poi.nearest_waterway_distance_m < 25


def test_invalid_geometry_is_repaired_and_empty_geometry_is_reported():
    graph = _graph()
    centre = _offset_from_edge(graph, 20)
    bowtie = Polygon(
        [
            (centre.x, centre.y),
            (centre.x + 0.001, centre.y + 0.001),
            (centre.x, centre.y + 0.001),
            (centre.x + 0.001, centre.y),
            (centre.x, centre.y),
        ]
    )
    result = attach_pois(
        graph,
        [
            _candidate(bowtie, geometry_source="area"),
            _candidate("POINT EMPTY", osm_id=2),
        ],
    )

    assert [poi.osm_id for poi in result.pois] == [1]
    assert result.summary["empty_geometry"] == 1


def test_repaired_area_must_remain_polygonal():
    graph = _graph()
    centre = _offset_from_edge(graph, 20)
    collapsed = (
        f"POLYGON (({centre.x} {centre.y}, {centre.x + 0.001} {centre.y}, "
        f"{centre.x + 0.002} {centre.y}, {centre.x} {centre.y}))"
    )

    result = attach_pois(graph, [_candidate(collapsed, geometry_source="area")])

    assert result.pois == ()
    assert result.summary["invalid_geometry"] == 1


def test_axis_order_projection_attachment_and_provenance_are_preserved():
    graph = _graph()
    point = _offset_from_edge(graph, 50)
    candidate = _candidate(
        LineString([point, Point(point.x + 0.0001, point.y + 0.0001)]),
        geometry_source="derived_path",
    )
    before_graph, before_candidate = deepcopy(graph), candidate.model_copy(deep=True)

    poi = attach_pois(graph, [candidate]).pois[0]

    assert poi.nearest_edge == (2, 9)
    assert poi.nearest_node_uid in (2, 9)
    assert -2 < poi.projected_lon < 0
    assert 51 < poi.projected_lat < 52
    edge_bng = LineString(
        [TO_BNG.transform(lon, lat) for lat, lon in graph.edges[9, 2]["geometry"]]
    )
    projected_bng = Point(TO_BNG.transform(poi.projected_lon, poi.projected_lat))
    assert edge_bng.distance(projected_bng) < 0.01
    assert (poi.osm_type, poi.osm_id, poi.kind) == candidate.identity
    assert (poi.name, poi.source_tags, poi.geometry_source) == (
        candidate.name,
        candidate.tags,
        candidate.geometry_source,
    )
    assert nx.utils.graphs_equal(graph, before_graph)
    assert candidate == before_candidate


def test_path_display_point_is_closest_point_to_waterway():
    graph = _graph()
    path = LineString([_offset_from_edge(graph, 200), _offset_from_edge(graph, 40)])
    poi = attach_pois(graph, [_candidate(path, geometry_source="derived_path")]).pois[0]

    displayed_bng = Point(TO_BNG.transform(poi.lon, poi.lat))
    path_bng = LineString([TO_BNG.transform(x, y) for x, y in path.coords])
    assert displayed_bng.distance(path_bng) < 0.01
    assert poi.nearest_waterway_distance_m == pytest.approx(40, abs=0.02)


@pytest.mark.parametrize(
    "updates",
    [
        {"access": "private", "tags": {"boat": "yes", "access": "yes"}},
        {"tags": {"access": "permit"}},
        {"boat": "private"},
    ],
)
def test_poi_index_reuses_public_access_policy(updates):
    graph = _graph()
    graph.edges[9, 2].update(updates)
    assert PoiAttachmentIndex(graph).edge_keys == []


def test_deterministic_edge_and_node_ties_and_non_navigable_edges():
    graph = _graph(non_navigable_shortcut=True)
    # Lies on the non-navigable shortcut, but must attach to routing edge (2, 9).
    candidate = _candidate(_offset_from_edge(graph, 100, along=0))
    poi = attach_pois(graph, [candidate]).pois[0]
    assert poi.nearest_edge == (2, 9)
    assert poi.nearest_node_uid == 9

    # Two identical routing edges: canonical UID pair breaks the edge tie.
    graph.add_node(3, **graph.nodes[9])
    graph.add_node(4, **graph.nodes[2])
    graph.add_edge(3, 4, geometry=list(graph.edges[9, 2]["geometry"]), navigable=True)
    assert attach_pois(graph, [candidate]).pois[0].nearest_edge == (2, 9)

    midpoint = _candidate(_offset_from_edge(graph, 0, along=0.5), osm_id=2)
    midpoint_poi = attach_pois(graph, [midpoint]).pois[0]
    assert midpoint_poi.nearest_edge == (2, 9)
    assert midpoint_poi.nearest_node_uid == 2


def test_duplicate_identity_is_deduplicated_deterministically():
    graph = _graph()
    first = _candidate(_offset_from_edge(graph, 20))
    duplicate = first.model_copy(update={"name": "later duplicate"})
    result = attach_pois(graph, [duplicate, first])

    assert len(result.pois) == 1
    assert result.pois[0].name == "A name"
    assert result.summary["duplicate_identities"] == 1


def test_duplicate_identity_winner_matches_legacy_json_order():
    graph = _graph()
    first = _candidate(_offset_from_edge(graph, 20)).model_copy(
        update={
            "name": "Zulu",
            "tags": {"amenity": "fuel", "operator": "Zulu"},
        }
    )
    second = _candidate(_offset_from_edge(graph, 30)).model_copy(
        update={
            "name": "Alpha",
            "tags": {"amenity": "fuel", "operator": "Alpha"},
        }
    )
    expected = min((first, second), key=lambda candidate: candidate.model_dump_json())

    forward = attach_pois(graph, [first, second])
    reverse = attach_pois(graph, [second, first])

    assert forward.pois == reverse.pois
    assert len(forward.pois) == 1
    assert (forward.pois[0].name, forward.pois[0].source_tags) == (
        expected.name,
        expected.tags,
    )


def test_streaming_accumulator_reuses_index_and_matches_unique_batch_attachment():
    graph = _graph()
    candidates = [
        _candidate(_offset_from_edge(graph, 20), osm_id=2),
        _candidate(_offset_from_edge(graph, 30), osm_id=1),
        _candidate(_offset_from_edge(graph, 2000), osm_id=3),
    ]
    index = PoiAttachmentIndex(graph)
    tree = index.tree
    accumulator = PoiBuildAccumulator(index)

    for candidate in candidates:
        accumulator.add(candidate)

    result = accumulator.build_result()
    assert index.tree is tree
    assert accumulator.accepted_count == 2
    assert result == attach_pois(graph, candidates)
    assert [poi.osm_id for poi in result.pois] == [1, 2]


def test_streaming_accumulator_chooses_legacy_winner_for_accepted_duplicates():
    graph = _graph()
    zulu = _candidate(_offset_from_edge(graph, 20)).model_copy(
        update={"name": "Zulu", "tags": {"amenity": "fuel", "operator": "Zulu"}}
    )
    alpha = _candidate(_offset_from_edge(graph, 30)).model_copy(
        update={"name": "Alpha", "tags": {"amenity": "fuel", "operator": "Alpha"}}
    )
    expected = attach_pois(graph, [zulu, alpha])

    forward = PoiBuildAccumulator(PoiAttachmentIndex(graph))
    reverse = PoiBuildAccumulator(PoiAttachmentIndex(graph))
    for candidate in (zulu, alpha):
        forward.add(candidate)
    for candidate in (alpha, zulu):
        reverse.add(candidate)

    assert forward.build_result() == expected
    assert reverse.build_result() == expected


def test_streaming_accumulator_matches_legacy_when_duplicate_winner_is_rejected():
    graph = _graph()
    valid = _candidate(_offset_from_edge(graph, 20)).model_copy(update={"name": "Zulu"})
    invalid = valid.model_copy(update={"name": "Alpha", "geometry_wkt": "not wkt"})
    assert invalid.model_dump_json() < valid.model_dump_json()
    expected = attach_pois(graph, [valid, invalid])

    for candidates in ((valid, invalid), (invalid, valid)):
        repeated = PoiBuildAccumulator(PoiAttachmentIndex(graph))
        batched = PoiBuildAccumulator(PoiAttachmentIndex(graph))
        for candidate in candidates:
            repeated.add(candidate)
        batched.add_many(candidates)

        assert repeated.build_result() == expected
        assert batched.build_result() == expected


def test_streaming_accumulator_counts_rejected_duplicate_once_like_legacy():
    graph = _graph()
    rejected = _candidate(_offset_from_edge(graph, 2000))
    expected = attach_pois(graph, [rejected, rejected])
    accumulator = PoiBuildAccumulator(PoiAttachmentIndex(graph))

    accumulator.add_many([rejected, rejected])

    assert accumulator.build_result() == expected


def test_streaming_accumulator_can_discard_unique_rejected_winners():
    graph = _graph()
    accumulator = PoiBuildAccumulator(PoiAttachmentIndex(graph), retain_rejected_winners=False)

    accumulator.add(_candidate(_offset_from_edge(graph, 2000)))

    assert accumulator.build_result().summary["rejected_by_corridor"] == 1
    assert accumulator._winners == {}


def test_batched_attachment_matches_single_candidate_results_exactly():
    graph = _graph(non_navigable_shortcut=True)
    candidates = [
        _candidate(_offset_from_edge(graph, 20), osm_id=3),
        _candidate(_offset_from_edge(graph, 2000), osm_id=1),
        _candidate("POINT EMPTY", osm_id=2),
        _candidate(_offset_from_edge(graph, 0, along=0.5), osm_id=4),
    ]
    index = PoiAttachmentIndex(graph)

    batched = index.attach_many(candidates)
    individual = [index.attach(candidate) for candidate in candidates]

    assert batched == individual


def test_batched_attachment_isolates_geometry_repair_failures():
    graph = _graph()
    candidates = [
        _candidate("POLYGON ((0 0, NaN 1, 1 1, 0 0))", osm_id=1, geometry_source="area"),
        _candidate(_offset_from_edge(graph, 20), osm_id=2),
    ]
    index = PoiAttachmentIndex(graph)

    with pytest.warns(RuntimeWarning, match="invalid value encountered"):
        batched = index.attach_many(candidates)
    with pytest.warns(RuntimeWarning, match="invalid value encountered"):
        individual = [index.attach(candidate) for candidate in candidates]

    assert batched == individual


def test_batched_attachment_contains_make_valid_exception(monkeypatch):
    from pound_build.graph import pois as pois_module

    graph = _graph()
    candidates = [
        _candidate(
            "POLYGON ((0 0, 1 1, 1 0, 0 1, 0 0))",
            osm_id=1,
            geometry_source="area",
        ),
        _candidate(_offset_from_edge(graph, 20), osm_id=2),
    ]
    index = PoiAttachmentIndex(graph)

    def fail_repair(_geometry):
        raise GEOSException("forced repair failure")

    monkeypatch.setattr(pois_module, "make_valid", fail_repair)

    assert index.attach_many(candidates) == [
        (None, "invalid_geometry"),
        index.attach(candidates[1]),
    ]


def test_batched_attachment_vectorizes_geometry_hot_path(monkeypatch):
    from pound_build.graph import pois as pois_module

    graph = _graph(non_navigable_shortcut=True)
    centre = _offset_from_edge(graph, 20)
    candidates = [
        _candidate(centre, osm_id=1),
        _candidate(_offset_from_edge(graph, 2000), osm_id=2),
        _candidate("POINT EMPTY", osm_id=3),
        _candidate("not wkt", osm_id=4),
        _candidate(
            LineString([centre, Point(centre.x + 0.0001, centre.y + 0.0001)]),
            osm_id=5,
            geometry_source="derived_path",
        ),
        _candidate(
            Polygon(
                [
                    (centre.x, centre.y),
                    (centre.x + 0.0001, centre.y),
                    (centre.x + 0.0001, centre.y + 0.0001),
                    (centre.x, centre.y),
                ]
            ),
            osm_id=6,
            geometry_source="area",
        ),
    ]
    index = PoiAttachmentIndex(graph)
    expected = [index.attach(candidate) for candidate in candidates]

    def scalar_hot_path(*_args, **_kwargs):
        raise AssertionError("used scalar geometry hot path")

    monkeypatch.setattr(pois_module, "_normalized_geometry", scalar_hot_path)
    monkeypatch.setattr(pois_module, "nearest_points", scalar_hot_path)

    assert index.attach_many(candidates) == expected


def test_streaming_accumulator_add_many_matches_repeated_add():
    graph = _graph()
    candidates = [
        _candidate(_offset_from_edge(graph, 20), osm_id=2),
        _candidate(_offset_from_edge(graph, 30), osm_id=1),
        _candidate(_offset_from_edge(graph, 2000), osm_id=3),
    ]
    batched = PoiBuildAccumulator(PoiAttachmentIndex(graph))
    repeated = PoiBuildAccumulator(PoiAttachmentIndex(graph))

    batched.add_many(candidates)
    for candidate in candidates:
        repeated.add(candidate)

    assert batched.build_result() == repeated.build_result()


def test_attachment_index_projects_all_edge_geometries_in_one_vectorized_call(monkeypatch):
    from pound_build.graph import pois as pois_module

    graph = _graph()
    graph.add_node(3, lat=graph.nodes[9]["lat"] + 0.01, lon=graph.nodes[9]["lon"])
    graph.add_edge(9, 3, navigable=True)
    calls = []
    real_transform = pois_module.transform

    def spy_transform(geometries, *args, **kwargs):
        calls.append(geometries)
        return real_transform(geometries, *args, **kwargs)

    monkeypatch.setattr(pois_module, "transform", spy_transform)

    PoiAttachmentIndex(graph)

    assert len(calls) == 1
    assert len(calls[0]) == 2


def test_batched_attachment_uses_bounded_corridor_query():
    graph = _graph()
    index = PoiAttachmentIndex(graph)
    real_tree = index.tree
    assert real_tree is not None

    class BoundedTree:
        geometries = real_tree.geometries

        def query(self, *args, **kwargs):
            assert kwargs["predicate"] == "dwithin"
            return real_tree.query(*args, **kwargs)

        def query_nearest(self, *_args, **_kwargs):
            raise AssertionError("used unbounded nearest query")

    index.tree = BoundedTree()  # pyright: ignore[reportAttributeAccessIssue]
    candidates = [
        _candidate(_offset_from_edge(graph, 20), osm_id=1),
        _candidate(_offset_from_edge(graph, 2000), osm_id=2),
    ]

    assert index.attach_many(candidates) == [
        PoiAttachmentIndex(graph).attach(candidate) for candidate in candidates
    ]
