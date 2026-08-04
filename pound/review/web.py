"""Local Flask reviewer for ranked boat-hire candidates."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import NoReturn, cast, get_args
from urllib.parse import urlencode

from flask import Flask, abort, redirect, render_template, request, url_for

from pound.review.models import ReviewDecision, ReviewRecord
from pound.review.store import ReviewStore

FILTERS = ("all", "unreviewed", "vacation_hire", "not_vacation_hire", "uncertain")
_DECISIONS = get_args(ReviewDecision)


def _review_url(filter_name: str, identity: str | None = None) -> str:
    query = {"filter": filter_name}
    if identity is not None:
        query["identity"] = identity
    return f"{url_for('index')}?{urlencode(query)}"


def _filter_records(records: list[ReviewRecord], filter_name: str) -> list[ReviewRecord]:
    if filter_name == "all":
        return records
    if filter_name == "unreviewed":
        return [record for record in records if record.decision is None]
    return [record for record in records if record.decision == filter_name]


def _bad_request(message: str) -> NoReturn:
    abort(400, description=message)
    raise AssertionError("unreachable")


def create_app(review_path: Path) -> Flask:
    """Create a reviewer app backed by one atomically persisted review file."""
    app = Flask(__name__)
    csrf_token = secrets.token_urlsafe(32)
    store = ReviewStore(Path(review_path))
    app.extensions["boat_hire_review_store"] = store
    app.jinja_env.globals["review_url"] = _review_url

    @app.get("/")
    def index():
        filter_name = request.args.get("filter", "all")
        if filter_name not in FILTERS:
            _bad_request(f"Unknown review filter: {filter_name}")

        records = _filter_records(store.document.records, filter_name)
        identity = request.args.get("identity")
        record = None
        position = None
        previous = None
        next_record = None
        if records:
            if identity is None:
                position = 0
            else:
                position = next(
                    (
                        index
                        for index, candidate in enumerate(records)
                        if candidate.identity == identity
                    ),
                    None,
                )
                if position is None:
                    _bad_request(f"Unknown review identity: {identity}")
            assert position is not None
            record = records[position]
            previous = records[position - 1] if position > 0 else None
            next_record = records[position + 1] if position + 1 < len(records) else None
        elif identity is not None:
            _bad_request(f"Unknown review identity: {identity}")

        return render_template(
            "review.html",
            record=record,
            filter_name=filter_name,
            filters=FILTERS,
            position=None if position is None else position + 1,
            total=len(records),
            previous=previous,
            next_record=next_record,
            csrf_token=csrf_token,
        )

    @app.post("/decision")
    def decision():
        if request.form.get("csrf_token") != csrf_token:
            _bad_request("Invalid CSRF token")

        identity = request.form.get("identity")
        decision_value = request.form.get("decision")
        filter_name = request.form.get("filter", "all")
        if filter_name not in FILTERS:
            _bad_request(f"Unknown review filter: {filter_name}")
        if not identity:
            _bad_request("Missing review identity")
        if decision_value not in _DECISIONS:
            _bad_request(f"Invalid review decision: {decision_value}")

        try:
            store.save_decision(identity, cast(ReviewDecision, decision_value))
        except ValueError as exc:
            _bad_request(str(exc))
        ranked = sorted(store.document.records, key=lambda candidate: candidate.rank)
        selected_index = next(
            (index for index, candidate in enumerate(ranked) if candidate.identity == identity),
            None,
        )
        if selected_index is None:
            _bad_request(f"Unknown review identity: {identity}")

        assert selected_index is not None
        candidates = ranked[selected_index + 1 :] + ranked[: selected_index + 1]
        next_unreviewed = next(
            (candidate for candidate in candidates if candidate.decision is None),
            None,
        )
        if next_unreviewed is None:
            return redirect(_review_url("unreviewed"))
        return redirect(_review_url("unreviewed", next_unreviewed.identity))

    return app


__all__ = ["create_app"]
