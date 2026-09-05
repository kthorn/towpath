import networkx as nx
import pytest

from pound.graph.artifact import prepare_artifact
from pound.graph.turnarounds import build_turnarounds, validate_turnarounds
from pound.ingest.ir import NodeKind, WaterwayFeatures, WaterwayNode


def _features(nodes):
    return WaterwayFeatures(
        ways=[], nodes=nodes, source="overpass", fetched_at="2026-09-05T00:00:00Z", bbox=None
    )


def _graph():
    graph = nx.Graph()
    graph.add_node(1, lat=51.0, lon=-1.0, osm_node_ids={"100"}, movable_bridge_ids=())
    graph.add_node(2, lat=51.0, lon=-0.99, osm_node_ids={"101"}, movable_bridge_ids=())
    graph.add_edge(
        1,
        2,
        osm_way_id=10,
        name="Canal",
        kind="canal",
        length_m=700.0,
        dimensions=None,
        has_tunnel=False,
        has_movable_bridge=False,
        locks=0,
        geometry=[(51.0, -1.0), (51.0, -0.99)],
        movable_bridge_ids=("way:10",),
        tunnel_restrictions=(),
        access_caveats=(),
    )
    return graph


def _turning_node(osm_id=999, lat=51.0, lon=-0.995, **tags):
    all_tags = {"waterway": "turning_point", **tags}
    return WaterwayNode(osm_id=osm_id, lat=lat, lon=lon, tags=all_tags, kind=NodeKind.TURNING_POINT)


def test_interior_turning_point_splits_edge_and_preserves_cost_and_infrastructure():
    graph = _graph()
    original = graph.edges[1, 2].copy()

    attached, report = build_turnarounds(graph, _features([_turning_node()]))

    assert report["unmatched"] == []
    record = attached.graph["turnarounds"][0]
    assert record["node_uid"] not in {1, 2}
    uid = record["node_uid"]
    assert attached.has_edge(1, uid) and attached.has_edge(uid, 2)
    assert str(_turning_node().osm_id) in attached.nodes[uid]["osm_node_ids"]
    assert attached.edges[1, uid]["length_m"] + attached.edges[uid, 2]["length_m"] == pytest.approx(
        original["length_m"]
    )
    bridge_ids = (
        attached.edges[1, uid]["movable_bridge_ids"] + attached.edges[uid, 2]["movable_bridge_ids"]
    )
    assert bridge_ids == original["movable_bridge_ids"]


@pytest.mark.parametrize("lon", [-0.9975, -0.9925])
def test_split_places_midpoint_bridge_once_with_reversed_edge_geometry(lon):
    graph = _graph()
    graph.edges[1, 2]["geometry"] = list(reversed(graph.edges[1, 2]["geometry"]))

    attached, _ = build_turnarounds(graph, _features([_turning_node(lon=lon)]))

    children = list(attached.edges(data=True))
    assert sum(len(data["movable_bridge_ids"]) for _, _, data in children) == 1
    uid = attached.graph["turnarounds"][0]["node_uid"]
    assert attached.nodes[uid]["lon"] == pytest.approx(lon, abs=1e-6)


def test_reversed_curved_geometry_splits_without_duplicate_polyline_vertex():
    graph = _graph()
    graph.edges[1, 2]["geometry"] = [
        (51.0, -0.99),
        (51.001, -0.997),
        (51.0, -1.0),
    ]
    node = _turning_node(lat=51.0005, lon=-0.9935)

    attached, _ = build_turnarounds(graph, _features([node]))

    uid = attached.graph["turnarounds"][0]["node_uid"]
    left = attached.edges[1, uid]["geometry"]
    right = attached.edges[uid, 2]["geometry"]
    assert left[-1] == right[0]
    assert len(left) + len(right) == 5


