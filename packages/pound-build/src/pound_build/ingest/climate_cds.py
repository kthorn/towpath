"""Offline Copernicus ERA5-Land acquisition and London-local daily aggregation."""

import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, MutableMapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import requests
from pound.climate.artifact import ClimateLocationSpec


def summer_hours(year: int) -> np.ndarray:
    """UTC hour labels for all 126 complete London-local summer days."""
    if not 1950 <= year < datetime.now(UTC).year:
        raise ValueError("year must be a complete ERA5-Land year")
    london = ZoneInfo("Europe/London")
    start = datetime(year, 5, 1, tzinfo=london).astimezone(UTC).replace(tzinfo=None)
    stop = datetime(year, 9, 4, tzinfo=london).astimezone(UTC).replace(tzinfo=None)
    return np.arange(np.datetime64(start, "h"), np.datetime64(stop, "h"))


def daily_extrema(
    hours: np.ndarray, kelvin: np.ndarray, year: int
) -> tuple[np.ndarray, np.ndarray]:
    """Daily highs/lows in Celsius; missing or nonfinite hours invalidate the day.

    Input time labels are UTC datetime64 values and values have shape (hours, points).
    Every expected hour must occur once; no partial-day extrema are inferred.
    """
    hours = np.asarray(hours)
    kelvin = np.ma.asarray(kelvin, dtype=np.float64).filled(np.nan).copy()
    kelvin[(kelvin < 150) | (kelvin > 350)] = np.nan
    if hours.ndim != 1 or kelvin.ndim != 2 or kelvin.shape[0] != len(hours):
        raise ValueError("expected one time axis and (hours, points) temperatures")
    if not np.issubdtype(hours.dtype, np.datetime64):
        raise ValueError("hours must be UTC datetime64 labels")
    if np.isnat(hours).any() or np.any(np.diff(hours) <= np.timedelta64(0, "h")):
        raise ValueError("hour labels must be strictly increasing")
    if np.any(hours != hours.astype("datetime64[h]")):
        raise ValueError("time labels must be aligned to exact hours")
    expected = summer_hours(year)
    positions = np.searchsorted(expected, hours)
    keep = (positions < len(expected)) & (hours >= expected[0])
    values = np.full((len(expected), kelvin.shape[1]), np.nan, dtype=np.float64)
    values[positions[keep]] = kelvin[keep]
    days = values.reshape(126, 24, kelvin.shape[1])
    complete = np.isfinite(days).all(axis=1)
    high = days.max(axis=1) - 273.15
    low = days.min(axis=1) - 273.15
    high[~complete] = np.nan
    low[~complete] = np.nan
    return high, low


CDS_ZARR_URL = (
    "https://arco.datastores.ecmwf.int/cadl-arco-geo-007/arco/"
    "reanalysis_era5_land/sfc-2m-temperature/geoChunked.zarr"
)


