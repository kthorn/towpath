import csv
import math
from pathlib import Path

import networkx as nx
import pytest
from shapely.geometry import Point

from pound.web.boat_hire import (
    BOAT_HIRE_ENRICHMENT_FIELDS,
    BoatHireSeed,
    load_boat_hire_seeds,
    select_boat_hire_overlay,
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


def test_loader_selects_review_positive_row_regardless_of_provenance(tmp_path: Path):
    path = _csv(
        tmp_path,
        _row(record_type="review_positive", enrichment_status="arbitrary"),
    )

    assert load_boat_hire_seeds(path) == (BoatHireSeed("provider", "base:one", 51.0, -1.0),)


def test_selector_keeps_only_the_seed_component_and_accepts_250m():
    graph = nx.Graph()
    graph.add_edges_from(((1, 2), (2, 3), (4, 5)))

    selected = select_boat_hire_overlay(
        graph,
        _Projector((1, 2), 250.0),  # type: ignore[arg-type] — deliberate duck-typed fixture
        (BoatHireSeed("provider", "base:one", 51.0, -1.0),),
    )

    assert set(selected.nodes) == {1, 2, 3}
    assert set(selected.edges) == {(1, 2), (2, 3)}
    assert set(graph.nodes) == {1, 2, 3, 4, 5}


def test_selector_rejects_a_distance_just_over_the_inclusive_limit():
    graph = nx.Graph([(1, 2)])
    with pytest.raises(ValueError, match="base:one"):
        select_boat_hire_overlay(
            graph,
            _Projector((1, 2), math.nextafter(250.0, math.inf)),  # type: ignore[arg-type] — deliberate duck-typed fixture
            (BoatHireSeed("provider", "base:one", 51.0, -1.0),),
        )
