"""Build and acquire the offline UK climate grid.

The grid builder deliberately lives in :mod:`pound_build`: the application only
opens the resulting SQLite file.  Weather acquisition is resumable through the
same annual Open-Meteo cache used by the named-location climate importer, while
the grid writer processes one cell at a time so a UK-wide build never creates a
large intermediate JSON artifact.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from pound.climate.artifact import (
    CLIMATE_SCHEMA_VERSION,
    DEFAULT_SOURCE,
    ClimateLocationSpec,
    ClimateSource,
)
from pyproj import Transformer
from shapely.geometry import box, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union
from shapely.validation import make_valid

from pound_build.ingest.climate import (
    OPEN_METEO_ARCHIVE_URL,
    ClimateImporter,
    _location_spec,
    _parse_timestamp,
)

GRID_SPACING_METRES = 10_000
GRID_SPACING_KM = 10
GRID_EPSG = 3035
WGS84_EPSG = 4326
# Keep a documented, stable metre-grid origin.  The source mask is WGS84, so
# this origin is an implementation detail rather than a claim about its source.
GRID_ORIGIN_X = 4_321_000
GRID_ORIGIN_Y = 3_210_000
GRID_MAX_CELLS = 10_000
GRID_MIN_END_YEAR = 1974
DEFAULT_WEIGHTED_CALLS_PER_REQUEST = 9
HOURLY_WEIGHTED_CALL_LIMIT = 5_000
DEFAULT_MASK_SOURCE = {
    "name": "ONS Countries December 2024 Boundaries UK BGC",
    "url": (
        "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
        "Countries_December_2024_Boundaries_UK_BGC/FeatureServer/0"
    ),
    "attribution": (
        "Office for National Statistics; contains Ordnance Survey data © Crown "
        "copyright and database right 2024 (ONS Open Government Licence)"
    ),
}

_TO_GRID = Transformer.from_crs(WGS84_EPSG, GRID_EPSG, always_xy=True).transform
_TO_WGS84 = Transformer.from_crs(GRID_EPSG, WGS84_EPSG, always_xy=True).transform


class ClimateGridBudgetExceeded(RuntimeError):
    """Raised before a request would exceed the configured weighted-call budget."""


def _validate_end_year(end_year: int) -> None:
    current_year = datetime.now(UTC).year
    if type(end_year) is not int or not GRID_MIN_END_YEAR <= end_year < current_year:
        raise ValueError(
            f"end_year must be a complete year from {GRID_MIN_END_YEAR} through {current_year - 1}"
        )


@dataclass(frozen=True, slots=True)
class GridCell:
    """A deterministic 10 km target cell and its point-on-land query coordinate."""

    id: str
    name: str
    latitude: float
    longitude: float

    def as_manifest_item(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "coordinate": {"lat": self.latitude, "lon": self.longitude},
        }


def _as_geometry(value: BaseGeometry | Mapping[str, Any] | Path | str) -> BaseGeometry:
    """Read a Polygon/MultiPolygon from GeoJSON, a Feature, or a FeatureCollection."""

    if isinstance(value, BaseGeometry):
        geometry = value
    else:
        if isinstance(value, (str, Path)):
            try:
                with Path(value).open(encoding="utf-8") as stream:
                    value = json.load(stream)
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"could not read land mask {value}") from exc
        if not isinstance(value, Mapping):
            raise ValueError("land mask must be GeoJSON or a Shapely geometry")
        kind = value.get("type")
        if kind == "FeatureCollection":
            features = value.get("features")
            if not isinstance(features, list) or not features:
                raise ValueError("land mask feature collection is empty")
            geometries = [
                shape(feature["geometry"])
                for feature in features
                if isinstance(feature, Mapping) and feature.get("geometry") is not None
            ]
            if not geometries:
                raise ValueError("land mask feature collection has no geometries")
            geometry = unary_union(geometries)
        elif kind == "Feature":
            raw_geometry = value.get("geometry")
            if not isinstance(raw_geometry, Mapping):
                raise ValueError("land mask feature has no geometry")
            geometry = shape(raw_geometry)
        else:
            try:
                geometry = shape(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("land mask must be valid GeoJSON") from exc
    if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("land mask must be a Polygon or MultiPolygon")
    if geometry.is_empty or not geometry.is_valid or not math.isfinite(geometry.area):
        raise ValueError("land mask must be non-empty and valid")
    west, south, east, north = geometry.bounds
    if not all(math.isfinite(value) for value in geometry.bounds):
        raise ValueError("land mask bounds must be finite")
    if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
        raise ValueError("land mask must use WGS84 coordinates")
    return geometry


def load_land_mask(path: Path) -> BaseGeometry:
    """Load and validate a WGS84 ONS GeoJSON land mask."""

    return _as_geometry(path)


def _display_mask(geometry: BaseGeometry, tolerance_metres: float) -> dict[str, Any]:
    if tolerance_metres < 0 or not math.isfinite(tolerance_metres):
        raise ValueError("mask simplification tolerance must be finite and non-negative")
    projected = transform(_TO_GRID, geometry)
    if tolerance_metres == 0:
        simplified = projected
    else:
        parts = projected.geoms if projected.geom_type == "MultiPolygon" else (projected,)
        kept_parts = []
        for part in parts:
            candidate = part.simplify(tolerance_metres, preserve_topology=True)
            if candidate.is_empty or candidate.geom_type != "Polygon" or candidate.area <= 0:
                candidate = part
            kept_parts.append(candidate)
        simplified = unary_union(kept_parts)
        if not simplified.is_valid:
            fixed = make_valid(simplified)
            polygonal = (
                [fixed]
                if fixed.geom_type in {"Polygon", "MultiPolygon"}
                else [part for part in fixed.geoms if part.geom_type == "Polygon"]
            )
            simplified = unary_union(polygonal) if polygonal else projected
    if simplified.is_empty or simplified.geom_type not in {"Polygon", "MultiPolygon"}:
        simplified = projected
    display = transform(_TO_WGS84, simplified)
    if not display.is_valid:
        fixed = make_valid(display)
        polygonal = (
            [fixed]
            if fixed.geom_type in {"Polygon", "MultiPolygon"}
            else [part for part in fixed.geoms if part.geom_type == "Polygon"]
        )
        display = unary_union(polygonal) if polygonal else geometry
    if display.is_empty or not display.is_valid:
        display = geometry
    return json.loads(json.dumps(mapping(display)))


def generate_grid_cells(
    mask: BaseGeometry | Mapping[str, Any] | Path | str,
    *,
    spacing_km: int = GRID_SPACING_KM,
) -> tuple[dict[str, Any], ...]:
    """Generate regular projected cells whose area intersects the supplied land mask.

    Cells are made in EPSG:3035 metres.  A representative point of the land
    intersection is used as the weather query coordinate, which keeps coastal
    and small-island cells even when their geometric centre is at sea.
    """

    if spacing_km != GRID_SPACING_KM:
        raise ValueError(f"only {GRID_SPACING_KM} km cells are supported")
    spacing = spacing_km * 1000
    geometry = _as_geometry(mask)
    projected = transform(_TO_GRID, geometry)
    min_x, min_y, max_x, max_y = projected.bounds
    min_col = math.floor((min_x - GRID_ORIGIN_X) / spacing)
    max_col = math.ceil((max_x - GRID_ORIGIN_X) / spacing) - 1
    min_row = math.floor((min_y - GRID_ORIGIN_Y) / spacing)
    max_row = math.ceil((max_y - GRID_ORIGIN_Y) / spacing) - 1

    cells: list[dict[str, Any]] = []
    for row in range(min_row, max_row + 1):
        for col in range(min_col, max_col + 1):
            x0 = GRID_ORIGIN_X + col * spacing
            y0 = GRID_ORIGIN_Y + row * spacing
            candidate = box(x0, y0, x0 + spacing, y0 + spacing)
            intersection = candidate.intersection(projected)
            if intersection.is_empty or intersection.area <= 0:
                continue
            point = intersection.representative_point()
            longitude, latitude = _TO_WGS84(point.x, point.y)
            cells.append(
                GridCell(
                    id=f"uk{spacing_km:02d}_e{int(x0)}_n{int(y0)}",
                    name=f"UK grid {len(cells) + 1}",
                    latitude=float(latitude),
                    longitude=float(longitude),
                ).as_manifest_item()
            )
    if not cells:
        raise ValueError("land mask does not intersect the requested grid")
    if len(cells) > GRID_MAX_CELLS:
        raise ValueError(f"grid has {len(cells)} cells; maximum is {GRID_MAX_CELLS}")
    return tuple(cells)


def load_grid_manifest(path: Path) -> tuple[ClimateLocationSpec, ...]:
    """Load a grid manifest without the named-location feature's 500-cell cap."""

    try:
        with Path(path).open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read climate grid manifest {path}") from exc
    if isinstance(payload, Mapping):
        payload = payload.get("cells")
    if not isinstance(payload, list) or not payload:
        raise ValueError("climate grid manifest must contain a non-empty cells list")
    if len(payload) > GRID_MAX_CELLS:
        raise ValueError(f"climate grid manifest supports at most {GRID_MAX_CELLS} cells")
    try:
        specs = tuple(ClimateLocationSpec.model_validate(item) for item in payload)
    except ValueError as exc:
        raise ValueError(f"invalid climate grid manifest: {exc}") from exc
    ids = [spec.id for spec in specs]
    if len(ids) != len(set(ids)):
        raise ValueError("climate grid cell ids must be unique")
    return specs


