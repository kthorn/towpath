import hashlib
import json

import numpy as np
import pytest
from pound_build.ingest.climate_cds import daily_extrema, summer_hours


def test_summer_hours_follow_london_local_midnight():
    hours = summer_hours(2025)
    assert len(hours) == 126 * 24
    assert hours[0] == np.datetime64("2025-04-30T23")
    assert hours[-1] == np.datetime64("2025-09-03T22")


def test_kelvin_conversion_extrema_and_complete_days():
    hours = summer_hours(2025)
    values = np.full((len(hours), 2), 283.15)
    values[0, 0] = 300.15
    values[23, 0] = 270.15
    values[24, 0] = 310.15
    values[10, 1] = np.nan
    high, low = daily_extrema(hours, values, 2025)
    assert high.shape == (126, 2)
    assert high[0, 0] == pytest.approx(27)
    assert low[0, 0] == pytest.approx(-3)
    assert high[1, 0] == pytest.approx(37)
    assert np.isnan(high[0, 1]) and np.isnan(low[0, 1])
    assert high[1, 1] == pytest.approx(10)


def test_missing_hour_makes_entire_day_unavailable():
    hours = summer_hours(2025)
    high, low = daily_extrema(hours[1:], np.full((len(hours) - 1, 1), 283.15), 2025)
    assert np.isnan(high[0, 0]) and np.isnan(low[0, 0])
    assert high[1, 0] == pytest.approx(10)


def test_duplicate_or_unsorted_hours_are_rejected():
    hours = summer_hours(2025)
    for invalid in (np.append(hours, hours[-1]), hours[::-1]):
        with pytest.raises(ValueError, match="strictly increasing"):
            daily_extrema(invalid, np.ones((len(invalid), 1)), 2025)


def test_chunk_cache_reuses_data_and_rejects_unsafe_keys(tmp_path):
    from pound_build.ingest.climate_cds import CdsStore

    calls = []

    def fetch(key):
        calls.append(key)
        return b"chunk"

    store = CdsStore(tmp_path, fetch=fetch)
    assert store["t2m/1.2.3"] == b"chunk"
    assert CdsStore(tmp_path, fetch=fetch)["t2m/1.2.3"] == b"chunk"
    assert calls == ["t2m/1.2.3"]
    for key in ("../secret", "/absolute", "https://evil.test/x", "t2m/../../x"):
        with pytest.raises(KeyError):
            store[key]
    assert calls == ["t2m/1.2.3"]


def test_failed_chunk_does_not_poison_cache(tmp_path):
    from pound_build.ingest.climate_cds import CdsStore

    def fail(key):
        raise RuntimeError("download failed")

    with pytest.raises(RuntimeError):
        CdsStore(tmp_path, fetch=fail)["t2m/1.2.3"]
    assert not (tmp_path / "t2m/1.2.3").exists()
    assert CdsStore(tmp_path, fetch=lambda _: b"ok")["t2m/1.2.3"] == b"ok"


def test_store_decodes_real_zarr_chunks_and_resumes_offline(tmp_path):
    zarr = pytest.importorskip("zarr")
    from pound_build.ingest.climate_cds import CdsStore

    memory = zarr.MemoryStore()
    root = zarr.group(store=memory)
    expected = np.arange(48, dtype="float32").reshape(6, 2, 4)
    root.create_dataset("t2m", data=expected, chunks=(3, 2, 2))
    zarr.consolidate_metadata(memory)
    store = CdsStore(tmp_path, fetch=memory.__getitem__)
    result = zarr.open_consolidated(store, mode="r")["t2m"][:]
    np.testing.assert_array_equal(result, expected)

    def no_network(key):
        pytest.fail("cached Zarr array must not download again")

    resumed = zarr.open_consolidated(CdsStore(tmp_path, fetch=no_network), mode="r")
    np.testing.assert_array_equal(resumed["t2m"][:], expected)


def test_masked_values_and_missing_sentinel_invalidate_days():
    hours = summer_hours(2025)
    values = np.ma.array(np.full((len(hours), 1), 283.15), mask=False)
    values.mask[0, 0] = True
    values[24, 0] = 3.4028234663852886e38
    high, low = daily_extrema(hours, values, 2025)
    assert np.isnan(high[:2]).all() and np.isnan(low[:2]).all()
    assert high[2, 0] == pytest.approx(10)


def test_source_metadata_change_rejects_cache_resume(tmp_path):
    from pound_build.ingest.climate_cds import CdsStore

    first = CdsStore(tmp_path, fetch=lambda _: b'{"version":1}')
    first.verify_snapshot()
    second = CdsStore(tmp_path, fetch=lambda _: b'{"version":2}')
    with pytest.raises(ValueError, match="metadata changed"):
        second.verify_snapshot()
    assert (tmp_path / ".zmetadata").read_bytes() == b'{"version":1}'


