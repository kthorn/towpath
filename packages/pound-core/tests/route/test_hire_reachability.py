import copy
from dataclasses import dataclass
from types import SimpleNamespace

import networkx as nx
import pytest
from pound.models import WayDimensions
from pound.route.hire_reachability import HireReachabilityError, compute_hire_base_reachability
from pound.schemas import CanalPointHandle


@dataclass(frozen=True)
class Anchor:
    identity: str
    handle: CanalPointHandle

    @property
    def seed(self):
        return SimpleNamespace(identity=self.identity)


def graph_with_route() -> nx.Graph:
    graph = nx.Graph()
    for uid in (1, 2, 3, 4):
        graph.add_node(uid, lat=51 + uid * 0.001, lon=-1.0, movable_bridge_ids=())
    for u, v in ((1, 2), (2, 3), (3, 4)):
        graph.add_edge(
            u,
            v,
            length_m=1_200.0,
            locks=0,
            dimensions=WayDimensions(),
            movable_bridge_ids=(),
            routing_eligible=True,
            navigable=True,
        )
    return graph


def test_reachability_uses_directional_maps_and_excludes_disconnected_base():
    graph = graph_with_route()
    graph.add_node(10, lat=51.002, lon=-1.0, movable_bridge_ids=())
    graph.add_node(11, lat=51.003, lon=-1.0, movable_bridge_ids=())
    graph.add_edge(
        10,
        11,
        length_m=1_200.0,
        locks=0,
        dimensions=WayDimensions(),
        movable_bridge_ids=(),
        routing_eligible=True,
        navigable=True,
    )
    target = CanalPointHandle(edge=(1, 2), fraction=0.5)
    anchors = (
        Anchor("provider/connected", CanalPointHandle(edge=(2, 3), fraction=0.5)),
        Anchor("provider/disconnected", CanalPointHandle(edge=(10, 11), fraction=0.5)),
    )

    matches = compute_hire_base_reachability(
        target,
        anchors,
        graph=graph,
        cutoff_min=20.0,
        boat_length_m=None,
        boat_beam_m=None,
        boat_draft_m=None,
        boat_height_m=None,
        movable_bridge_delay_min=5.0,
    )

    assert [match.identity for match in matches] == ["provider/connected"]
    assert matches[0].one_way_minutes == pytest.approx(15.0)
    assert matches[0].return_minutes == pytest.approx(15.0)


def test_reachability_supports_exact_same_edge_interior():
    graph = graph_with_route()
    target = CanalPointHandle(edge=(1, 2), fraction=0.75)
    anchor = Anchor("provider/same", CanalPointHandle(edge=(1, 2), fraction=0.25))

    matches = compute_hire_base_reachability(
        target,
        (anchor,),
        graph=graph,
        cutoff_min=10.0,
        boat_length_m=None,
        boat_beam_m=None,
        boat_draft_m=None,
        boat_height_m=None,
        movable_bridge_delay_min=5.0,
    )

    assert len(matches) == 1
    assert matches[0].one_way_minutes == pytest.approx(7.5)
    assert matches[0].return_minutes == pytest.approx(7.5)


def test_reachability_charges_arrived_node_bridges_directionally():
    graph = graph_with_route()
    graph.nodes[2]["movable_bridge_ids"] = ("bridge-2",)
    graph.nodes[3]["movable_bridge_ids"] = ("bridge-3",)
    target = CanalPointHandle(edge=(1, 2), fraction=0.0)
    anchor = Anchor("provider/endpoint", CanalPointHandle(edge=(2, 3), fraction=1.0))

    matches = compute_hire_base_reachability(
        target,
        (anchor,),
        graph=graph,
        cutoff_min=60.0,
        boat_length_m=None,
        boat_beam_m=None,
        boat_draft_m=None,
        boat_height_m=None,
        movable_bridge_delay_min=5.0,
    )

    assert matches[0].one_way_minutes == pytest.approx(35.0)
    assert matches[0].return_minutes == pytest.approx(40.0)


def test_reachability_applies_routing_dimensions_and_rejects_interior_ineligible_handles():
    graph = graph_with_route()
    graph.edges[2, 3]["dimensions"] = WayDimensions(max_beam_m=1.0)
    target = CanalPointHandle(edge=(1, 2), fraction=0.5)
    anchor = Anchor("provider/narrow", CanalPointHandle(edge=(2, 3), fraction=0.5))

    assert compute_hire_base_reachability(
        target,
        (anchor,),
        graph=graph,
        cutoff_min=60.0,
        boat_length_m=None,
        boat_beam_m=2.0,
        boat_draft_m=None,
        boat_height_m=None,
        movable_bridge_delay_min=5.0,
    ) == ()

    graph.edges[1, 2]["candidate_eligible"] = False
    with pytest.raises(ValueError, match="candidate-eligible"):
        compute_hire_base_reachability(
            target,
            (anchor,),
            graph=graph,
            cutoff_min=60.0,
            boat_length_m=None,
            boat_beam_m=None,
            boat_draft_m=None,
            boat_height_m=None,
            movable_bridge_delay_min=5.0,
        )


def test_reachability_does_not_mutate_graph():
    graph = graph_with_route()
    before = copy.deepcopy(graph)
    compute_hire_base_reachability(
        CanalPointHandle(edge=(1, 2), fraction=0.5),
        (Anchor("provider/base", CanalPointHandle(edge=(2, 3), fraction=0.5)),),
        graph=graph,
        cutoff_min=60.0,
        boat_length_m=None,
        boat_beam_m=None,
        boat_draft_m=None,
        boat_height_m=None,
        movable_bridge_delay_min=5.0,
    )
    assert nx.utils.graphs_equal(graph, before)


def test_reachability_work_limit_raises_typed_error():
    graph = graph_with_route()
    with pytest.raises(HireReachabilityError) as error:
        compute_hire_base_reachability(
            CanalPointHandle(edge=(1, 2), fraction=0.5),
            (Anchor("provider/base", CanalPointHandle(edge=(2, 3), fraction=0.5)),),
            graph=graph,
            cutoff_min=60.0,
            boat_length_m=None,
            boat_beam_m=None,
            boat_draft_m=None,
            boat_height_m=None,
            movable_bridge_delay_min=5.0,
            max_work=0,
        )
    assert error.value.code == "reachability_search_limit"
