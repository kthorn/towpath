"""Offline Open-Meteo climate acquisition and artifact assembly.

The request-time application never imports this module.  Each successful seasonal
response is cached independently so an interrupted acquisition can resume at the next
location/year batch.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import requests
from pound.climate.artifact import (
    DEFAULT_SOURCE,
    PERIOD_YEARS,
    ClimateArtifact,
    ClimateCoordinate,
    ClimateLocation,
    ClimateLocationSpec,
    ClimateSource,
    ClimateWeek,
)
from pound.climate.calendar import WEEK_COUNT, week_dates, week_label
from pound.climate.statistics import summarize_distribution

OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
SEASON_START = (5, 1)
SEASON_END = (9, 3)
_SAFE_LOCATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _finite(value: Any, *, field: str, allow_none: bool = True) -> float | None:
    if value is None and allow_none:
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric or null") from exc
    if not math.isfinite(converted):
        raise ValueError(f"{field} must be finite")
    return converted


def normalize_history_payload(payload: Mapping[str, Any], *, expected_year: int) -> dict[str, Any]:
    """Validate one Open-Meteo daily response and return a JSON-safe copy.

    All returned days remain in the payload's original order.  Missing metric values
    are retained as nulls so high and low completeness can be assessed independently.
    """

    if not isinstance(payload, Mapping):
        raise ValueError("climate response must be an object")
    timezone = payload.get("timezone")
    if timezone is not None and timezone != "Europe/London":
        raise ValueError("climate response timezone must be Europe/London")
    daily_units = payload.get("daily_units")
    if not isinstance(daily_units, Mapping):
        raise ValueError("climate response must contain daily_units in Celsius")
    for metric in ("temperature_2m_max", "temperature_2m_min"):
        if daily_units.get(metric) != "°C":
            raise ValueError(f"daily unit for {metric} must be Celsius")
    for field in ("latitude", "longitude", "elevation"):
        if field in payload and payload[field] is not None:
            _finite(payload[field], field=field)
    daily = payload.get("daily")
    if not isinstance(daily, Mapping):
        raise ValueError("climate response must contain a daily object")
    times = daily.get("time")
    highs = daily.get("temperature_2m_max")
    lows = daily.get("temperature_2m_min")
    if not isinstance(times, list) or not isinstance(highs, list) or not isinstance(lows, list):
        raise ValueError("daily time, maximum, and minimum arrays are required")
    if not len(times) == len(highs) == len(lows):
        raise ValueError("daily arrays must have equal lengths")

    seen: set[date] = set()
    clean_times: list[str] = []
    clean_highs: list[float | None] = []
    clean_lows: list[float | None] = []
    for index, (raw_time, raw_high, raw_low) in enumerate(zip(times, highs, lows, strict=True)):
        if not isinstance(raw_time, str):
            raise ValueError(f"daily date at index {index} must be an ISO date")
        try:
            day = date.fromisoformat(raw_time)
        except ValueError as exc:
            raise ValueError(f"daily date at index {index} is invalid") from exc
        if day.year != expected_year:
            raise ValueError(f"daily date {raw_time} is outside expected year {expected_year}")
        if day in seen:
            raise ValueError(f"daily date {raw_time} is duplicate")
        seen.add(day)
        high = _finite(raw_high, field=f"daily maximum at index {index}")
        low = _finite(raw_low, field=f"daily minimum at index {index}")
        if high is not None and low is not None and low > high:
            raise ValueError(f"daily minimum exceeds maximum at {raw_time}")
        clean_times.append(day.isoformat())
        clean_highs.append(high)
        clean_lows.append(low)

    normalized = dict(payload)
    for field in ("latitude", "longitude", "elevation"):
        if field in normalized and normalized[field] is not None:
            normalized[field] = _finite(normalized[field], field=field)
    normalized["daily"] = {
        "time": clean_times,
        "temperature_2m_max": clean_highs,
        "temperature_2m_min": clean_lows,
    }
    return normalized


def _location_spec(value: ClimateLocationSpec | Mapping[str, Any]) -> ClimateLocationSpec:
    return (
        value
        if isinstance(value, ClimateLocationSpec)
        else ClimateLocationSpec.model_validate(value)
    )


def _coordinate(value: ClimateCoordinate | Mapping[str, Any]) -> ClimateCoordinate:
    return (
        value
        if isinstance(value, ClimateCoordinate)
        else ClimateCoordinate.model_validate(value)
    )


def _safe_cache_id(location_id: str) -> str:
    if not _SAFE_LOCATION_ID.fullmatch(location_id):
        raise ValueError(
            "location ids may contain only letters, numbers, underscore, dot, and hyphen"
        )
    return location_id


def _season_bounds(year: int) -> tuple[str, str]:
    return (
        f"{year}-{SEASON_START[0]:02d}-{SEASON_START[1]:02d}",
        f"{year}-{SEASON_END[0]:02d}-{SEASON_END[1]:02d}",
    )


class ClimateImporter:
    """Resumable seasonal-year importer with one cache file per request."""

    def __init__(
        self,
        cache_dir: Path = Path("data/climate"),
        *,
        endpoint: str = OPEN_METEO_ARCHIVE_URL,
        session: requests.Session | None = None,
        fetcher: Callable[[str, Mapping[str, float], int], Mapping[str, Any]] | None = None,
        retries: int = 3,
        backoff_seconds: float = 1.0,
        request_interval_seconds: float = 1.0,
        timeout_seconds: float = 60.0,
    ) -> None:
        if retries < 1:
            raise ValueError("retries must be positive")
        if backoff_seconds < 0 or request_interval_seconds < 0 or timeout_seconds <= 0:
            raise ValueError("retry, pacing, and timeout values are invalid")
        self.cache_dir = Path(cache_dir)
        self.endpoint = endpoint
        self.session = session or requests.Session()
        self.fetcher = fetcher
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.request_interval_seconds = request_interval_seconds
        self.timeout_seconds = timeout_seconds
        self._last_request_at: float | None = None

    def _cache_path(self, location_id: str, year: int) -> Path:
        return self.cache_dir / _safe_cache_id(location_id) / f"{year}.json"

    def _request_parameters(
        self, location_id: str, coordinate: ClimateCoordinate, year: int
    ) -> dict[str, Any]:
        start_date, end_date = _season_bounds(year)
        return {
            "endpoint": self.endpoint,
            "location_id": location_id,
            "latitude": coordinate.lat,
            "longitude": coordinate.lon,
            "start_date": start_date,
            "end_date": end_date,
            "daily": "temperature_2m_max,temperature_2m_min",
            "temperature_unit": "celsius",
            "timezone": "Europe/London",
            "models": "era5_land",
        }

    def _read_cache(
        self, location_id: str, coordinate: ClimateCoordinate, year: int
    ) -> dict[str, Any] | None:
        path = self._cache_path(location_id, year)
        try:
            with path.open(encoding="utf-8") as stream:
                envelope = json.load(stream)
            if not isinstance(envelope, dict) or not set(envelope) <= {
                "request",
                "response",
                "fetched_at",
            } or not {"request", "response"} <= set(envelope):
                return None
            if "fetched_at" in envelope:
                _parse_timestamp(envelope["fetched_at"])
            if envelope["request"] != self._request_parameters(location_id, coordinate, year):
                return None
            return normalize_history_payload(envelope["response"], expected_year=year)
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
            return None

    def _write_cache(
        self,
        location_id: str,
        coordinate: ClimateCoordinate,
        year: int,
        payload: Mapping[str, Any],
    ) -> None:
        path = self._cache_path(location_id, year)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{year}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = stream.name
                json.dump(
                    {
                        "request": self._request_parameters(location_id, coordinate, year),
                        "fetched_at": datetime.now(UTC).isoformat(),
                        "response": payload,
                    },
                    stream,
                    ensure_ascii=False,
                    indent=2,
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

    def _wait_for_pacing(self) -> None:
        if self._last_request_at is None:
            return
        remaining = self.request_interval_seconds - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)

    def _request_year(
        self, location_id: str, coordinate: Mapping[str, float], year: int
    ) -> dict[str, Any]:
        params = self._request_parameters(
            location_id,
            ClimateCoordinate(lat=coordinate["lat"], lon=coordinate["lon"]),
            year,
        )
        params.pop("endpoint")
        params.pop("location_id")
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                self._wait_for_pacing()
                response = self.session.get(
                    self.endpoint, params=params, timeout=self.timeout_seconds
                )
                self._last_request_at = time.monotonic()
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    delay = self.backoff_seconds * (2**attempt)
                    if retry_after:
                        try:
                            delay = max(delay, min(float(retry_after), 60.0))
                        except ValueError:
                            pass
                    if attempt + 1 < self.retries:
                        time.sleep(delay)
                        continue
                response.raise_for_status()
                payload = response.json()
                return normalize_history_payload(payload, expected_year=year)
            except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(self.backoff_seconds * (2**attempt))
                    continue
                break
        raise RuntimeError(f"failed to fetch climate year {year} for {location_id}") from last_error

    def fetch_year(
        self, location_id: str, coordinate: ClimateCoordinate | Mapping[str, float], year: int
    ) -> dict[str, Any]:
        """Load one cached year or fetch, validate, and cache it."""

        if type(year) is not int or not 1900 <= year <= 2200:
            raise ValueError("year is outside the supported range")
        coord = _coordinate(coordinate)
        cached = self._read_cache(location_id, coord, year)
        if cached is not None:
            return cached
        if self.fetcher is None:
            payload = self._request_year(location_id, {"lat": coord.lat, "lon": coord.lon}, year)
        else:
            payload = normalize_history_payload(
                self.fetcher(location_id, {"lat": coord.lat, "lon": coord.lon}, year),
                expected_year=year,
            )
        self._write_cache(location_id, coord, year, payload)
        return payload

    def fetch_histories(
        self, locations: Iterable[ClimateLocationSpec | Mapping[str, Any]], end_year: int
    ) -> dict[str, dict[int, dict[str, Any]]]:
        """Fetch all 25 annual seasonal batches, resuming from cache files."""

        specs = [_location_spec(location) for location in locations]
        histories: dict[str, dict[int, dict[str, Any]]] = {}
        for spec in specs:
            histories[spec.id] = {
                year: self.fetch_year(spec.id, spec.coordinate, year)
                for year in range(end_year - 24, end_year + 1)
            }
        return histories

    def load_cached_histories(
        self, locations: Iterable[ClimateLocationSpec | Mapping[str, Any]], end_year: int
    ) -> dict[str, dict[int, dict[str, Any]]]:
        """Read all expected annual cache files and fail if one is unavailable."""

        specs = [_location_spec(location) for location in locations]
        histories: dict[str, dict[int, dict[str, Any]]] = {}
        for spec in specs:
            location_history: dict[int, dict[str, Any]] = {}
            for year in range(end_year - 24, end_year + 1):
                payload = self._read_cache(spec.id, spec.coordinate, year)
                if payload is None:
                    raise FileNotFoundError(
                        f"missing cached climate response for {spec.id} in {year}"
                    )
                location_history[year] = payload
            histories[spec.id] = location_history
        return histories


def _daily_by_date(
    payload: Mapping[str, Any], year: int
) -> dict[date, tuple[float | None, float | None]]:
    normalized = normalize_history_payload(payload, expected_year=year)
    daily = normalized["daily"]
    return {
        date.fromisoformat(day): (high, low)
        for day, high, low in zip(
            daily["time"], daily["temperature_2m_max"], daily["temperature_2m_min"], strict=True
        )
    }


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("fetched_at must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("fetched_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("fetched_at must include a timezone")
    return parsed


def _history_metadata(
    histories: Mapping[int, Mapping[str, Any]],
    spec: ClimateLocationSpec,
    years: range,
) -> tuple[ClimateCoordinate, float | None]:
    source_coordinate: ClimateCoordinate | None = None
    elevation: float | None = None
    for year in years:
        payload = histories.get(year) or histories.get(str(year))
        if payload is None:
            continue
        normalized = normalize_history_payload(payload, expected_year=year)
        latitude = normalized.get("latitude")
        longitude = normalized.get("longitude")
        if latitude is None or longitude is None:
            raise ValueError("provider response is missing source coordinates")
        response_coordinate = ClimateCoordinate(
            lat=_finite(latitude, field="latitude", allow_none=False),
            lon=_finite(longitude, field="longitude", allow_none=False),
        )
        if source_coordinate is not None and (
            response_coordinate.lat != source_coordinate.lat
            or response_coordinate.lon != source_coordinate.lon
        ):
            raise ValueError("source coordinates differ across cached climate years")
        source_coordinate = response_coordinate
        if normalized.get("elevation") is not None:
            response_elevation = _finite(normalized["elevation"], field="elevation")
            if elevation is not None and response_elevation != elevation:
                raise ValueError("source elevations differ across cached climate years")
            elevation = response_elevation
    if source_coordinate is None:
        raise ValueError("provider response is missing source coordinates")
    return source_coordinate, elevation


def build_climate(
    locations: Iterable[ClimateLocationSpec | Mapping[str, Any]],
    end_year: int,
    histories: Mapping[str, Mapping[int | str, Mapping[str, Any]]],
    *,
    source: ClimateSource | Mapping[str, Any] | None = None,
    revision: str | None = None,
) -> ClimateArtifact:
    """Aggregate cached responses into the strictly validated climate artifact."""

    if type(end_year) is not int or not 1900 <= end_year <= 2200:
        raise ValueError("end_year is outside the supported range")
    source_model = (
        source
        if isinstance(source, ClimateSource)
        else ClimateSource.model_validate(source or DEFAULT_SOURCE)
    )
    specs = [_location_spec(location) for location in locations]
    if len(specs) > 500:
        raise ValueError("climate artifacts support at most 500 locations")
    built_locations: list[ClimateLocation] = []
    baseline_years = range(end_year - 24, end_year + 1)
    for spec in specs:
        raw_history = histories.get(spec.id, {})
        by_year: dict[int, dict[date, tuple[float | None, float | None]]] = {}
        for raw_year, payload in raw_history.items():
            try:
                year = int(raw_year)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"history year {raw_year!r} is invalid") from exc
            if year in baseline_years:
                by_year[year] = _daily_by_date(payload, year)
        source_coordinate, elevation = _history_metadata(raw_history, spec, baseline_years)
        weeks: list[ClimateWeek] = []
        for week_id in range(WEEK_COUNT):
            high_by_period: dict[str, Any] = {}
            low_by_period: dict[str, Any] = {}
            for period_years in PERIOD_YEARS:
                start_year = end_year - period_years + 1
                high_values: dict[int, list[float] | None] = {}
                low_values: dict[int, list[float] | None] = {}
                for year in range(start_year, end_year + 1):
                    days = by_year.get(year, {})
                    dates = week_dates(year, week_id)
                    high = (
                        [days[day][0] for day in dates]
                        if all(day in days for day in dates)
                        else None
                    )
                    low = (
                        [days[day][1] for day in dates]
                        if all(day in days for day in dates)
                        else None
                    )
                    high_values[year] = (
                        high
                        if high is not None and all(value is not None for value in high)
                        else None
                    )
                    low_values[year] = (
                        low
                        if low is not None and all(value is not None for value in low)
                        else None
                    )
                high_by_period[str(period_years)] = summarize_distribution(
                    high_values, start_year=start_year, end_year=end_year
                )
                low_by_period[str(period_years)] = summarize_distribution(
                    low_values, start_year=start_year, end_year=end_year
                )
            weeks.append(
                ClimateWeek(
                    week_id=week_id,
                    label=week_label(week_id),
                    high=high_by_period,
                    low=low_by_period,
                )
            )
        built_locations.append(
            ClimateLocation(
                id=spec.id,
                name=spec.name,
                coordinate=spec.coordinate,
                source_coordinate=source_coordinate,
                elevation=elevation,
                weeks=weeks,
            )
        )

    artifact = ClimateArtifact.model_construct(
        schema_version=1,
        revision=revision or "pending",
        end_year=end_year,
        built_at=datetime.now(UTC),
        source=source_model,
        locations=built_locations,
    )
    from pound.climate.artifact import _content_revision

    artifact_revision = revision or _content_revision(artifact)
    return ClimateArtifact.model_validate(
        artifact.model_dump(mode="python") | {"revision": artifact_revision}
    )


def load_location_manifest(path: Path) -> tuple[ClimateLocationSpec, ...]:
    """Load the checked-in location manifest used by the build CLI."""

    try:
        with Path(path).open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read climate location manifest {path}") from exc
    if not isinstance(payload, list):
        raise ValueError("climate location manifest must be a list")
    specs = tuple(ClimateLocationSpec.model_validate(item) for item in payload)
    if len(specs) > 500:
        raise ValueError("climate location manifest supports at most 500 locations")
    return specs