def _grid_specs(
    locations: Iterable[ClimateLocationSpec | Mapping[str, Any]] | Path | str,
) -> tuple[ClimateLocationSpec, ...]:
    if isinstance(locations, (Path, str)):
        return load_grid_manifest(Path(locations))
    return tuple(_location_spec(location) for location in locations)


def write_grid_manifest(cells: Iterable[Mapping[str, Any]], path: Path) -> Path:
    """Atomically write a strict JSON grid manifest."""

    normalized = [
        ClimateLocationSpec.model_validate(cell).model_dump(mode="json") for cell in cells
    ]
    if not normalized or len(normalized) > GRID_MAX_CELLS:
        raise ValueError("grid manifest must contain between 1 and 10000 cells")
    if len({cell["id"] for cell in normalized}) != len(normalized):
        raise ValueError("climate grid cell ids must be unique")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = stream.name
            json.dump(normalized, stream, ensure_ascii=False, indent=2)
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
    return path


class ClimateGridImporter(ClimateImporter):
    """Open-Meteo adapter with an explicit weighted-call ceiling.

    The estimate of nine weighted calls per 126-day seasonal request is a
    deliberately conservative planning value.  Cached responses consume no
    budget, and an interrupted run can be resumed with the same cache directory.
    """

    def __init__(
        self,
        cache_dir: Path = Path("data/climate-grid"),
        *,
        max_weighted_calls: int | None = None,
        weighted_calls_per_request: int = DEFAULT_WEIGHTED_CALLS_PER_REQUEST,
        **kwargs: Any,
    ) -> None:
        if max_weighted_calls is not None and (
            type(max_weighted_calls) is not int or max_weighted_calls <= 0
        ):
            raise ValueError("max_weighted_calls must be a positive integer")
        if type(weighted_calls_per_request) is not int or weighted_calls_per_request <= 0:
            raise ValueError("weighted_calls_per_request must be a positive integer")
        # Grid acquisition defaults to one attempt: the weighted budget is a
        # hard ceiling, so retries must be explicitly budgeted by the caller.
        kwargs.setdefault("retries", 1)
        kwargs.setdefault("request_interval_seconds", 7.0)
        if kwargs.get("fetcher") is None:
            minimum_interval = (
                weighted_calls_per_request * kwargs["retries"] * 3600 / HOURLY_WEIGHTED_CALL_LIMIT
            )
            if kwargs["request_interval_seconds"] < minimum_interval:
                raise ValueError(
                    "request interval is too short for the weighted hourly quota "
                    f"({minimum_interval:.2f} seconds minimum)"
                )
        super().__init__(cache_dir=cache_dir, **kwargs)
        self.max_weighted_calls = max_weighted_calls
        self.weighted_calls_per_request = weighted_calls_per_request
        self.weighted_calls = 0

    def estimate_weighted_calls(
        self,
        locations: Iterable[ClimateLocationSpec | Mapping[str, Any]] | Path | str,
        end_year: int,
        *,
        include_cached: bool = False,
    ) -> dict[str, int]:
        """Estimate missing requests and weighted calls without network access."""

        _validate_end_year(end_year)
        specs = _grid_specs(locations)
        years = range(end_year - 24, end_year + 1)
        cached = 0
        missing = 0
        for spec in specs:
            for year in years:
                if self._read_cache(spec.id, spec.coordinate, year) is None:
                    missing += 1
                else:
                    cached += 1
        requests_count = missing if not include_cached else missing + cached
        return {
            "locations": len(specs),
            "years_per_location": 25,
            "cached_requests": cached,
            "missing_requests": missing,
            "requests": requests_count,
            "weighted_calls": requests_count * self.weighted_calls_per_request * self.retries,
        }

    def fetch_limited(
        self,
        locations: Iterable[ClimateLocationSpec | Mapping[str, Any]] | Path | str,
        end_year: int,
    ) -> dict[str, dict[int, dict[str, Any]]]:
        """Fetch missing annual batches until the weighted budget is exhausted."""

        histories: dict[str, dict[int, dict[str, Any]]] = {}
        for location_id, year, payload in self.iter_limited(locations, end_year):
            histories.setdefault(location_id, {})[year] = payload
        return histories

    def iter_limited(
        self,
        locations: Iterable[ClimateLocationSpec | Mapping[str, Any]] | Path | str,
        end_year: int,
    ) -> Iterator[tuple[str, int, dict[str, Any]]]:
        """Yield cached/fetched annual payloads without retaining the grid in memory."""

        if self.max_weighted_calls is None and self.fetcher is None:
            raise ValueError("network acquisition requires max_weighted_calls")
        _validate_end_year(end_year)
        specs = _grid_specs(locations)
        for spec in specs:
            for year in range(end_year - 24, end_year + 1):
                cached = self._read_cache(spec.id, spec.coordinate, year)
                if cached is not None:
                    yield spec.id, year, cached
                    continue
                request_budget = self.weighted_calls_per_request * self.retries
                next_total = self.weighted_calls + request_budget
                if self.max_weighted_calls is not None and next_total > self.max_weighted_calls:
                    raise ClimateGridBudgetExceeded(
                        f"weighted call budget {self.max_weighted_calls} would be exceeded "
                        f"by {spec.id}/{year} (used {self.weighted_calls})"
                    )
                # Reserve before calling so a failed/retried request cannot make
                # the process exceed the declared ceiling.
                self.weighted_calls = next_total
                yield spec.id, year, self.fetch_year(spec.id, spec.coordinate, year)

    fetch_histories = fetch_limited


