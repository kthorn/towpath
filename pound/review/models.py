"""Strict JSON models for the standalone candidate review document."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ReviewDecision = Literal["vacation_hire", "not_vacation_hire", "uncertain"]


class ReviewLink(BaseModel):
    """A label and URL retained for a review candidate."""

    model_config = ConfigDict(extra="forbid", strict=True)

    label: str
    url: str


class ReviewRecord(BaseModel):
    """One ranked candidate and its human review state."""

    model_config = ConfigDict(extra="forbid", strict=True)

    identity: str
    osm_type: str
    osm_id: int
    kind: str
    name: str
    lat: float
    lon: float
    metadata: dict[str, Any]
    links: list[ReviewLink]
    website_urls: list[str]
    osm_url: str
    likelihood_score: int
    rank: int = Field(gt=0)
    likelihood_reasons: list[str]
    decision: ReviewDecision | None
    reviewed_at: str | None


class ReviewDocument(BaseModel):
    """The versioned, ranked review file persisted on disk."""

    model_config = ConfigDict(extra="forbid", strict=True)

    format_version: int
    source_artifact: str
    catalog_revision: str
    generated_at: str
    records: list[ReviewRecord]

    @model_validator(mode="after")
    def validate_invariants(self) -> ReviewDocument:
        if self.format_version != 1:
            raise ValueError("unsupported review format version")

        identities = [record.identity for record in self.records]
        if len(identities) != len(set(identities)):
            raise ValueError("review record identities must be unique")

        ranks = [record.rank for record in self.records]
        if len(ranks) != len(set(ranks)):
            raise ValueError("review record ranks must be unique")
        return self


__all__ = ["ReviewDecision", "ReviewDocument", "ReviewLink", "ReviewRecord"]
