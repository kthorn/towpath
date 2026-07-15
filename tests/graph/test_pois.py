from copy import deepcopy

import networkx as nx
import pytest
from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon

from pound.graph.pois import PoiAttachmentIndex, PoiBuildAccumulator, attach_pois
from pound.ingest.ir import OsmElementType, PoiCandidate, PoiCategory

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
        [(centre.x, centre.y), (centre.x + 0.001, centre.y + 0.001),
         (centre.x, centre.y + 0.001), (centre.x + 0.001, centre.y), (centre.x, centre.y)]
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