class CdsStore(MutableMapping[str, bytes]):
    """Read-only HTTP Zarr mapping with atomic, resumable local chunk caching.

    Credentials are read only when needed and sent only to the official CDS host.
    They never appear in cache keys, stored metadata, or raised error messages.
    """

    def __init__(self, cache_dir: Path | str, *, fetch: Callable[[str], bytes] | None = None):
        self.cache_dir = Path(cache_dir)
        self.fetch = fetch or self._download
        self.downloaded_bytes = 0
        self.downloaded_chunks = 0
        self._session = None

    def verify_snapshot(self, *, historical_end=None, progress=None) -> str:
        """Revalidate metadata; allow appended future hours only after overlap checks."""
        marker = self.cache_dir / "source.json"
        if marker.exists() and json.loads(marker.read_text()).get("url") != CDS_ZARR_URL:
            raise ValueError("cached source URL does not match official CDS source")
        current = self.fetch(".zmetadata")
        if not isinstance(json.loads(current), dict):
            raise ValueError("invalid CDS metadata")
        path = self.cache_dir / ".zmetadata"
        original = path.read_bytes() if path.exists() else current
        if json.loads(original) != json.loads(current):
            if historical_end is None:
                raise ValueError("CDS metadata changed; use a new source cache and validate again")
            self._verify_append(original, current, historical_end, progress)
        digest = hashlib.sha256(original).hexdigest()
        identity = {"url": CDS_ZARR_URL, "metadata_sha256": digest}
        if marker.exists() and json.loads(marker.read_text()) != identity:
            raise ValueError("cached source identity mismatch")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        _atomic_bytes(path, original)
        _atomic_bytes(marker, json.dumps(identity, sort_keys=True).encode())
        return digest

    def _verify_append(self, original, current, historical_end, progress):
        """Check cached tail chunks when the archive only appends future hours.

        Retain original metadata/cache identity and validate the requested historical
        prefix of every cached chunk affected by the extension, including 404 fills.
        Corrections in older unchanged chunks cannot be detected by metadata alone.
        """
        import copy

        import zarr
        from numcodecs import get_codec

        old = json.loads(original)
        new = json.loads(current)
        normalized = copy.deepcopy(new)
        try:
            old_length = old["metadata"]["time/.zarray"]["shape"][0]
            new_length = new["metadata"]["time/.zarray"]["shape"][0]
            if new_length <= old_length:
                raise ValueError("CDS metadata changed beyond an append-only extension")
            for name in ("time", "t2m", "d2m"):
                key = name + "/.zarray"
                if key not in old["metadata"]:
                    continue
                if new["metadata"][key]["shape"][0] != new_length:
                    raise ValueError("inconsistent appended array lengths")
                normalized["metadata"][key]["shape"][0] = old_length
            if normalized != old:
                raise ValueError("CDS metadata changed beyond an append-only extension")
        except (KeyError, TypeError, IndexError):
            raise ValueError("unsupported changed CDS metadata") from None
        group = zarr.open_consolidated(self, mode="r")
        if group["time"].attrs.get("units") != "hours since 1970-01-01":
            raise ValueError("unsupported CDS time encoding")
        hours = np.asarray(group["time"][:]).astype("datetime64[h]")
        if historical_end > hours[-1]:
            raise ValueError("requested history is outside original source snapshot")
        cutoff = int(np.searchsorted(hours, historical_end, side="right"))
        checked = []
        for name in ("time", "t2m"):
            meta = old["metadata"][name + "/.zarray"]
            chunks = tuple(meta["chunks"])
            if (
                meta.get("filters")
                or meta.get("order") != "C"
                or meta.get("dimension_separator", ".") != "."
            ):
                raise ValueError("unsupported CDS chunk encoding for overlap validation")
            codec = get_codec(meta["compressor"]) if meta.get("compressor") else None
            names = set()
            for directory in (self.cache_dir / name, self.cache_dir / ".missing" / name):
                if directory.exists():
                    names.update(
                        p.name
                        for p in directory.iterdir()
                        if p.is_file() and re.fullmatch(r"\d+(?:\.\d+)*", p.name)
                    )
            for filename in sorted(names):
                first = int(filename.split(".")[0]) * chunks[0]
                if first + chunks[0] <= old_length or first >= cutoff:
                    continue
                key = name + "/" + filename

                def decoded(data, meta=meta, chunks=chunks, codec=codec):
                    if data is None:
                        fill = meta.get("fill_value")
                        return np.full(chunks, 0 if fill is None else fill, dtype=meta["dtype"])
                    raw = codec.decode(data) if codec else data
                    return np.frombuffer(raw, dtype=meta["dtype"]).reshape(chunks)

                try:
                    before = self[key]
                except KeyError:
                    before = None
                try:
                    after = self.fetch(key)
                except KeyError:
                    after = None
                n = min(chunks[0], cutoff - first)
                if not np.array_equal(decoded(before)[:n], decoded(after)[:n], equal_nan=True):
                    raise ValueError("CDS historical chunk changed: " + key)
                checked.append(key)
                if progress:
                    progress({"stage": "verify-extension", "checked_chunks": len(checked)})
        report = {
            "original_metadata_sha256": hashlib.sha256(original).hexdigest(),
            "current_metadata_sha256": hashlib.sha256(current).hexdigest(),
            "historical_end": str(historical_end),
            "checked_chunks": checked,
            "verified_at": datetime.now(UTC).isoformat(),
        }
        _atomic_bytes(
            self.cache_dir.parent / "extension-verification.json",
            json.dumps(report, sort_keys=True).encode(),
        )

    def _download(self, key: str) -> bytes:
        for attempt in range(3):
            if self._session is None:
                token = os.environ.get("CDSAPI_KEY")
                if not token:
                    path = Path.home() / ".cdsapirc"
                    if path.exists():
                        for line in path.read_text().splitlines():
                            if line.strip().startswith("key:"):
                                token = line.split(":", 1)[1].strip().strip("\"'")
                                break
                if not token:
                    raise RuntimeError("Configure CDSAPI_KEY or ~/.cdsapirc before acquisition")
                self._session = requests.Session()
                self._session.headers["Authorization"] = "Bearer " + token
            try:
                response = self._session.get(
                    CDS_ZARR_URL + "/" + key, timeout=120, allow_redirects=False
                )
            except requests.RequestException:
                if attempt == 2:
                    raise RuntimeError("CDS connection failed; cached chunks retained") from None
                self._session.close()
                self._session = None
                time.sleep(2 ** (attempt + 1))
                continue
            if response.status_code == 404:
                raise KeyError(key)
            if response.status_code == 200:
                return response.content
            try:
                error_code = response.json().get("_errorCode", "unknown")
            except (ValueError, AttributeError):
                error_code = "non-JSON provider error"
            error_code = re.sub(r"[^A-Za-z0-9 _-]", "", str(error_code))[:80]
            # The service has returned stale licence errors immediately after
            # acceptance; retry the same authenticated request, never skip it.
            transient = response.status_code in (429, 500, 502, 503, 504) or (
                response.status_code == 403 and error_code == "LICENSES_NOT_ACCEPTED"
            )
            if transient and attempt < 2:
                delay = 2 ** (attempt + 1)
                try:
                    delay = max(delay, min(60, float(response.headers.get("Retry-After", 0))))
                except ValueError:
                    pass
                self._session.close()
                self._session = None
                time.sleep(delay)
                continue
            raise RuntimeError(f"CDS download HTTP {response.status_code} for {key}: {error_code}")

    def __getitem__(self, key: str) -> bytes:
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_.]+(?:/[A-Za-z0-9_.]+)*", key):
            raise KeyError(key)
        if any(part in (".", "..") for part in key.split("/")):
            raise KeyError(key)
        path = self.cache_dir / key
        if path.is_file():
            return path.read_bytes()
        missing = self.cache_dir / ".missing" / key
        if missing.exists():
            raise KeyError(key)
        try:
            data = self.fetch(key)
        except KeyError:
            _atomic_bytes(missing, b"")
            raise
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                temporary = stream.name
                stream.write(data)
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        self.downloaded_bytes += len(data)
        self.downloaded_chunks += 1
        return data

    def __iter__(self) -> Iterator[str]:
        return (
            str(p.relative_to(self.cache_dir)) for p in self.cache_dir.rglob("*") if p.is_file()
        )

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __setitem__(self, key: str, value: bytes) -> None:
        raise TypeError("CDS store is read-only")

    def __delitem__(self, key: str) -> None:
        raise TypeError("CDS store is read-only")


