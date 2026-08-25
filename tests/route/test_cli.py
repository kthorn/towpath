import json
from pathlib import Path
from unittest.mock import patch

import pytest

from pound.graph.artifact import save_artifact
from pound.graph.build import build_graph
from pound.graph.gazetteer import attach_node_names, build_gazetteer
from pound.graph.locks import attach_locks
from pound.ingest.overpass import parse
from pound.route import cli
from tests.fixtures import oxford_fixture_path


def _metadata(feats) -> dict:
    return {
        "artifact_revision": "route-cli-test",
        "source": feats.source,
        "fetched_at": feats.fetched_at,
        "built_at": "t",
        "validation": {},
        "poi_summary": {},
    }


def _build_oxford_artifact(out: Path) -> Path:
    raw = json.loads(Path(oxford_fixture_path()).read_text())
    feats = parse(raw["elements"], None, osm_timestamp=raw["osm3s"]["timestamp_osm_base"])
    g, _ = attach_locks(build_graph(feats), feats)
    attach_node_names(g, feats)
    g.graph["gazetteer"] = build_gazetteer(feats)
    g.graph["fetched_at"] = feats.fetched_at
    save_artifact(
        g,
        [],
        out,
        _metadata(feats),
    )
    return out


def test_pound_plan_prints_human_readable_route(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = cli.main(["Oxford", "Hayfield", "--days", "1", "--artifact", str(art)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Oxford" in out
    assert "Hayfield" in out
    # default output: route header + Totals + Days, NO node-to-node Legs: list
    assert "Totals:" in out
    assert "Days:" in out
    assert "Legs:" not in out  # node-to-node list is --verbose only


def test_pound_plan_rejects_days_zero(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = cli.main(["Oxford", "Hayfield", "--days", "0", "--artifact", str(art)])
    assert rc != 0
    # pydantic validation surfaces a clear message, not a traceback
    assert "days" in capsys.readouterr().err.lower()


def test_pound_plan_unknown_place_clear_error(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = cli.main(["Narnia", "Hayfield", "--days", "1", "--artifact", str(art)])
    assert rc != 0
    err = capsys.readouterr().err
    assert "not found in gazetteer" in err


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
    err = capsys.readouterr().err
    assert "no path" in err.lower()


def test_pound_plan_accepts_uid_start_and_end(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    from pound.graph.artifact import load_artifact
    from pound.route.resolve import resolve_place

    graph = load_artifact(Path(art)).graph
    o_uid = resolve_place("Oxford", graph)
    h_uid = resolve_place("Hayfield", graph)
    rc = cli.main([str(o_uid), str(h_uid), "--days", "1", "--artifact", str(art)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Oxford" in out
    assert "Hayfield" in out


def test_pound_plan_forwards_zero_movable_bridge_delay_for_uid_route(tmp_path):
    artifact = _build_oxford_artifact(tmp_path / "oxford.pkl")
    from pound.graph.artifact import load_artifact
    from pound.route.resolve import resolve_place

    graph = load_artifact(artifact).graph
    start_uid = resolve_place("Oxford", graph)
    end_uid = resolve_place("Hayfield", graph)
    with patch("pound.route.cli.plan_route", wraps=cli.plan_route) as planner:
        assert (
            cli.main(
                [
                    str(start_uid),
                    str(end_uid),
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
            cli.main(["1", "2", "--movable-bridge-delay-min", "inf", "--artifact", "missing.pkl"])

    assert excinfo.value.code == 2
    assert "must be a finite non-negative number" in capsys.readouterr().err
    loader.assert_not_called()


def test_pound_plan_mixes_uid_start_and_name_end(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    from pound.graph.artifact import load_artifact
    from pound.route.resolve import resolve_place

    graph = load_artifact(Path(art)).graph
    o_uid = resolve_place("Oxford", graph)
    rc = cli.main([str(o_uid), "Hayfield", "--days", "1", "--artifact", str(art)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Oxford" in out
    assert "Hayfield" in out


def test_pound_plan_unknown_uid_clear_error_not_traceback(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    # A uid that is not a graph node -> plan_route raises ValueError; CLI catches it.
    rc = cli.main(["999999", "0", "--days", "1", "--artifact", str(art)])
    assert rc != 0
    assert capsys.readouterr().err  # non-empty, not a traceback


def test_pound_plan_days_optional_infers_day_count(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    # Omit --days entirely; hours_per_day alone drives day-count inference.
    rc = cli.main(["Oxford", "Hayfield", "--hours-per-day", "6", "--artifact", str(art)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Days:" in out  # reports the inferred day count + per-day summary


def test_pound_plan_default_hides_leg_list(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = cli.main(["Oxford", "Hayfield", "--days", "1", "--artifact", str(art)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Totals:" in out
    assert "Legs:" not in out  # node-to-node leg list is verbose-only


def test_pound_plan_verbose_shows_leg_list(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = cli.main(["Oxford", "Hayfield", "--days", "1", "--verbose", "--artifact", str(art)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Legs:" in out  # verbose => per-leg node-to-node list present


def test_pound_plan_locks_flag_shows_per_day_lock_count(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = cli.main(["Oxford", "Hayfield", "--days", "1", "--locks", "--artifact", str(art)])
    assert rc == 0
    out = capsys.readouterr().out
    # The per-day line gains a locks count; Oxford->Hayfield has exactly 1 lock.
    assert "locks" in out.lower()
    day_line = [ln for ln in out.splitlines() if ln.strip().startswith("Day 1")][0]
    assert "1 locks" in day_line


def test_pound_plan_no_locks_flag_omits_per_day_lock_count(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = cli.main(["Oxford", "Hayfield", "--days", "1", "--artifact", str(art)])
    assert rc == 0
    out = capsys.readouterr().out
    day_line = [ln for ln in out.splitlines() if ln.strip().startswith("Day 1")][0]
    assert "locks" not in day_line.lower()  # default per-day line has no lock count
