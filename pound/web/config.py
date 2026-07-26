"""Configuration for the Pound web application."""

import math
import os
from dataclasses import dataclass
from pathlib import Path

from pound.catalog.manifest import MAX_CATALOG_KINDS, MAX_CATALOG_RADIUS_M
from pound.catalog.spatial import MAX_CATALOG_QUERY_WORK, MAX_CATALOG_VIEWPORT_SPAN_DEGREES
from pound.schemas import MAX_CATALOG_ROUTE_COORDINATES


@dataclass(frozen=True)
class WebSettings:
    """Runtime settings for routing, catalog loading, and bounded queries."""

    artifact_path: Path
    static_dir: Path
    candidate_pool_size: int = 20
    google_destination_limit: int = 10
    minimum_candidate_spacing_m: float = 250.0
    catalog_path: Path | None = None
    catalog_max_kinds: int = MAX_CATALOG_KINDS
    catalog_max_viewport_span_deg: float = MAX_CATALOG_VIEWPORT_SPAN_DEGREES
    catalog_max_radius_m: float = MAX_CATALOG_RADIUS_M
    catalog_max_route_vertices: int = MAX_CATALOG_ROUTE_COORDINATES
    catalog_query_work_budget: int = MAX_CATALOG_QUERY_WORK

    def __post_init__(self) -> None:
        if self.candidate_pool_size <= 0:
            raise ValueError("candidate_pool_size must be greater than zero")
        if self.google_destination_limit <= 0:
            raise ValueError("google_destination_limit must be greater than zero")
        if self.minimum_candidate_spacing_m < 0:
            raise ValueError("minimum_candidate_spacing_m must be nonnegative")
        if not 0 < self.catalog_max_kinds <= MAX_CATALOG_KINDS:
            raise ValueError(f"catalog_max_kinds must be from 1 through {MAX_CATALOG_KINDS}")
        if not math.isfinite(self.catalog_max_viewport_span_deg) or not (
            0 < self.catalog_max_viewport_span_deg <= MAX_CATALOG_VIEWPORT_SPAN_DEGREES
        ):
            raise ValueError(
                "catalog_max_viewport_span_deg must be finite and from 0 through "
                f"{MAX_CATALOG_VIEWPORT_SPAN_DEGREES:g}"
            )
        if not math.isfinite(self.catalog_max_radius_m) or not (
            0 <= self.catalog_max_radius_m <= MAX_CATALOG_RADIUS_M
        ):
            raise ValueError(
                f"catalog_max_radius_m must be from 0 through {MAX_CATALOG_RADIUS_M:g}"
            )
        if not 0 < self.catalog_max_route_vertices <= MAX_CATALOG_ROUTE_COORDINATES:
            raise ValueError(
                "catalog_max_route_vertices must be positive and within the geometry ceiling"
            )
        if not 0 < self.catalog_query_work_budget <= MAX_CATALOG_QUERY_WORK:
            raise ValueError(
                f"catalog_query_work_budget must be from 1 through {MAX_CATALOG_QUERY_WORK}"
            )

    @classmethod
    def from_env(cls) -> "WebSettings":
        """Build settings from the process environment."""

        artifact_path = os.environ.get("POUND_ARTIFACT_PATH")
        if not artifact_path:
            raise RuntimeError("POUND_ARTIFACT_PATH is required")

        catalog_path = os.environ.get("POUND_CATALOG_PATH")
        return cls(
            artifact_path=Path(artifact_path),
            static_dir=Path(os.environ.get("POUND_STATIC_DIR", "web/dist")),
            catalog_path=Path(catalog_path) if catalog_path else None,
            candidate_pool_size=int(os.environ.get("POUND_CANDIDATE_POOL_SIZE", "20")),
            google_destination_limit=int(os.environ.get("POUND_GOOGLE_DESTINATION_LIMIT", "10")),
            minimum_candidate_spacing_m=float(
                os.environ.get("POUND_MINIMUM_CANDIDATE_SPACING_M", "250.0")
            ),
            catalog_max_kinds=int(os.environ.get("POUND_CATALOG_MAX_KINDS", "16")),
            catalog_max_viewport_span_deg=float(
                os.environ.get("POUND_CATALOG_MAX_VIEWPORT_SPAN_DEG", "10.0")
            ),
            catalog_max_radius_m=float(os.environ.get("POUND_CATALOG_MAX_RADIUS_M", "2000.0")),
            catalog_max_route_vertices=int(
                os.environ.get("POUND_CATALOG_MAX_ROUTE_VERTICES", "10000")
            ),
            catalog_query_work_budget=int(
                os.environ.get("POUND_CATALOG_QUERY_WORK_BUDGET", "100000")
            ),
        )
