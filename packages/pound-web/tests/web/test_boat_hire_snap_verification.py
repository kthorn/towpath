import json
from pathlib import Path

import networkx as nx
import pytest  # pyright: ignore[reportMissingImports]
from pound.models import WayDimensions  # pyright: ignore[reportMissingImports]

from scripts.verify_boat_hire_snaps import (  # pyright: ignore[reportMissingImports]
    main,
    verify_boat_hire_snaps,
)

from .conftest import artifact_metadata, write_boat_hire_enrichment
from .fixtures import write_runtime_artifact


def _graph(
    edge: tuple[int, int], *, west: float = -1.01, candidate_eligible: bool = True
) -> nx.Graph:
    low, high = edge
    graph = nx.Graph()
    graph.add_node(low, lat=51.0, lon=west + 0.01, movable_bridge_ids=())
    graph.add_node(high, lat=51.0, lon=west, movable_bridge_ids=())
    graph.add_edge(
        low,
        high,
        length_m=1_000.0,
        locks=0,
        dimensions=WayDimensions(),
        movable_bridge_ids=(),
        geometry=[(51.0, west + 0.01), (51.0, west)],
        candidate_eligible=candidate_eligible,
    )
    return graph


def _seeds() -> tuple:
    from pound_web.boat_hire import BoatHireSeed

    return (
        BoatHireSeed("canal-holidays", "base:62", 51.0, -1.005),
        BoatHireSeed("provider", "base:one", 51.0, -1.005),
    )


def _artifacts(
    tmp_path: Path,
    *,
    old_west: float = -1.01,
    new_west: float = -1.01,
    old_candidate_eligible: bool = True,
) -> tuple[Path, Path]:
    old_path = write_runtime_artifact(
        _graph((1, 2), west=old_west, candidate_eligible=old_candidate_eligible),
        [],
        tmp_path / "old.pkl",
        artifact_metadata("old"),
    )
    new_path = write_runtime_artifact(
        _graph((3, 4), west=new_west), [], tmp_path / "new.pkl", artifact_metadata("new")
    )
    return old_path, new_path


def test_verification_reports_sorted_old_and_new_projection_for_every_base(tmp_path: Path):
    old_path, new_path = _artifacts(tmp_path)

    report = verify_boat_hire_snaps(old_path, new_path, _seeds())

    assert [entry["identity"] for entry in report["bases"]] == [
        "canal-holidays/base:62",
        "provider/base:one",
    ]
    assert all(entry["old_edge"] == [1, 2] for entry in report["bases"])
    assert all(entry["new_edge"] == [3, 4] for entry in report["bases"])
    assert all(entry["old_snap_distance_m"] < 1.0 for entry in report["bases"])
    assert all(entry["new_snap_distance_m"] < 1.0 for entry in report["bases"])
    assert report["threshold_breaches"] == []
    assert report["required_exception_changes"] == []


def test_verification_uses_legacy_edge_projection_for_old_artifact(tmp_path: Path):
    old_path, new_path = _artifacts(tmp_path, old_candidate_eligible=False)

    report = verify_boat_hire_snaps(old_path, new_path, _seeds())

    assert all(entry["old_snap_distance_m"] < 1.0 for entry in report["bases"])
    assert report["old_threshold_breaches"] == []


def test_verification_command_reports_old_threshold_breaches_even_when_new_is_valid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    old_path, new_path = _artifacts(tmp_path, old_west=-1.03)
    report = verify_boat_hire_snaps(old_path, new_path, _seeds())

    assert report["threshold_breaches"] == []
    assert report["old_threshold_breaches"] == [
        "canal-holidays/base:62",
        "provider/base:one",
    ]
    assert report["required_exception_changes"] == []

    seed_path = write_boat_hire_enrichment(
        tmp_path / "boat-hire.csv",
        rows=[
            {
                "source_provider_id": "canal-holidays",
                "location_id": "base:62",
                "latitude": "51.0",
                "longitude": "-1.005",
            },
            {
                "source_provider_id": "provider",
                "location_id": "base:one",
                "latitude": "51.0",
                "longitude": "-1.005",
            },
        ],
    )
    result = main(
        [
            "--before",
            str(old_path),
            "--after",
            str(new_path),
            "--boat-hire-enrichment",
            str(seed_path),
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert result == 1
    assert output["old_threshold_breaches"] == [
        "canal-holidays/base:62",
        "provider/base:one",
    ]


def test_verification_command_reports_base_62_and_fails_new_threshold_breaches(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    old_path, new_path = _artifacts(tmp_path, new_west=-1.03)
    seed_path = write_boat_hire_enrichment(
        tmp_path / "boat-hire.csv",
        rows=[
            {
                "source_provider_id": "canal-holidays",
                "location_id": "base:62",
                "latitude": "51.0",
                "longitude": "-1.005",
            },
            {
                "source_provider_id": "provider",
                "location_id": "base:one",
                "latitude": "51.0",
                "longitude": "-1.005",
            },
        ],
    )

    result = main(
        [
            "--before",
            str(old_path),
            "--after",
            str(new_path),
            "--boat-hire-enrichment",
            str(seed_path),
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert result == 1
    assert {entry["identity"] for entry in output["bases"]} == {
        "canal-holidays/base:62",
        "provider/base:one",
    }
    assert set(output["threshold_breaches"]) == {
        "canal-holidays/base:62",
        "provider/base:one",
    }
    assert set(output["required_exception_changes"]) == {
        "canal-holidays/base:62",
        "provider/base:one",
    }
