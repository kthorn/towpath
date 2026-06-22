import json

from pound.ingest import cli
from pound.ingest.ir import (
    NodeKind,
    WaterwayFeatures,
    WaterwayKind,
    WaterwayNode,
    WaterwayWay,
    WayDimensions,
)


def _sample_features() -> WaterwayFeatures:
    return WaterwayFeatures(
        ways=[
            WaterwayWay(
                osm_id=1,
                kind=WaterwayKind.CANAL,
                name="Oxford Canal",
                tags={"waterway": "canal"},
                node_ids=[],
                geometry=[(51.75, -1.26)],
                dimensions=WayDimensions(max_beam_m=2.1),
            )
        ],
        nodes=[
            WaterwayNode(
                osm_id=10,
                lat=51.75,
                lon=-1.26,
                tags={"waterway": "lock_gate"},
                kind=NodeKind.LOCK_GATE,
            )
        ],
        source="overpass",
        fetched_at="2026-06-21T12:00:00+00:00",
        bbox=(51.70, -1.35, 51.80, -1.20),
    )


def test_cli_prints_report_and_writes_out(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_oxford", lambda: _sample_features())
    out_path = tmp_path / "oxford.json"
    cli.main(["oxford", "--out", str(out_path)])

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["way_count"] == 1
    assert report["ways_by_kind"] == {"canal": 1}

    written = WaterwayFeatures.model_validate_json(out_path.read_text())
    assert written.source == "overpass"
    assert len(written.ways) == 1


def test_cli_rejects_unknown_region(monkeypatch):
    monkeypatch.setattr(cli, "fetch_oxford", lambda: _sample_features())
    try:
        cli.main(["bogus"])
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("expected SystemExit for unknown region")
