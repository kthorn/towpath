"""Configuration for the Pound web application."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WebSettings:
    """Runtime settings for artifact loading and candidate selection."""

    artifact_path: Path
    static_dir: Path
    candidate_pool_size: int = 20
    google_destination_limit: int = 10
    minimum_candidate_spacing_m: float = 250.0

    def __post_init__(self) -> None:
        if self.candidate_pool_size <= 0:
            raise ValueError("candidate_pool_size must be greater than zero")
        if self.google_destination_limit <= 0:
            raise ValueError("google_destination_limit must be greater than zero")
        if self.minimum_candidate_spacing_m < 0:
            raise ValueError("minimum_candidate_spacing_m must be nonnegative")

    @classmethod
    def from_env(cls) -> "WebSettings":
        """Build settings from the process environment."""

        artifact_path = os.environ.get("POUND_ARTIFACT_PATH")
        if not artifact_path:
            raise RuntimeError("POUND_ARTIFACT_PATH is required")

        return cls(
            artifact_path=Path(artifact_path),
            static_dir=Path(os.environ.get("POUND_STATIC_DIR", "web/dist")),
            candidate_pool_size=int(os.environ.get("POUND_CANDIDATE_POOL_SIZE", "20")),
            google_destination_limit=int(
                os.environ.get("POUND_GOOGLE_DESTINATION_LIMIT", "10")
            ),
            minimum_candidate_spacing_m=float(
                os.environ.get("POUND_MINIMUM_CANDIDATE_SPACING_M", "250.0")
            ),
        )
