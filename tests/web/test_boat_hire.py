import csv
import math
from pathlib import Path
from typing import TypedDict, Unpack

import networkx as nx
import pytest
from shapely.geometry import Point

import pound.web.boat_hire as boat_hire
from pound.ingest.ir import WayDimensions
from pound.web.boat_hire import (
    BOAT_HIRE_ENRICHMENT_FIELDS,
    BoatHireAnchor,
    BoatHireSeed,
    load_boat_hire_seeds,
    select_boat_hire_reachability,
    snap_boat_hire_bases,
)


def _row(**changes: str) -> dict[str, str]:
    row = dict.fromkeys(BOAT_HIRE_ENRICHMENT_FIELDS, "")
    row.update(
        record_type="company_base",
        source_provider_id="provider",
        location_id="base:one",
        latitude="51.0",
        longitude="-1.0",
        osm_url="https://www.openstreetmap.org/node/1",
        exclude="",
    )
    row.update(changes)
    return row


def _csv(tmp_path: Path, *rows: dict[str, str]) -> Path:
    path = tmp_path / "boat-hire.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=BOAT_HIRE_ENRICHMENT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


class _Projector:
    def __init__(self, edge: tuple[int, int], distance: float) -> None:
        self.edge = edge
        self.distance = distance

    def project_to_nearest_edge(self, latitude: float, longitude: float):
        return self.edge, Point(longitude, latitude), self.distance


def test_loader_includes_blank_and_false_rows_but_ignores_true_rows(tmp_path: Path):
    path = _csv(
        tmp_path,
        _row(location_id="blank", exclude=""),
        _row(location_id="false", exclude="false"),
        _row(location_id="excluded", exclude="true", latitude="", longitude=""),
    )

    assert load_boat_hire_seeds(path) == (
        BoatHireSeed("provider", "blank", 51.0, -1.0),
        BoatHireSeed("provider", "false", 51.0, -1.0),
    )


def test_loader_accepts_evidence_only_drifters_map_row(tmp_path: Path):
    path = _csv(
        tmp_path,
        _row(
            source_provider_id="drifters",
            osm_url="",
            evidence_url="https://www.drifters.co.uk/uk-canal-map/",
        ),
    )

    assert load_boat_hire_seeds(path) == (BoatHireSeed("drifters", "base:one", 51.0, -1.0),)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"exclude": "yes"}, "exclude"),
        ({"source_provider_id": ""}, "source_provider_id"),
        ({"latitude": "nan"}, "latitude"),
        ({"longitude": "181"}, "longitude"),
        ({"osm_url": "http://example.test/base", "evidence_url": ""}, "evidence"),
    ],
)
def test_loader_rejects_invalid_active_rows(tmp_path: Path, changes: dict[str, str], message: str):
    with pytest.raises(ValueError, match=message):
        load_boat_hire_seeds(_csv(tmp_path, _row(**changes)))


def test_loader_rejects_duplicate_provider_location_identity(tmp_path: Path):
    with pytest.raises(ValueError, match="duplicate"):
        load_boat_hire_seeds(_csv(tmp_path, _row(), _row()))


def test_loader_accepts_distinct_pairs_that_collide_as_joined_display_strings(tmp_path: Path):
    path = _csv(
        tmp_path,
        _row(source_provider_id="a/b", location_id="c"),
        _row(source_provider_id="a", location_id="b/c"),
    )

    assert load_boat_hire_seeds(path) == (
        BoatHireSeed("a/b", "c", 51.0, -1.0),
        BoatHireSeed("a", "b/c", 51.0, -1.0),
    )


def test_loader_rejects_surplus_row_cells(tmp_path: Path):
    path = tmp_path / "boat-hire.csv"
    row = _row()
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(BOAT_HIRE_ENRICHMENT_FIELDS)
        writer.writerow([row[field] for field in BOAT_HIRE_ENRICHMENT_FIELDS] + ["surplus"])

    with pytest.raises(ValueError, match="surplus"):
        load_boat_hire_seeds(path)


def test_loader_rejects_header_mismatch_with_path(tmp_path: Path):
    path = tmp_path / "boat-hire.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerow(BOAT_HIRE_ENRICHMENT_FIELDS[:-1])

    with pytest.raises(ValueError) as excinfo:
        load_boat_hire_seeds(path)
    assert str(path) in str(excinfo.value)
    assert "header" in str(excinfo.value)


@pytest.mark.parametrize("content", [None, ""])
def test_loader_reports_missing_or_empty_csv_path(tmp_path: Path, content: str | None):
    path = tmp_path / "boat-hire.csv"
    if content is not None:
        path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        load_boat_hire_seeds(path)
    assert str(path) in str(excinfo.value)