def test_source_cache_is_bound_to_official_url(tmp_path):
    import json

    from pound_build.ingest.climate_cds import CdsStore

    (tmp_path / "source.json").write_text(json.dumps({"url": "https://wrong.test"}))
    with pytest.raises(ValueError, match="source"):
        CdsStore(tmp_path, fetch=lambda _: b"{}").verify_snapshot()


def test_nearest_land_point_is_bounded_and_handles_western_longitudes():
    from pound_build.ingest.climate_cds import nearest_land_point

    lat = np.array([51.8, 51.7, 51.6])
    lon = np.array([358.7, 358.8, 358.9])
    valid = np.ones((3, 3), dtype=bool)
    valid[1, 1] = False
    result = nearest_land_point(51.7, -1.2, lat, lon, valid, max_distance_km=15)
    assert result is not None and result[:2] != (1, 1)
    assert result[2] < 10
    assert nearest_land_point(60, -1.2, lat, lon, valid, max_distance_km=15) is None


def test_acquire_point_writes_complete_annual_cache_for_grid_builder(tmp_path, monkeypatch):
    zarr = pytest.importorskip("zarr")
    from pound_build.ingest.climate import ClimateImporter
    from pound_build.ingest.climate_cds import acquire_cells, cache_endpoint

    fingerprint = hashlib.sha256(b"{}").hexdigest()
    store = zarr.MemoryStore()
    root = zarr.group(store=store)
    times = np.arange(
        np.datetime64("2001-04-30T23"), np.datetime64("2025-09-03T23"), np.timedelta64(1, "h")
    )
    root.create_dataset("time", data=times.astype("datetime64[h]").astype("int64"))
    root["time"].attrs["units"] = "hours since 1970-01-01"
    root.create_dataset("latitude", data=np.array([51.7]))
    root.create_dataset("longitude", data=np.array([358.8]))
    root.create_dataset(
        "t2m",
        data=(273.15 + (np.arange(len(times)) % 997) / 100).astype("float32")[:, None, None],
        chunks=(33792, 1, 1),
    )
    root["t2m"].attrs["units"] = "K"
    cell = {"id": "oxford", "name": "Oxford", "coordinate": {"lat": 51.7, "lon": -1.2}}
    reports = list(acquire_cells([cell], root, tmp_path / "annual", 2025, fingerprint))
    assert reports[-1]["completed_cells"] == 1
    importer = ClimateImporter(cache_dir=tmp_path / "annual", endpoint=cache_endpoint(fingerprint))
    cached = importer.load_cached_histories([cell], 2025)["oxford"]
    assert len(cached) == 25
    assert len(cached[2025]["daily"]["time"]) == 126
    for year in (2001, 2009, 2025):
        for day_index, day in ((0, "05-01"), (56, "06-26"), (125, "09-03")):
            first = np.datetime64(f"{year}-{day}T00") - np.timedelta64(1, "h")
            index = int(np.flatnonzero(times == first)[0])
            reference = (273.15 + (np.arange(index, index + 24) % 997) / 100).astype("float32")
            assert cached[year]["daily"]["temperature_2m_max"][day_index] == pytest.approx(
                float(reference.max()) - 273.15, abs=0.00001
            )
            assert cached[year]["daily"]["temperature_2m_min"][day_index] == pytest.approx(
                float(reference.min()) - 273.15, abs=0.00001
            )
    assert cached[2025]["longitude"] == pytest.approx(-1.2)
    assert cached[2025]["elevation"] is None

    from pound.climate.grid import ClimateGrid
    from pound_build.ingest.climate_cds import CDS_ZARR_URL, CdsStore

    from scripts.build_climate_cds import main

    chunks = tmp_path / "chunks"
    chunks.mkdir()
    (chunks / ".zmetadata").write_bytes(b"{}")
    (chunks / "source.json").write_text(
        json.dumps(
            {
                "url": CDS_ZARR_URL,
                "metadata_sha256": fingerprint,
            }
        )
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([cell]))
    mask = tmp_path / "mask.json"
    mask.write_text(
        json.dumps(
            {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-1.5, 51.5],
                        [-1, 51.5],
                        [-1, 52],
                        [-1.5, 52],
                        [-1.5, 51.5],
                    ]
                ],
            }
        )
    )
    monkeypatch.setattr(CdsStore, "_download", lambda *_: pytest.fail("build must be offline"))
    output = tmp_path / "grid.sqlite"
    assert (
        main(
            [
                "build",
                "--manifest",
                str(manifest),
                "--cache-dir",
                str(tmp_path),
                "--mask",
                str(mask),
                "--out",
                str(output),
            ]
        )
        == 0
    )
    surface = ClimateGrid(output).surface(8, 25, "high_p90")
    assert surface["source"]["name"] == "Copernicus ERA5-Land"
    assert surface["cells"][0]["n_days"] == 175

    # Second run uses validated annual caches, without reading the large temperature array.
    class NoTemperatureRead:
        def __getitem__(self, key):
            if key == "t2m":
                pytest.fail("complete annual cache must resume without reading temperature")
            return root[key]

    assert (
        list(acquire_cells([cell], NoTemperatureRead(), tmp_path / "annual", 2025, fingerprint))[
            -1
        ]["completed_cells"]
        == 1
    )


