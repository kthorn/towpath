"""Strict JSON models for the standalone candidate review document."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pound.catalog.metadata import normalize_external_link

ReviewDecision = Literal["vacation_hire", "not_vacation_hire", "uncertain"]


def _normalized_url(value: str) -> str:
    normalized = normalize_external_link("Review URL", value)
    if normalized is None:
        raise ValueError("must be an absolute HTTP(S) URL")
    return normalized.url


class ReviewLink(BaseModel):
    """A label and URL retained for a review candidate."""

    model_config = ConfigDict(extra="forbid", strict=True)

    label: str
    url: str

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str) -> str:
        return _normalized_url(value)


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

    @field_validator("website_urls")
    @classmethod
    def normalize_website_urls(cls, values: list[str]) -> list[str]:
        return [_normalized_url(value) for value in values]

    @field_validator("osm_url")
    @classmethod
    def normalize_osm_url(cls, value: str) -> str:
        return _normalized_url(value)


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