def test_loader_reports_unreadable_csv_path(tmp_path: Path):
    path = tmp_path / "boat-hire-dir"
    path.mkdir()

    with pytest.raises(ValueError) as excinfo:
        load_boat_hire_seeds(path)
    assert str(path) in str(excinfo.value)


def test_loader_reports_invalid_utf8_csv_path(tmp_path: Path):
    path = tmp_path / "boat-hire.csv"
    path.write_bytes(b"\xff\xfe\x00invalid-utf8")

    with pytest.raises(ValueError) as excinfo:
        load_boat_hire_seeds(path)
    assert str(path) in str(excinfo.value)
    assert "Could not read" in str(excinfo.value)


def test_loader_selects_review_positive_row_regardless_of_provenance(tmp_path: Path):
    path = _csv(
        tmp_path,
        _row(record_type="review_positive", enrichment_status="arbitrary"),
    )

    assert load_boat_hire_seeds(path) == (BoatHireSeed("provider", "base:one", 51.0, -1.0),)


def _seed(name: str, latitude: float = 51.0) -> BoatHireSeed:
    return BoatHireSeed("provider", f"base:{name}", latitude, -1.0)


def _reachable_graph() -> nx.Graph:
    graph = nx.Graph()
    for uid in range(1, 6):
        graph.add_node(uid, movable_bridge_ids=())
    dimensions = WayDimensions()
    graph.add_edge(
        1,
        2,
        length_m=100.0,
        locks=0,
        dimensions=dimensions,
        movable_bridge_ids=(),
    )
    graph.add_edge(
        2,
        3,
        length_m=100.0,
        locks=1,
        dimensions=dimensions,
        movable_bridge_ids=(),
    )
    graph.add_edge(
        2,
        4,
        length_m=100.0,
        locks=0,
        dimensions=WayDimensions(max_beam_m=2.0),
        movable_bridge_ids=(),
    )
    graph.add_edge(
        4,
        5,
        length_m=100.0,
        locks=0,
        dimensions=dimensions,
        movable_bridge_ids=(),
    )
    return graph


class _ReachabilityKwargs(TypedDict):
    cutoff_min: float
    movable_bridge_delay_min: float
    boat_length_m: float | None
    boat_beam_m: float | None
    boat_draft_m: float | None
    boat_height_m: float | None


class _ReachabilityOverrides(TypedDict, total=False):
    cutoff_min: float
    movable_bridge_delay_min: float
    boat_length_m: float | None
    boat_beam_m: float | None
    boat_draft_m: float | None
    boat_height_m: float | None


def _reachability_kwargs(**changes: Unpack[_ReachabilityOverrides]) -> _ReachabilityKwargs:
    kwargs: _ReachabilityKwargs = {
        "cutoff_min": 25.0,
        "boat_length_m": None,
        "boat_beam_m": 2.5,
        "boat_draft_m": None,
        "boat_height_m": None,
        "movable_bridge_delay_min": 5.0,
    }
    kwargs.update(changes)
    return kwargs


def test_loader_retains_display_fields_and_fallbacks(tmp_path: Path):
    seeds = load_boat_hire_seeds(
        _csv(tmp_path, _row(source_provider_name="Provider", location_name="Base one"))
    )

    assert seeds[0].source_provider_name == "Provider"
    assert seeds[0].location_name == "Base one"
    assert seeds[0].operator == "Provider"
    assert seeds[0].name == "Base one"
    fallback = BoatHireSeed("provider", "base:one", 51.0, -1.0)
    assert fallback.operator == "provider"
    assert fallback.name == "base:one"


def test_snap_boat_hire_bases_retains_anchor_and_display_fallbacks():
    seeds = (_seed("one"),)
    anchors = snap_boat_hire_bases(_Projector((1, 2), 250.0), seeds)

    assert anchors[0].edge == (1, 2)
    assert anchors[0].seed.operator == "provider"
    assert anchors[0].seed.name == "base:one"


def test_reachability_uses_minimum_cost_from_any_anchor_and_excludes_ineligible_edges():
    graph = _reachable_graph()
    anchors = (
        BoatHireAnchor(_seed("one", 51.0), (1, 2)),
        BoatHireAnchor(_seed("two", 52.0), (5, 4)),
    )

    overlay = select_boat_hire_reachability(graph, anchors, **_reachability_kwargs())

    assert set(overlay.edges) == {(1, 2), (2, 3), (4, 5)}
    assert (2, 4) not in overlay.edges