def test_repeated_off_node_points_follow_split_descendants_past_parallel_edge():
    graph = _graph()
    graph.add_node(3, lat=51.0001, lon=-1.0, osm_node_ids={"103"}, movable_bridge_ids=())
    graph.add_node(4, lat=51.0001, lon=-0.99, osm_node_ids={"104"}, movable_bridge_ids=())
    graph.add_edge(
        3,
        4,
        **{
            **graph.edges[1, 2],
            "geometry": [(51.0001, -1.0), (51.0001, -0.99)],
            "osm_way_id": 11,
        },
    )
    nodes = [
        _turning_node(osm_id=901, lon=-0.9975),
        _turning_node(osm_id=902, lon=-0.9925),
    ]

    attached, _ = build_turnarounds(graph, _features(nodes))

    records = attached.graph["turnarounds"]
    assert len(records) == 2
    assert len({record["node_uid"] for record in records}) == 2
    assert all(
        attached.nodes[record["node_uid"]]["lat"] == pytest.approx(51.0, abs=1e-6)
        for record in records
    )


def test_reversed_edge_endpoint_projection_attaches_to_correct_uid():
    graph = _graph()
    graph.edges[1, 2]["geometry"] = list(reversed(graph.edges[1, 2]["geometry"]))
    node = _turning_node(lat=51.00001, lon=-1.0)

    attached, _ = build_turnarounds(graph, _features([node]))

    assert attached.graph["turnarounds"][0]["node_uid"] == 1


def test_nonrouting_incident_edge_does_not_create_junction():
    graph = _graph()
    graph.add_node(3, lat=51.001, lon=-0.995, osm_node_ids={"103"}, movable_bridge_ids=())
    graph.add_edge(
        1,
        3,
        **{
            **graph.edges[1, 2],
            "routing_eligible": False,
            "geometry": [(51.0, -1.0), (51.001, -0.995)],
        },
    )
    graph.add_node(4, lat=50.999, lon=-0.995, osm_node_ids={"104"}, movable_bridge_ids=())
    graph.add_edge(
        1,
        4,
        **{
            **graph.edges[1, 2],
            "geometry": [(51.0, -1.0), (50.999, -0.995)],
        },
    )

    attached, report = build_turnarounds(graph, _features([]))

    assert report["junctions"] == 0
    assert attached.graph["turnarounds"] == []


def test_inferred_bridge_position_survives_multiple_splits():
    graph = _graph()
    nodes = [
        _turning_node(osm_id=911, lon=-0.9975),
        _turning_node(osm_id=912, lon=-0.996),
        _turning_node(osm_id=913, lon=-0.994),
    ]

    attached, _ = build_turnarounds(graph, _features(nodes))

    bridge_edges = [
        data for _, _, data in attached.edges(data=True) if "way:10" in data["movable_bridge_ids"]
    ]
    assert len(bridge_edges) == 1
    assert bridge_edges[0]["length_m"] == pytest.approx(140.0, abs=20.0)


def test_equal_distance_turning_point_is_reported_ambiguous_and_not_indexed():
    graph = _graph()
    graph.add_node(3, lat=51.0002, lon=-1.0, osm_node_ids={"102"}, movable_bridge_ids=())
    graph.add_node(4, lat=51.0002, lon=-0.99, osm_node_ids={"103"}, movable_bridge_ids=())
    graph.add_edge(3, 4, **{**graph.edges[1, 2], "geometry": [(51.0002, -1.0), (51.0002, -0.99)]})

    attached, report = build_turnarounds(graph, _features([_turning_node(lat=51.0001, lon=-0.995)]))

    assert report["ambiguous"]
    assert attached.graph["turnarounds"] == []


def test_tied_edges_sharing_an_endpoint_attach_once_to_that_endpoint():
    graph = _graph()
    graph.add_node(3, lat=51.0, lon=-1.01, osm_node_ids={"103"}, movable_bridge_ids=())
    graph.add_edge(
        1,
        3,
        **{
            **graph.edges[1, 2],
            "osm_way_id": 12,
            "geometry": [(51.0, -1.0), (51.0, -1.01)],
        },
    )
    node = _turning_node(lat=51.00001, lon=-1.0)

    attached, report = build_turnarounds(graph, _features([node]))

    assert report["ambiguous"] == []
    assert attached.graph["turnarounds"][0]["node_uid"] == 1
    assert attached.number_of_edges() == graph.number_of_edges()


