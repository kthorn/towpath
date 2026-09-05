"""Strict, versioned JSON models for historical climate data."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    field_validator,
    model_validator,
)

from pound.climate.calendar import WEEK_COUNT, week_label

PERIOD_KEYS = frozenset({"5", "25"})
MAX_CLIMATE_LOCATIONS = 500
CLIMATE_SCHEMA_VERSION = 1
PERIOD_YEARS = (25, 5)


def _linear_quantile(values: list[float], probability: float) -> float:
    index = (len(values) - 1) * probability
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return values[lower]
    fraction = index - lower
    return values[lower] + (values[upper] - values[lower]) * fraction


class InvalidClimateArtifactError(ValueError):
    """Raised when a climate artifact is absent, corrupt, or violates its contract."""


class ClimateSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    url: str
    attribution: str
    timezone: str
    model: str

    @field_validator("name", "url", "attribution", "timezone", "model")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source fields must be nonblank")
        return value

    @field_validator("url")
    @classmethod
    def require_web_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source url must be an absolute HTTP(S) URL")
        return value


class ClimateCoordinate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    lat: FiniteFloat = Field(ge=-90, le=90)
    lon: FiniteFloat = Field(ge=-180, le=180)


class ClimateDistribution(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    available: bool
    missing_years: list[int]
    start_year: int
    end_year: int
    n_days: int = Field(ge=0)
    n_years: int = Field(ge=0)
    p10: FiniteFloat | None
    median: FiniteFloat | None
    p90: FiniteFloat | None
    samples: list[FiniteFloat]

    @field_validator("missing_years")
    @classmethod
    def validate_missing_years(cls, years: list[int]) -> list[int]:
        if years != sorted(set(years)):
            raise ValueError("missing_years must be sorted and unique")
        return years

    @field_validator("samples")
    @classmethod
    def validate_sorted_samples(cls, values: list[float]) -> list[float]:
        if values != sorted(values):
            raise ValueError("samples must be sorted")
        if not all(math.isfinite(value) for value in values):
            raise ValueError("samples must be finite")
        return values

    @model_validator(mode="after")
    def validate_consistency(self):
        if self.start_year > self.end_year:
            raise ValueError("start_year must be no greater than end_year")
        expected_years = set(range(self.start_year, self.end_year + 1))
        if not set(self.missing_years) <= expected_years:
            raise ValueError("missing_years must fall within start_year and end_year")
        expected_complete_years = len(expected_years) - len(self.missing_years)
        if self.n_years != expected_complete_years or self.n_days != self.n_years * 7:
            raise ValueError("n_years and n_days must describe complete seven-day years")
        if self.available:
            if self.missing_years or self.n_years != len(expected_years):
                raise ValueError("available distributions require every eligible year")
            if len(self.samples) != self.n_days:
                raise ValueError("available samples must match n_days")
            if self.p10 is None or self.median is None or self.p90 is None:
                raise ValueError("available distributions require all quantiles")
            if not self.p10 <= self.median <= self.p90:
                raise ValueError("quantiles must be ordered")
            expected = (
                _linear_quantile(self.samples, 0.10),
                _linear_quantile(self.samples, 0.50),
                _linear_quantile(self.samples, 0.90),
            )
            actual = (self.p10, self.median, self.p90)
            if not all(
                math.isclose(observed, calculated, rel_tol=1e-12, abs_tol=1e-12)
                for observed, calculated in zip(actual, expected, strict=True)
            ):
                raise ValueError("quantiles must match the sorted samples")
        elif self.samples or any(value is not None for value in (self.p10, self.median, self.p90)):
            raise ValueError("unavailable distributions cannot contain samples or quantiles")
        elif not self.missing_years:
            raise ValueError("unavailable distributions require missing_years metadata")
        return self


PeriodDistributions = Annotated[
    dict[Literal["25", "5"], ClimateDistribution],
    Field(min_length=2, max_length=2),
]


class ClimateWeek(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    week_id: int = Field(ge=0, lt=WEEK_COUNT)
    label: str
    high: PeriodDistributions
    low: PeriodDistributions

    @field_validator("high", "low")
    @classmethod
    def validate_period_keys(cls, values: dict[str, ClimateDistribution]):
        if set(values) != PERIOD_KEYS:
            raise ValueError("each metric must contain exactly the 5-year and 25-year periods")
        return values

    @model_validator(mode="after")
    def validate_label(self):
        if self.label != week_label(self.week_id):
            raise ValueError(f"label does not match week_id {self.week_id}")
        return self


class ClimateLocationSpec(BaseModel):
    """Configured request location used by the offline importer."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    name: str
    coordinate: ClimateCoordinate

    @field_validator("id", "name")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("location id and name must be nonblank")
        return value


class ClimateLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    name: str
    coordinate: ClimateCoordinate
    source_coordinate: ClimateCoordinate
    elevation: FiniteFloat | None
    weeks: list[ClimateWeek]

    @model_validator(mode="after")
    def validate_windows(self):
        if len(self.weeks) != WEEK_COUNT:
            raise ValueError(f"locations must contain exactly {WEEK_COUNT} weeks")
        if [week.week_id for week in self.weeks] != list(range(WEEK_COUNT)):
            raise ValueError("weeks must be ordered by week_id from 0 through 17")
        return self


class ClimateArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[CLIMATE_SCHEMA_VERSION]
    revision: str
    end_year: int
    built_at: AwareDatetime
    source: ClimateSource
    locations: list[ClimateLocation] = Field(max_length=MAX_CLIMATE_LOCATIONS)

    @field_validator("revision")
    @classmethod
    def require_revision(cls, value: str) -> str:
        if not value.strip() or value == "pending":
            raise ValueError("revision must be a finalized content revision")
        return value

    @field_validator("built_at", mode="before")
    @classmethod
    def parse_built_at(cls, value):
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("built_at must be an ISO-8601 timestamp") from exc
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("built_at must include a timezone")
        return value.astimezone(UTC)

    @field_validator("locations")
    @classmethod
    def validate_unique_locations(cls, values: list[ClimateLocation]) -> list[ClimateLocation]:
        ids = [location.id for location in values]
        if len(ids) != len(set(ids)):
            raise ValueError("location ids must be unique")
        return values

    @model_validator(mode="after")
    def validate_periods(self):
        if self.end_year < 1900:
            raise ValueError("end_year is outside the supported calendar range")
        if self.source.timezone != "Europe/London":
            raise ValueError("climate source timezone must be Europe/London")
        for location in self.locations:
            for week in location.weeks:
                for metric in (week.high, week.low):
                    for period_years in PERIOD_YEARS:
                        summary = metric[str(period_years)]
                        expected_start = self.end_year - period_years + 1
                        if (summary.start_year, summary.end_year) != (
                            expected_start,
                            self.end_year,
                        ):
                            raise ValueError(
                                "distribution period endpoints must match artifact end_year"
                            )
        if self.revision != _content_revision(self):
            raise ValueError("revision does not match artifact content")
        return self


DEFAULT_SOURCE = ClimateSource(
    name="Open-Meteo Historical Weather API",
    url="https://open-meteo.com/en/docs/historical-weather-api",
    attribution="Open-Meteo, ERA5-Land reanalysis",
    timezone="Europe/London",
    model="era5_land",
)


def _content_revision(artifact: ClimateArtifact) -> str:
    payload = artifact.model_dump(mode="json")
    payload.pop("revision", None)
    payload.pop("built_at", None)
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def write_climate(artifact: ClimateArtifact, path: Path) -> None:
    """Validate and atomically write an uncompressed climate JSON artifact."""

    try:
        validated = ClimateArtifact.model_validate(artifact.model_dump(mode="python"))
    except Exception as exc:
        raise InvalidClimateArtifactError(f"invalid climate artifact: {exc}") from exc
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = stream.name
            json.dump(validated.model_dump(mode="json"), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass


def load_climate(path: Path) -> ClimateArtifact:
    """Load and strictly validate a climate JSON artifact."""

    path = Path(path)
    try:
        with path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
        return ClimateArtifact.model_validate(payload)
    except InvalidClimateArtifactError:
        raise
    except Exception as exc:
        raise InvalidClimateArtifactError(f"could not load climate artifact: {exc}") from exc