def test_reachability_includes_edges_at_the_exact_cutoff_and_hides_partial_edges():
    graph = nx.Graph()
    graph.add_nodes_from((1, 2, 3, 4))
    for uid in graph:
        graph.nodes[uid]["movable_bridge_ids"] = ()
    graph.add_edge(
        1,
        2,
        length_m=0.0,
        locks=0,
        dimensions=WayDimensions(),
        movable_bridge_ids=(),
    )
    graph.add_edge(
        2,
        3,
        length_m=2_000.0,
        locks=0,
        dimensions=WayDimensions(),
        movable_bridge_ids=(),
    )
    graph.add_edge(
        2,
        4,
        length_m=3_000.0,
        locks=0,
        dimensions=WayDimensions(),
        movable_bridge_ids=(),
    )

    overlay = select_boat_hire_reachability(
        graph,
        (BoatHireAnchor(_seed("one"), (1, 2)),),
        **_reachability_kwargs(cutoff_min=25.0, boat_beam_m=None),
    )

    assert set(overlay.edges) == {(1, 2), (2, 3)}
    assert (2, 4) not in overlay.edges


def test_reachability_bridge_delay_changes_reached_edges():
    graph = nx.Graph()
    graph.add_nodes_from((1, 2, 3))
    graph.nodes[1]["movable_bridge_ids"] = ()
    graph.nodes[2]["movable_bridge_ids"] = ()
    graph.nodes[3]["movable_bridge_ids"] = ("node:3",)
    graph.add_edge(
        1,
        2,
        length_m=0.0,
        locks=0,
        dimensions=WayDimensions(),
        movable_bridge_ids=(),
    )
    graph.add_edge(
        2,
        3,
        length_m=0.0,
        locks=0,
        dimensions=WayDimensions(),
        movable_bridge_ids=(),
    )
    anchor = (BoatHireAnchor(_seed("one"), (1, 2)),)

    delayed = select_boat_hire_reachability(
        graph, anchor, **_reachability_kwargs(cutoff_min=4.9, boat_beam_m=None)
    )
    free = select_boat_hire_reachability(
        graph,
        anchor,
        **_reachability_kwargs(cutoff_min=4.9, boat_beam_m=None, movable_bridge_delay_min=0.0),
    )

    assert set(delayed.edges) == {(1, 2)}
    assert set(free.edges) == {(1, 2), (2, 3)}


def test_reachability_with_no_eligible_source_returns_an_edgeless_view():
    graph = _reachable_graph()
    anchors = (BoatHireAnchor(_seed("one"), (2, 4)),)

    overlay = select_boat_hire_reachability(graph, anchors, **_reachability_kwargs())

    assert set(overlay.nodes) == set()
    assert set(overlay.edges) == set()


def test_reachability_does_not_mutate_the_full_graph():
    graph = _reachable_graph()
    before_nodes = dict(graph.nodes(data=True))
    before_edges = {(u, v): data.copy() for u, v, data in graph.edges(data=True)}
    anchors = (BoatHireAnchor(_seed("one"), (1, 2)),)

    select_boat_hire_reachability(graph, anchors, **_reachability_kwargs())

    assert dict(graph.nodes(data=True)) == before_nodes
    assert {(u, v): data for u, v, data in graph.edges(data=True)} == before_edges


def test_snap_pins_base_62_as_the_only_distance_exception():
    assert boat_hire.BOAT_HIRE_OVERLAY_DISTANCE_EXCEPTIONS_M == {
        "canal-holidays/base:62": 251.0,
    }


def test_snap_accepts_base_62_at_its_explicit_251m_limit():
    anchors = snap_boat_hire_bases(
        _Projector((1, 2), 251.0),
        (BoatHireSeed("canal-holidays", "base:62", 51.0, -1.0),),
    )

    assert anchors[0].edge == (1, 2)


def test_snap_rejects_a_distance_just_over_the_inclusive_limit():
    with pytest.raises(ValueError, match="base:one"):
        snap_boat_hire_bases(
            _Projector((1, 2), math.nextafter(250.0, math.inf)),
            (BoatHireSeed("provider", "base:one", 51.0, -1.0),),
        )


def test_snap_rejects_base_62_just_over_its_explicit_limit():
    with pytest.raises(ValueError, match=r"base:62 is farther than 251 m"):
        snap_boat_hire_bases(
            _Projector((1, 2), math.nextafter(251.0, math.inf)),
            (BoatHireSeed("canal-holidays", "base:62", 51.0, -1.0),),
        )


def test_snap_rejects_canal_holidays_sibling_just_over_default_limit():
    with pytest.raises(ValueError, match=r"base:61 is farther than 250 m"):
        snap_boat_hire_bases(
            _Projector((1, 2), math.nextafter(250.0, math.inf)),
            (BoatHireSeed("canal-holidays", "base:61", 51.0, -1.0),),
        )
