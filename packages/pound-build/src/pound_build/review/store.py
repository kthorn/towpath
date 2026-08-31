"""Atomic persistence for the standalone candidate review document."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import get_args

from pydantic import ValidationError

from pound_build.review.models import ReviewDecision, ReviewDocument


class ReviewFileError(ValueError):
    """A review file is missing, malformed, or violates its JSON contract."""


def load_document(path: Path) -> ReviewDocument:
    """Load and validate a review document, normalizing file errors."""
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ReviewDocument.model_validate(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValidationError) as exc:
        raise ReviewFileError(f"Could not load review file {path}: {exc}") from exc


def write_document(path: Path, document: ReviewDocument) -> None:
    """Write a validated document atomically beside its destination."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            json.dump(document.model_dump(mode="json"), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


class ReviewStore:
    """Load, update, and atomically persist one review document."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.document = load_document(self.path)
        # ponytail: process-local review server; add an interprocess lock for multi-process serving.
        self._write_lock = Lock()

    def save_decision(self, identity: str, decision: ReviewDecision) -> ReviewDocument:
        """Persist a decision and review timestamp for one known identity."""
        if decision not in get_args(ReviewDecision):
            raise ValueError(f"invalid review decision: {decision!r}")

        with self._write_lock:
            if not any(record.identity == identity for record in self.document.records):
                raise ValueError(f"unknown review identity: {identity}")

            reviewed_at = datetime.now(UTC).isoformat()
            records = [
                record.model_copy(update={"decision": decision, "reviewed_at": reviewed_at})
                if record.identity == identity
                else record
                for record in self.document.records
            ]
            updated = self.document.model_copy(update={"records": records})
            write_document(self.path, updated)
            self.document = updated
            return updated
