from pathlib import Path
from unittest.mock import patch

import pytest  # pyright: ignore[reportMissingImports]
from pound.artifact import load_artifact
from pound.route import cli

from tests.fixtures import routing_test_graph, write_runtime_artifact


def _metadata() -> dict:
    return {
        "artifact_revision": "route-cli-test",
        "source": "fixture",
        "fetched_at": "2026-06-21T12:00:00Z",
        "built_at": "t",
        "validation": {},
        "poi_summary": {},
    }


def _build_oxford_artifact(out: Path) -> Path:
    graph, gazetteer = routing_test_graph()
    graph.graph.pop("gazetteer", None)
    return write_runtime_artifact(graph, (), out, _metadata(), gazetteer=gazetteer)


def test_pound_plan_prints_human_readable_route(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = cli.main(["Oxford", "Hayfield", "--days", "1", "--artifact", str(art)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Oxford" in out
    assert "Hayfield" in out
    assert "Totals:" in out
    assert "Days:" in out
    assert "Legs:" not in out


def test_pound_plan_matches_place_names_case_insensitively(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = cli.main(["oXfOrD", "hAyFiElD", "--days", "1", "--artifact", str(art)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Oxford" in out
    assert "Hayfield" in out


def test_pound_plan_rejects_days_zero(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = cli.main(["Oxford", "Hayfield", "--days", "0", "--artifact", str(art)])
    assert rc != 0
    assert "days" in capsys.readouterr().err.lower()


def test_pound_plan_unknown_place_clear_error(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = cli.main(["Narnia", "Hayfield", "--days", "1", "--artifact", str(art)])
    assert rc != 0
    assert "not found in gazetteer" in capsys.readouterr().err


def test_pound_plan_no_path_clear_error(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = cli.main(
        [
            "Oxford",
            "Hayfield",
            "--days",
            "1",
            "--boat-beam",
            "99",
            "--boat-draft",
            "99",
            "--artifact",
            str(art),
        ]
    )
    assert rc != 0
    assert "no path" in capsys.readouterr().err.lower()


def test_pound_plan_forwards_zero_movable_bridge_delay(tmp_path):
    artifact = _build_oxford_artifact(tmp_path / "oxford.pkl")
    with patch("pound.route.cli.plan_projected_route", wraps=cli.plan_projected_route) as planner:
        assert (
            cli.main(
                [
                    "Oxford",
                    "Hayfield",
                    "--movable-bridge-delay-min",
                    "0",
                    "--artifact",
                    str(artifact),
                ]
            )
            == 0
        )
    assert planner.call_args.args[0].movable_bridge_delay_min == 0.0


def test_pound_plan_rejects_nonfinite_movable_bridge_delay_before_loading_artifact(capsys):
    with patch("pound.route.cli.load_artifact") as loader:
        with pytest.raises(SystemExit) as excinfo:
            cli.main(
                [
                    "Oxford",
                    "Hayfield",
                    "--movable-bridge-delay-min",
                    "inf",
                    "--artifact",
                    "missing.pkl",
                ]
            )

    assert excinfo.value.code == 2
    assert "must be a finite non-negative number" in capsys.readouterr().err
    loader.assert_not_called()


def test_pound_plan_days_optional_infers_day_count(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = cli.main(["Oxford", "Hayfield", "--hours-per-day", "6", "--artifact", str(art)])
    assert rc == 0
    assert "Days:" in capsys.readouterr().out


def test_pound_plan_verbose_shows_leg_list(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = cli.main(["Oxford", "Hayfield", "--days", "1", "--verbose", "--artifact", str(art)])
    assert rc == 0
    assert "Legs:" in capsys.readouterr().out


def test_pound_plan_locks_flag_shows_per_day_lock_count(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = cli.main(["Oxford", "Hayfield", "--days", "1", "--locks", "--artifact", str(art)])
    assert rc == 0
    out = capsys.readouterr().out
    day_line = [ln for ln in out.splitlines() if ln.strip().startswith("Day 1")][0]
    assert "1 locks" in day_line


def test_pound_plan_no_locks_flag_omits_per_day_lock_count(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = cli.main(["Oxford", "Hayfield", "--days", "1", "--artifact", str(art)])
    assert rc == 0
    day_line = [
        ln for ln in capsys.readouterr().out.splitlines() if ln.strip().startswith("Day 1")
    ][0]
    assert "locks" not in day_line.lower()


def test_pound_plan_builds_constraints_from_loaded_artifact(tmp_path):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    loaded = load_artifact(art)
    assert loaded.gazetteer