def nearest_land_point(
    lat: float,
    lon: float,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    valid: np.ndarray,
    *,
    max_distance_km: float = 15,
) -> tuple[int, int, float] | None:
    """Nearest finite model land point, with geographic wrap and bounded distance."""
    longitude_delta = (np.asarray(longitudes) - lon + 180) % 360 - 180
    dx = longitude_delta[None, :] * 111.195 * np.cos(np.deg2rad(lat))
    dy = (np.asarray(latitudes)[:, None] - lat) * 111.195
    distance = np.hypot(dx, dy)
    eligible = np.asarray(valid) & (distance <= max_distance_km)
    if not eligible.any():
        return None
    ranked = np.where(eligible, distance, np.inf)
    row, column = np.unravel_index(np.argmin(ranked), ranked.shape)
    return int(row), int(column), float(distance[row, column])


def cache_endpoint(fingerprint: str) -> str:
    """Separate daily cache identity from Open-Meteo and other source snapshots."""
    return CDS_ZARR_URL + "#london-hourly-v1-land15km-" + fingerprint


def acquire_cells(
    locations: Iterable[ClimateLocationSpec | Mapping[str, Any]],
    group: Any,
    cache_dir: Path,
    end_year: int,
    fingerprint: str,
) -> Iterator[dict[str, Any]]:
    """Yield progress while converting bounded spatial tiles into annual caches.

    Select the nearest model land point within 15 km using one reference hour.
    All subsequent hourly values still require completeness; reference selection
    does not turn gaps elsewhere in the history into available observations.
    """
    from collections import defaultdict
    from datetime import date, timedelta

    from pound_build.ingest.climate import ClimateImporter

    if not 1974 <= end_year < datetime.now(UTC).year:
        raise ValueError("end_year must contain 25 complete ERA5-Land years")
    specs = [ClimateLocationSpec.model_validate(s) for s in locations]
    importer = ClimateImporter(cache_dir=Path(cache_dir), endpoint=cache_endpoint(fingerprint))
    years = range(end_year - 24, end_year + 1)
    todo = []
    for spec in specs:
        if not all(importer._read_cache(spec.id, spec.coordinate, y) is not None for y in years):
            todo.append(spec)
    completed = len(specs) - len(todo)
    yield {"stage": "cache", "completed_cells": completed, "total_cells": len(specs)}
    if not todo:
        return
    temperature = group["t2m"]
    if temperature.attrs.get("units") != "K":
        raise ValueError("CDS temperature must be Kelvin")
    if group["time"].attrs.get("units") != "hours since 1970-01-01":
        raise ValueError("unsupported CDS time encoding")
    hours = np.asarray(group["time"][:]).astype("datetime64[h]")
    if np.isnat(hours).any() or np.any(np.diff(hours) != np.timedelta64(1, "h")):
        raise ValueError("CDS source time axis must have consecutive hourly labels")
    latitudes = np.asarray(group["latitude"][:])
    longitudes = (np.asarray(group["longitude"][:]) + 180) % 360 - 180
    if temperature.shape != (len(hours), len(latitudes), len(longitudes)):
        raise ValueError("unexpected CDS array dimensions")
    first, last = summer_hours(end_year - 24)[0], summer_hours(end_year)[-1]
    if hours[0] > first or hours[-1] < last:
        raise ValueError("CDS source does not cover requested historical years")
    start = int(np.searchsorted(hours, first))
    stop = int(np.searchsorted(hours, last)) + 1
    probe = int(np.searchsorted(hours, summer_hours(end_year)[0]))
    _, cy, cx = temperature.chunks
    candidates = {}
    tiles = set()
    for spec in todo:
        lat, lon = spec.coordinate.lat, spec.coordinate.lon
        ys = np.flatnonzero(np.abs(latitudes - lat) * 111.195 <= 15)
        xs = np.flatnonzero(
            np.abs((longitudes - lon + 180) % 360 - 180) * 111.195 * np.cos(np.deg2rad(lat)) <= 15
        )
        candidates[spec.id] = (ys, xs)
        tiles.update((int(y) // cy, int(x) // cx) for y in ys for x in xs)
    valid = np.zeros((len(latitudes), len(longitudes)), dtype=bool)
    for index, (ty, tx) in enumerate(sorted(tiles)):
        y, x = ty * cy, tx * cx
        values = np.asarray(temperature[probe, y : y + cy, x : x + cx])
        valid[y : y + cy, x : x + cx] = np.isfinite(values) & (values >= 150) & (values <= 350)
        yield {
            "stage": "land-mask",
            "tiles": index + 1,
            "total_tiles": len(tiles),
            "completed_cells": completed,
        }
    grouped = defaultdict(list)
    missing = []
    for spec in todo:
        ys, xs = candidates[spec.id]
        selected = nearest_land_point(
            spec.coordinate.lat,
            spec.coordinate.lon,
            latitudes[ys],
            longitudes[xs],
            valid[np.ix_(ys, xs)],
        )
        if selected is None:
            missing.append(spec)
        else:
            row, col, distance = selected
            iy, ix = int(ys[row]), int(xs[col])
            grouped[(iy // cy, ix // cx)].append((spec, iy, ix, distance))
    for tile_index, ((ty, tx), points) in enumerate(sorted(grouped.items())):
        y, x = ty * cy, tx * cx
        block = np.asarray(temperature[start:stop, y : y + cy, x : x + cx])
        selected_values = np.stack([block[:, iy - y, ix - x] for _, iy, ix, _ in points], axis=1)
        for year in years:
            expected = summer_hours(year)
            a, b = np.searchsorted(hours[start:stop], [expected[0], expected[-1]])
            highs, lows = daily_extrema(
                hours[start + a : start + b + 1], selected_values[a : b + 1], year
            )
            days = [(date(year, 5, 1) + timedelta(days=i)).isoformat() for i in range(126)]
            for j, (spec, iy, ix, distance) in enumerate(points):
                payload = {
                    "latitude": float(latitudes[iy]),
                    "longitude": float(longitudes[ix]),
                    "elevation": None,
                    "timezone": "Europe/London",
                    "source_distance_km": distance,
                    "source_metadata_sha256": fingerprint,
                    "daily_units": {"temperature_2m_max": "°C", "temperature_2m_min": "°C"},
                    "daily": {
                        "time": days,
                        "temperature_2m_max": [
                            float(v) if np.isfinite(v) else None for v in highs[:, j]
                        ],
                        "temperature_2m_min": [
                            float(v) if np.isfinite(v) else None for v in lows[:, j]
                        ],
                    },
                }
                importer._write_cache(spec.id, spec.coordinate, year, payload)
        completed += len(points)
        del block, selected_values
        yield {
            "stage": "annual",
            "tiles": tile_index + 1,
            "total_tiles": len(grouped),
            "completed_cells": completed,
            "total_cells": len(specs),
        }
    for spec in missing:
        for year in years:
            days = [(date(year, 5, 1) + timedelta(days=i)).isoformat() for i in range(126)]
            importer._write_cache(
                spec.id,
                spec.coordinate,
                year,
                {
                    "latitude": spec.coordinate.lat,
                    "longitude": spec.coordinate.lon,
                    "elevation": None,
                    "timezone": "Europe/London",
                    "unavailable_reason": "No ERA5-Land land point within 15 km",
                    "source_metadata_sha256": fingerprint,
                    "daily_units": {"temperature_2m_max": "°C", "temperature_2m_min": "°C"},
                    "daily": {
                        "time": days,
                        "temperature_2m_max": [None] * 126,
                        "temperature_2m_min": [None] * 126,
                    },
                },
            )
        completed += 1
    yield {
        "stage": "complete",
        "completed_cells": completed,
        "total_cells": len(specs),
        "unavailable_cells": [s.id for s in missing],
    }


def _atomic_bytes(path: Path, data: bytes) -> None:
    """Publish complete cache metadata without truncating an existing snapshot."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
