import json
from pathlib import Path

from pound.graph.artifact import save_artifact
from pound.graph.build import build_graph
from pound.graph.gazetteer import attach_node_names, build_gazetteer
from pound.graph.locks import attach_locks
from pound.ingest.overpass import parse
from pound.route import cli
from tests.fixtures import oxford_fixture_path


def _build_oxford_artifact(out: Path) -> Path:
    raw = json.loads(Path(oxford_fixture_path()).read_text())
    feats = parse(raw["elements"], None, osm_timestamp=raw["osm3s"]["timestamp_osm_base"])
    g, _ = attach_locks(build_graph(feats), feats)
    attach_node_names(g, feats)
    g.graph["gazetteer"] = build_gazetteer(feats)
    g.graph["fetched_at"] = feats.fetched_at
    save_artifact(
        g,
        out,
        {
            "source": feats.source,
            "fetched_at": feats.fetched_at,
            "built_at": "t",
            "version": "1",
        },
    )
    return out


def test_pound_plan_prints_human_readable_route(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    rc = cli.main(["Oxford", "Hayfield", "--days", "1", "--artifact", str(art)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Oxford" in out
    assert "Hayfield" in out
    # per-leg list + totals + days + warnings sections present
    assert "legs" in out.lower() or "Leg" in out
    assert "total" in out.lower()


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

    graph, _ = load_artifact(Path(art))
    o_uid = resolve_place("Oxford", graph)
    h_uid = resolve_place("Hayfield", graph)
    rc = cli.main([str(o_uid), str(h_uid), "--days", "1", "--artifact", str(art)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Oxford" in out
    assert "Hayfield" in out


def test_pound_plan_mixes_uid_start_and_name_end(tmp_path, capsys):
    art = _build_oxford_artifact(tmp_path / "oxford.pkl")
    from pound.graph.artifact import load_artifact
    from pound.route.resolve import resolve_place

    graph, _ = load_artifact(Path(art))
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