@pytest.mark.parametrize("private_id", [920, 921])
def test_restricted_duplicate_attachment_suppresses_public_record(private_id):
    public_id = 921 if private_id == 920 else 920
    public = _turning_node(osm_id=public_id)
    private = _turning_node(osm_id=private_id, access="private")

    attached, report = build_turnarounds(graph=_graph(), features=_features([public, private]))

    assert attached.graph["turnarounds"] == []
    assert report["restricted"] == [f"node/{private_id}"]


def test_degree_three_canal_junction_is_indexed_without_turning_evidence():
    graph = nx.Graph()
    graph.add_node(1, lat=51.0, lon=-1.0, osm_node_ids={"100"}, movable_bridge_ids=())
    for uid, lon in ((2, -0.99), (3, -1.01), (4, -1.0)):
        graph.add_node(
            uid,
            lat=51.0 + (uid == 4) * 0.01,
            lon=lon,
            osm_node_ids={str(uid)},
            movable_bridge_ids=(),
        )
        graph.add_edge(
            1,
            uid,
            osm_way_id=uid,
            name="Canal",
            kind="canal" if uid != 4 else "river",
            length_m=100.0,
            dimensions=None,
            has_tunnel=False,
            has_movable_bridge=False,
            locks=0,
            geometry=[(51.0, -1.0), (graph.nodes[uid]["lat"], lon)],
            movable_bridge_ids=(),
            tunnel_restrictions=(),
            access_caveats=(),
        )

    attached, report = build_turnarounds(graph, _features([]))

    assert report["junctions"] == 1
    assert len(attached.graph["turnarounds"]) == 1
    assert attached.graph["turnarounds"][0]["eligibility_basis"] == "junction_assumption"


def test_turning_restrictions_and_provenance_are_normalized():
    attached, _ = build_turnarounds(
        _graph(),
        _features(
            [
                _turning_node(
                    maxlength="18",
                    maxwidth="2.4",
                    maxdraft="0.8",
                    maxheight="2.1",
                    turning="no",
                    name="Private basin",
                )
            ]
        ),
    )

    record = attached.graph["turnarounds"][0]
    assert record["turning_limits"] == {
        "boat_length_m": 18.0,
        "boat_beam_m": 2.4,
        "boat_draft_m": 0.8,
        "boat_height_m": 2.1,
        "prohibited": True,
    }
    assert record["sources"][0]["evidence"]["source_coordinate"] == {
        "lat": 51.0,
        "lon": -0.995,
    }


def test_private_turning_point_is_excluded_from_index():
    attached, report = build_turnarounds(_graph(), _features([_turning_node(access="private")]))

    assert attached.graph["turnarounds"] == []
    assert report["restricted"] == ["node/999"]


def test_artifact_validates_turnaround_references_and_round_trips():
    graph = _graph()
    graph.graph["turnarounds"] = [
        {
            "turnaround_id": "osm:node/999",
            "kind": "winding_hole",
            "node_uid": 1,
            "coordinate": {"lat": 51.0, "lon": -1.0},
            "display_name": "Winding hole",
            "eligibility_basis": "mapped_winding_hole",
            "sources": [
                {
                    "source": "overpass",
                    "identity": "node/999",
                    "source_date": "2026-09-05T00:00:00Z",
                    "attribution": "© OpenStreetMap contributors",
                }
            ],
            "turning_limits": {"boat_length_m": 18.0},
        }
    ]
    graph.graph["turnaround_report"] = {}
    metadata = {
        "artifact_revision": "revision-1",
        "source": "overpass",
        "fetched_at": "2026-09-05T00:00:00Z",
        "built_at": "2026-09-05T01:00:00Z",
        "validation": {},
        "poi_summary": {},
    }

    artifact = prepare_artifact(graph, [], metadata)
    assert artifact.graph.graph["turnarounds"][0]["node_uid"] == 1
    artifact.graph.graph["turnarounds"][0]["node_uid"] = 900
    with pytest.raises(ValueError, match="turnaround"):
        validate_turnarounds(artifact.graph)
