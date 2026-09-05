"""Climate endpoints are optional, bounded artifact reads."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from pound_web.app import create_app


def climate_payload():
    def distribution(period):
        return {
            "available": True,
            "missing_years": [],
            "start_year": 2026 - period,
            "end_year": 2025,
            "n_days": period * 7,
            "n_years": period,
            "p10": 12.0,
            "median": 12.0,
            "p90": 12.0,
            "samples": [12.0] * (period * 7),
        }

    return {
        "revision": "climate-test",
        "end_year": 2025,
        "source": {
            "name": "Test data",
            "url": "https://example.org",
            "attribution": "Synthetic",
            "timezone": "Europe/London",
            "model": "era5_land",
        },
        "locations": [
            {
                "id": "oxford",
                "name": "Oxford",
                "coordinate": {"lat": 51.75, "lon": -1.25},
                "source_coordinate": {"lat": 51.75, "lon": -1.25},
                "elevation": 60,
                "weeks": [
                    {
                        "week_id": i,
                        "label": "June 26–July 2",
                        "high": {str(p): distribution(p) for p in (25, 5)},
                        "low": {str(p): distribution(p) for p in (25, 5)},
                    }
                    for i in range(18)
                ],
            }
        ],
    }


def test_climate_absent_preserves_routing(web_client):
    response = web_client.get("/api/climate/locations")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "climate_unavailable"
    assert (
        web_client.post("/api/canal-network", json={"days": 7, "hours_per_day": 6}).status_code
        == 200
    )


def test_climate_summary_omits_samples_and_supports_etags(web_client, monkeypatch):
    web_client.app.state.climate = climate_payload()
    monkeypatch.setattr("requests.get", lambda *a, **k: pytest.fail("runtime network call"))
    response = web_client.get("/api/climate/locations?week_id=8&period_years=5&metric=low")
    assert response.status_code == 200
    body = response.json()
    assert body["period_years"] == 5 and body["metric"] == "low"
    assert body["locations"][0]["distribution"]["n_days"] == 35
    assert "samples" not in body["locations"][0]["distribution"]
    assert "weeks" not in body["locations"][0]
    cached = web_client.get(
        "/api/climate/locations?week_id=8&period_years=5&metric=low",
        headers={"If-None-Match": response.headers["etag"]},
    )
    assert cached.status_code == 304
    different = web_client.get(
        "/api/climate/locations?week_id=9&period_years=5&metric=low",
        headers={"If-None-Match": response.headers["etag"]},
    )
    assert different.status_code == 200


def test_climate_detail_returns_both_periods(web_client):
    web_client.app.state.climate = climate_payload()
    response = web_client.get("/api/climate/locations/oxford?week_id=8")
    assert response.status_code == 200
    body = response.json()
    assert body["location"]["id"] == "oxford"
    assert len(body["high"]["25"]["samples"]) == 175
    assert len(body["low"]["5"]["samples"]) == 35
    assert web_client.get("/api/climate/locations/missing").status_code == 404


@pytest.mark.parametrize("query", ["week_id=-1", "week_id=18", "period_years=10", "metric=mean"])
def test_climate_invalid_query(web_client, query):
    web_client.app.state.climate = climate_payload()
    assert web_client.get("/api/climate/locations?" + query).status_code == 422


def test_invalid_climate_artifact_does_not_block_app(web_client, tmp_path):
    path = tmp_path / "climate.json"
    path.write_text("{bad data")
    settings = replace(web_client.app.state.settings, climate_path=path)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/climate/locations")
        assert response.status_code == 503
        assert str(path) not in response.text
        assert client.get("/api/health").status_code == 200


def test_valid_climate_loaded_once_and_runtime_never_reads_cache(web_client, tmp_path, monkeypatch):
    from pound.climate.artifact import write_climate
    from pound_build.ingest.climate import build_climate

    location = {"id": "oxford", "name": "Oxford", "coordinate": {"lat": 51.75, "lon": -1.25}}
    history = {
        year: {
            "latitude": 51.75,
            "longitude": -1.25,
            "elevation": 60.0,
            "timezone": "Europe/London",
            "daily_units": {"temperature_2m_max": "°C", "temperature_2m_min": "°C"},
            "daily": {
                "time": [f"{year}-05-{day:02d}" for day in range(1, 8)],
                "temperature_2m_max": [20.0] * 7,
                "temperature_2m_min": [10.0] * 7,
            },
        }
        for year in range(2001, 2026)
    }
    artifact = build_climate([location], 2025, {"oxford": history})
    path = tmp_path / "climate.json"
    write_climate(artifact, path)
    settings = replace(web_client.app.state.settings, climate_path=path)
    with TestClient(create_app(settings)) as client:
        path.unlink()
        monkeypatch.setattr(
            "requests.sessions.Session.request", lambda *a, **k: pytest.fail("runtime network")
        )
        summary = client.get("/api/climate/locations?week_id=0")
        assert summary.status_code == 200
        assert summary.json()["locations"][0]["distribution"]["median"] == 20
        detail = client.get("/api/climate/locations/oxford?week_id=0")
        assert detail.json()["high"]["5"]["n_days"] == 35
        assert detail.json()["revision"] == artifact.revision
        cached = client.get(
            "/api/climate/locations/oxford?week_id=0",
            headers={"If-None-Match": detail.headers["etag"]},
        )
        assert cached.status_code == 304
        assert (
            client.get(
                "/api/climate/locations/oxford?week_id=1",
                headers={"If-None-Match": detail.headers["etag"]},
            ).status_code
            == 200
        )