def test_missing_ocean_chunks_are_cached_as_missing(tmp_path):
    from pound_build.ingest.climate_cds import CdsStore

    calls = []

    def absent(key):
        calls.append(key)
        raise KeyError(key)

    store = CdsStore(tmp_path, fetch=absent)
    for _ in range(2):
        with pytest.raises(KeyError):
            store["t2m/1.2.3"]
    assert calls == ["t2m/1.2.3"]


def test_daily_conversion_does_not_modify_input():
    values = np.full((len(summer_hours(2025)), 1), 283.15)
    values[0] = 1e30
    before = values.copy()
    daily_extrema(summer_hours(2025), values, 2025)
    np.testing.assert_array_equal(values, before)


def test_transient_provider_licence_error_retries_but_never_becomes_missing(tmp_path, monkeypatch):
    import requests
    from pound_build.ingest.climate_cds import CdsStore

    monkeypatch.setenv("CDSAPI_KEY", "test-token")

    class Session:
        headers = {}

        def get(self, *args, **kwargs):
            response = requests.Response()
            response.status_code = statuses.pop(0)
            response._content = (
                b"chunk"
                if response.status_code == 200
                else b'{"_errorCode":"LICENSES_NOT_ACCEPTED"}'
            )
            return response

        def close(self):
            pass

    monkeypatch.setattr(requests, "Session", Session)
    monkeypatch.setattr("time.sleep", lambda _: None)
    statuses = [403, 200]
    assert CdsStore(tmp_path / "ok")["t2m/1.2.3"] == b"chunk"
    statuses = [403, 403, 403]
    with pytest.raises(RuntimeError, match="403"):
        CdsStore(tmp_path / "bad")["t2m/1.2.3"]
    assert not (tmp_path / "bad" / "t2m/1.2.3").exists()
    assert not (tmp_path / "bad" / ".missing" / "t2m/1.2.3").exists()


def test_append_only_archive_growth_checks_historical_overlap(tmp_path):
    zarr = pytest.importorskip("zarr")
    from pound_build.ingest.climate_cds import CdsStore

    memory = zarr.MemoryStore()
    root = zarr.group(store=memory)
    first = np.datetime64("2025-01-01T00", "h").astype("int64")
    root.create_dataset(
        "time", data=np.arange(first, first + 4), chunks=(8,), dimension_separator="."
    )
    root["time"].attrs["units"] = "hours since 1970-01-01"
    root.create_dataset(
        "t2m",
        data=np.arange(280, 284, dtype="float32")[:, None, None],
        chunks=(8, 1, 1),
        dimension_separator=".",
    )
    zarr.consolidate_metadata(memory)
    store = CdsStore(tmp_path, fetch=memory.__getitem__)
    original_fingerprint = store.verify_snapshot()
    cached = zarr.open_consolidated(store, mode="r")
    cached["time"][:]
    cached["t2m"][:]
    root["time"].resize(6)
    root["time"][4:] = np.arange(first + 4, first + 6)
    root["t2m"].resize(6, 1, 1)
    root["t2m"][4:] = np.array([284, 285], dtype="float32")[:, None, None]
    zarr.consolidate_metadata(memory)
    assert (
        store.verify_snapshot(historical_end=np.datetime64("2025-01-01T02")) == original_fingerprint
    )
    # A correction within requested historical data must fail, even with append-only metadata.
    root["t2m"][1, 0, 0] = 299
    with pytest.raises(ValueError, match="historical chunk changed"):
        store.verify_snapshot(historical_end=np.datetime64("2025-01-01T02"))


def test_append_verification_rejects_nested_chunk_keys(tmp_path):
    import json

    from pound_build.ingest.climate_cds import CdsStore

    zarr = pytest.importorskip("zarr")
    memory = zarr.MemoryStore()
    root = zarr.group(store=memory)
    root.create_dataset("time", data=np.arange(4), chunks=(8,), dimension_separator="/")
    root["time"].attrs["units"] = "hours since 1970-01-01"
    root.create_dataset("t2m", data=np.ones((4, 1, 1)), chunks=(8, 1, 1), dimension_separator="/")
    zarr.consolidate_metadata(memory)
    store = CdsStore(tmp_path, fetch=memory.__getitem__)
    store.verify_snapshot()
    new = json.loads(memory[".zmetadata"])
    for name in ("time", "t2m"):
        new["metadata"][name + "/.zarray"]["shape"][0] = 6
    memory[".zmetadata"] = json.dumps(new).encode()
    with pytest.raises(ValueError, match="chunk encoding"):
        store.verify_snapshot(historical_end=np.datetime64("1970-01-01T02"))
