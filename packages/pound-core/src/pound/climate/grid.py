"""Read-only, bounded access to an offline UK climate grid SQLite artifact."""

from __future__ import annotations

import json
import math
import sqlite3
from bisect import bisect_right
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from shapely.geometry import shape

from pound.climate.artifact import ClimateCoordinate, ClimateDistribution, ClimateSource
from pound.climate.calendar import week_label

GridView = Literal["high_median", "high_p90", "low_median", "low_p10", "high_exceedance"]
GRID_VIEWS = {"high_median", "high_p90", "low_median", "low_p10", "high_exceedance"}
MAX_GRID_CELLS = 10_000


class InvalidClimateGridError(ValueError):
    """A grid cannot safely serve historical statistics."""


class ClimateGrid:
    """Immutable local artifact; each query uses its own read-only connection.

    No shared connection crosses request threads. Replacing an artifact requires a
    restart so responses cannot mix a startup revision with subsequently changed data.
    """

    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        try:
            self._stamp = self._file_stamp()
            with closing(self._connect()) as db:
                if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("SQLite integrity check failed")
                self.metadata = {
                    k: json.loads(v) for k, v in db.execute("SELECT key,value FROM metadata")
                }
                m = self.metadata
                if m["schema_version"] != 1 or m["spacing_km"] != 10:
                    raise ValueError("unsupported grid schema or spacing")
                if type(m["end_year"]) is not int or not 1974 <= m["end_year"] <= 2200:
                    raise ValueError("invalid end year")
                if not isinstance(m["revision"], str) or not m["revision"].strip():
                    raise ValueError("missing revision")
                source = ClimateSource.model_validate(m["source"])
                if source.timezone != "Europe/London":
                    raise ValueError("grid daily timezone must be Europe/London")
                if not isinstance(m["built_at"], str):
                    raise ValueError("invalid build timestamp")
                if datetime.fromisoformat(m["built_at"].replace("Z", "+00:00")).utcoffset() is None:
                    raise ValueError("build timestamp requires timezone")
                if m["mask"]["type"] not in ("Polygon", "MultiPolygon"):
                    raise ValueError("land mask must be polygonal")
                mask = shape(m["mask"])
                if mask.is_empty or not mask.is_valid:
                    raise ValueError("invalid land mask")
                if not all(math.isfinite(v) for v in mask.bounds):
                    raise ValueError("invalid land mask bounds")
                west, south, east, north = mask.bounds
                if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
                    raise ValueError("land mask must use WGS84")
                provenance = m["mask_source"]
                if not all(
                    isinstance(provenance[k], str) and provenance[k].strip()
                    for k in ("name", "url", "attribution")
                ):
                    raise ValueError("missing mask provenance")
                url = urlparse(provenance["url"])
                if url.scheme not in {"http", "https"} or not url.netloc:
                    raise ValueError("mask provenance URL must be HTTP(S)")
                rows = db.execute(
                    "SELECT * FROM cells ORDER BY id LIMIT ?", (MAX_GRID_CELLS + 1,)
                ).fetchall()
                if not 1 <= len(rows) <= MAX_GRID_CELLS:
                    raise ValueError("grid cell count outside supported limit")
                self.cells = {}
                for row in rows:
                    cell = dict(row)
                    if not isinstance(cell["id"], str) or not cell["id"] or not cell["name"]:
                        raise ValueError("invalid cell identity")
                    ClimateCoordinate(lat=cell["lat"], lon=cell["lon"])
                    if cell["source_lat"] is not None or cell["source_lon"] is not None:
                        ClimateCoordinate(lat=cell["source_lat"], lon=cell["source_lon"])
                    if cell["elevation"] is not None and not math.isfinite(cell["elevation"]):
                        raise ValueError("invalid elevation")
                    self.cells[cell["id"]] = cell
                counts = dict(
                    db.execute("SELECT cell_id,count(*) FROM distributions GROUP BY cell_id")
                )
                if counts != dict.fromkeys(self.cells, 72):
                    raise ValueError("each cell requires all weeks, metrics and periods")
                invalid = db.execute(
                    "SELECT 1 FROM distributions WHERE week_id IS NULL OR metric IS NULL "
                    "OR period_years IS NULL OR typeof(week_id) != 'integer' "
                    "OR typeof(period_years) != 'integer' OR week_id NOT BETWEEN 0 "
                    "AND 17 OR metric NOT IN ('high','low') OR period_years "
                    "NOT IN (5,25) OR payload IS NULL LIMIT 1"
                ).fetchone()
                if invalid:
                    raise ValueError("invalid distribution keys")
                duplicates = db.execute(
                    "SELECT 1 FROM distributions GROUP BY cell_id,week_id,metric,period_years "
                    "HAVING count(*) != 1 LIMIT 1"
                ).fetchone()
                if duplicates:
                    raise ValueError("duplicate distribution keys")
        except Exception as exc:
            raise InvalidClimateGridError(f"Could not load climate grid: {exc}") from exc

    def _file_stamp(self) -> tuple[int, int, int]:
        stat = self.path.stat()
        return stat.st_ino, stat.st_size, stat.st_mtime_ns

    def _connect(self) -> sqlite3.Connection:
        if self._file_stamp() != self._stamp:
            raise InvalidClimateGridError("Climate grid changed; restart to load its revision")
        db = sqlite3.connect(self.path.as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            db.execute("PRAGMA schema_version").fetchone()
            if self._file_stamp() != self._stamp:
                raise InvalidClimateGridError("Climate grid changed while opening")
            db.row_factory = sqlite3.Row
            return db
        except Exception:
            db.close()
            raise

    @staticmethod
    def _week(week: int) -> None:
        if type(week) is not int or not 0 <= week < 18:
            raise ValueError("week_id must be between 0 and 17")

    def _distribution(self, payload: str, period: int) -> ClimateDistribution:
        try:
            if len(payload) > 20_000:
                raise ValueError("oversized distribution")
            d = ClimateDistribution.model_validate_json(payload)
            if d.end_year != self.metadata["end_year"] or d.start_year != d.end_year - period + 1:
                raise ValueError("distribution years differ from grid window")
            return d
        except (ValueError, TypeError) as exc:
            raise InvalidClimateGridError(f"Invalid grid distribution: {exc}") from exc

    def _common(self, week: int) -> dict:
        return {k: self.metadata[k] for k in ("revision", "end_year", "source")} | {
            "week_id": week,
            "week_label": week_label(week),
        }

    def surface(self, week: int, period: int, view: str, threshold: float = 30) -> dict:
        """Return one scalar per cell; exceedance is strictly greater than threshold."""
        self._week(week)
        if type(period) is not int or period not in (5, 25) or view not in GRID_VIEWS:
            raise ValueError("invalid grid period or view")
        if not math.isfinite(threshold) or not -20 <= threshold <= 50:
            raise ValueError("threshold must be between -20 and 50 Celsius")
        metric, statistic = view.split("_", 1)
        cells = []
        try:
            with closing(self._connect()) as db:
                rows = db.execute(
                    "SELECT cell_id,payload FROM distributions WHERE week_id=? "
                    "AND metric=? AND period_years=? ORDER BY cell_id",
                    (week, metric, period),
                )
                for row in rows:
                    cell = self.cells[row["cell_id"]]
                    d = self._distribution(row["payload"], period)
                    value = None
                    if d.available:
                        value = (
                            (len(d.samples) - bisect_right(d.samples, threshold)) / len(d.samples)
                            if statistic == "exceedance"
                            else getattr(d, statistic)
                        )
                    cells.append(
                        {
                            "id": cell["id"],
                            "coordinate": {"lat": cell["lat"], "lon": cell["lon"]},
                            "value": value,
                            "n_days": d.n_days,
                        }
                    )
        except (OSError, sqlite3.Error, KeyError) as exc:
            raise InvalidClimateGridError(f"Could not read climate grid: {exc}") from exc
        return self._common(week) | {
            "period_years": period,
            "view": view,
            "threshold_c": threshold if statistic == "exceedance" else None,
            "unit": "probability" if statistic == "exceedance" else "celsius",
            "spacing_km": self.metadata["spacing_km"],
            "mask": self.metadata["mask"],
            "mask_source": self.metadata["mask_source"],
            "cells": cells,
        }

    def detail(self, cell_id: str, week: int) -> dict | None:
        """Return the unsmoothed empirical samples for a single grid cell."""
        self._week(week)
        if cell_id not in self.cells:
            return None
        cell = self.cells[cell_id]
        data = self._common(week) | {
            "location": {
                "id": cell_id,
                "name": cell["name"],
                "coordinate": {"lat": cell["lat"], "lon": cell["lon"]},
                "source_coordinate": (
                    {"lat": cell["source_lat"], "lon": cell["source_lon"]}
                    if cell["source_lat"] is not None
                    else None
                ),
                "elevation": cell["elevation"],
            },
            "high": {},
            "low": {},
        }
        try:
            with closing(self._connect()) as db:
                for row in db.execute(
                    "SELECT metric,period_years,payload FROM distributions "
                    "WHERE cell_id=? AND week_id=?",
                    (cell_id, week),
                ):
                    d = self._distribution(row["payload"], row["period_years"])
                    data[row["metric"]][str(row["period_years"])] = d.model_dump(mode="json")
        except (OSError, sqlite3.Error) as exc:
            raise InvalidClimateGridError(f"Could not read climate grid: {exc}") from exc
        return data
