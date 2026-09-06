"""Optional grid endpoints do not interfere with route planning."""

from types import SimpleNamespace

import pytest


def test_missing_grid_is_optional(web_client):
    r = web_client.get("/api/climate/grid")
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "climate_grid_unavailable"
    assert web_client.get("/api/health").status_code == 200


def test_grid_query_and_etag(web_client):
    calls = []

    def surface(week, period, view, threshold):
        calls.append((week, period, view, threshold))
        return dict(revision="grid-r1", cells=[], view=view, threshold_c=threshold)

    web_client.app.state.climate_grid = SimpleNamespace(surface=surface)
    url = "/api/climate/grid?week_id=8&period_years=5&view=high_exceedance&threshold_c=30"
    r = web_client.get(url)
    assert r.status_code == 200
    assert calls == [(8, 5, "high_exceedance", 30)]
    assert web_client.get(url, headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    r2 = web_client.get(url.replace("=30", "=31"), headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 200 and r2.headers["etag"] != r.headers["etag"]


@pytest.mark.parametrize(
    "query", ["week_id=18", "period_years=10", "view=low_p90", "threshold_c=nan", "threshold_c=51"]
)
def test_grid_rejects_invalid_queries(web_client, query):
    assert web_client.get("/api/climate/grid?" + query).status_code == 422


def test_grid_missing_cell(web_client):
    web_client.app.state.climate_grid = SimpleNamespace(detail=lambda cell, week: None)
    assert web_client.get("/api/climate/grid/cells/unknown").status_code == 404


def test_nearby_thresholds_have_distinct_etags(web_client):
    web_client.app.state.climate_grid = SimpleNamespace(
        surface=lambda week, period, view, threshold: dict(revision="same", value=threshold)
    )
    url = "/api/climate/grid?view=high_exceedance&threshold_c="
    first = web_client.get(url + "29.999999")
    second = web_client.get(url + "30", headers={"If-None-Match": first.headers["etag"]})
    assert second.status_code == 200


def test_invalid_grid_startup_preserves_routing(web_client,tmp_path):
    from dataclasses import replace

    from fastapi.testclient import TestClient
    from pound_web.app import create_app

    path=tmp_path/'broken.sqlite'
    path.write_text('not a SQLite artifact')
    settings=replace(web_client.app.state.settings,climate_grid_path=path)
    with TestClient(create_app(settings)) as client:
        response=client.get('/api/climate/grid')
        assert response.status_code == 503
        assert str(path) not in response.text
        assert client.get('/api/health').status_code == 200