def _validate_mask_source(value: Mapping[str, Any]) -> dict[str, str]:
    if set(value) != {"name", "url", "attribution"}:
        raise ValueError("mask_source must contain name, url, and attribution")
    result = {key: value[key] for key in ("name", "url", "attribution")}
    if not all(isinstance(item, str) and item.strip() for item in result.values()):
        raise ValueError("mask_source fields must be nonblank strings")
    parsed = urlparse(result["url"])
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("mask_source url must be an absolute HTTP(S) URL")
    return result


def _canonical_revision(
    metadata: Mapping[str, Any],
    cells: Iterable[Mapping[str, Any]],
    distributions: Iterable[Mapping[str, Any]],
) -> str:
    """Hash canonical rows incrementally so a full grid is never materialized."""

    digest = hashlib.sha256()

    def add(tag: str, value: Any) -> None:
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        digest.update(tag.encode("ascii"))
        digest.update(encoded.encode("utf-8"))
        digest.update(b"\n")

    add(
        "metadata\0",
        {key: value for key, value in metadata.items() if key not in {"revision", "built_at"}},
    )
    for cell in cells:
        add("cell\0", dict(cell))
    for distribution in distributions:
        add("distribution\0", dict(distribution))
    return digest.hexdigest()[:16]


def _create_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE cells(
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            source_lat REAL,
            source_lon REAL,
            elevation REAL
        );
        CREATE TABLE distributions(
            cell_id TEXT NOT NULL,
            week_id INTEGER NOT NULL,
            metric TEXT NOT NULL,
            period_years INTEGER NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY(cell_id,week_id,metric,period_years)
        );
        """
    )


def build_climate_grid(
    locations: Iterable[ClimateLocationSpec | Mapping[str, Any]] | Path | str,
    mask: BaseGeometry | Mapping[str, Any] | Path | str,
    cache_dir: Path,
    end_year: int,
    output_path: Path,
    *,
    source: ClimateSource | Mapping[str, Any] | None = None,
    mask_source: Mapping[str, Any] | None = None,
    built_at: datetime | str | None = None,
    importer: ClimateImporter | None = None,
    endpoint: str | None = None,
    mask_simplification_metres: float = 150,
) -> Path:
    """Stream cached one-cell artifacts into a validated SQLite grid.

    ``locations`` may be a small custom pilot manifest or the full generated
    manifest.  The function never calls the network; acquisition is explicit in
    :class:`ClimateGridImporter.fetch_limited`.
    """

    _validate_end_year(end_year)
    specs = _grid_specs(locations)
    if not specs or len(specs) > GRID_MAX_CELLS:
        raise ValueError(f"grid must contain between 1 and {GRID_MAX_CELLS} cells")
    ids = [spec.id for spec in specs]
    if len(ids) != len(set(ids)):
        raise ValueError("climate grid cell ids must be unique")
    geometry = _as_geometry(mask)
    source_model = (
        source
        if isinstance(source, ClimateSource)
        else ClimateSource.model_validate(DEFAULT_SOURCE if source is None else source)
    )
    provenance = _validate_mask_source(DEFAULT_MASK_SOURCE if mask_source is None else mask_source)
    if built_at is None:
        timestamp = datetime.now(UTC)
    elif isinstance(built_at, datetime):
        timestamp = built_at
    else:
        timestamp = _parse_timestamp(built_at)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("built_at must include a timezone")
    timestamp = timestamp.astimezone(UTC)
    display_mask = _display_mask(geometry, mask_simplification_metres)
    metadata = {
        "schema_version": CLIMATE_SCHEMA_VERSION,
        "revision": "building",
        "end_year": end_year,
        "source": source_model.model_dump(mode="json"),
        "spacing_km": GRID_SPACING_KM,
        "grid_crs": f"EPSG:{GRID_EPSG}",
        "grid_origin_m": [GRID_ORIGIN_X, GRID_ORIGIN_Y],
        "mask_simplification_metres": mask_simplification_metres,
        "mask": display_mask,
        "mask_source": provenance,
        "built_at": timestamp.isoformat(),
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    climate_importer = importer or ClimateImporter(
        cache_dir=Path(cache_dir), endpoint=endpoint or OPEN_METEO_ARCHIVE_URL
    )
    try:
        with tempfile.NamedTemporaryFile(
            dir=output_path.parent, prefix=f".{output_path.name}.", suffix=".tmp", delete=False
        ) as stream:
            temporary_path = stream.name
        with sqlite3.connect(temporary_path) as db:
            db.row_factory = sqlite3.Row
            _create_schema(db)
            db.executemany(
                "INSERT INTO metadata(key,value) VALUES (?,?)",
                [
                    (key, json.dumps(value, ensure_ascii=True, separators=(",", ":")))
                    for key, value in metadata.items()
                ],
            )
            for spec in specs:
                histories = climate_importer.load_cached_histories((spec,), end_year)
                from pound_build.ingest.climate import build_climate

                artifact = build_climate((spec,), end_year, histories, source=source_model)
                location = artifact.locations[0]
                db.execute(
                    "INSERT INTO cells(id,name,lat,lon,source_lat,source_lon,elevation) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        location.id,
                        location.name,
                        location.coordinate.lat,
                        location.coordinate.lon,
                        location.source_coordinate.lat,
                        location.source_coordinate.lon,
                        location.elevation,
                    ),
                )
                for week in location.weeks:
                    for metric_name, periods in (("high", week.high), ("low", week.low)):
                        for period_years, distribution in periods.items():
                            payload = json.dumps(
                                distribution.model_dump(mode="json"),
                                ensure_ascii=True,
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                            db.execute(
                                "INSERT INTO distributions("
                                "cell_id,week_id,metric,period_years,payload) "
                                "VALUES (?,?,?,?,?)",
                                (
                                    location.id,
                                    week.week_id,
                                    metric_name,
                                    int(period_years),
                                    payload,
                                ),
                            )
            cells = [dict(row) for row in db.execute("SELECT * FROM cells ORDER BY id")]
            distribution_count = db.execute("SELECT count(*) FROM distributions").fetchone()[0]
            if distribution_count != len(specs) * 72:
                raise ValueError("each grid cell must have exactly 72 distributions")
            distributions = db.execute(
                "SELECT cell_id,week_id,metric,period_years,payload FROM distributions "
                "ORDER BY cell_id,week_id,metric,period_years"
            )
            metadata["revision"] = _canonical_revision(metadata, cells, distributions)
            db.execute(
                "UPDATE metadata SET value=? WHERE key='revision'",
                (json.dumps(metadata["revision"]),),
            )
            db.commit()
        os.replace(temporary_path, output_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
    return output_path


build_grid = build_climate_grid


def download_land_mask(url: str, output_path: Path, *, timeout_seconds: float = 60) -> Path:
    """Download and validate one public GeoJSON mask, atomically."""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("mask URL must be an absolute HTTP(S) URL")
    response = requests.get(url, timeout=timeout_seconds)
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError("mask response is not JSON") from exc
    _as_geometry(payload)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = stream.name
            json.dump(payload, stream, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output_path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
    return output_path


__all__ = [
    "ClimateGridBudgetExceeded",
    "ClimateGridImporter",
    "DEFAULT_MASK_SOURCE",
    "DEFAULT_WEIGHTED_CALLS_PER_REQUEST",
    "GridCell",
    "GRID_EPSG",
    "GRID_MAX_CELLS",
    "GRID_MIN_END_YEAR",
    "GRID_ORIGIN_X",
    "GRID_ORIGIN_Y",
    "GRID_SPACING_KM",
    "GRID_SPACING_METRES",
    "HOURLY_WEIGHTED_CALL_LIMIT",
    "build_climate_grid",
    "build_grid",
    "download_land_mask",
    "generate_grid_cells",
    "load_grid_manifest",
    "load_land_mask",
    "write_grid_manifest",
]
