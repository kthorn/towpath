"""Place resolution and browser task HTTP bridge; no provider payloads in model results."""

import hashlib
import json
import logging
import secrets
import time
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pound.catalog.resolve import GB_BOUNDS, in_scope, resolve_place
from pound.schemas import Coordinate, ResolvePlaceRequest
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, ValidationError

from pound_web.api import CanalCandidatesRequest, canal_candidates
from pound_web.place_sessions import PlaceSession, PlaceSessionError, PlaceSessions

router = APIRouter(prefix="/api/place-sessions")
_LOG = logging.getLogger(__name__)


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SelectionCoordinate(StrictBody):
    lat: FiniteFloat = Field(ge=-90, le=90)
    lon: FiniteFloat = Field(ge=-180, le=180)


class Selection(StrictBody):
    run_id: str = Field(max_length=128)
    option_ref: str = Field(min_length=1, max_length=128)
    coordinate: SelectionCoordinate | None = None


class ManualSelection(StrictBody):
    run_id: str | None = Field(default=None, max_length=128)
    coordinate: SelectionCoordinate


class Fallback(StrictBody):
    run_id: str = Field(max_length=128)


class TransferState(StrictBody):
    candidate_id: str = Field(max_length=256)
    outward: Literal["available", "unavailable"]
    return_state: Literal["available", "unavailable"] = Field(alias="return")


class BrowserResult(StrictBody):
    run_id: str = Field(max_length=128)
    digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    status: Literal["matches", "not_found", "unavailable", "incomplete", "complete"]
    option_refs: list[str] = Field(default_factory=list, max_length=5)
    transfers: list[TransferState] = Field(default_factory=list, max_length=5)


async def body[BodyModel: BaseModel](request: Request, model: type[BodyModel]) -> BodyModel:
    """Bound streamed input before JSON parsing; never echo rejected provider content."""
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > 16_384:
            raise HTTPException(
                413,
                detail={
                    "code": "payload_limit",
                    "message": "Place request is too large.",
                    "fields": [],
                },
            )
    try:
        return model.model_validate_json(bytes(chunks))
    except (ValidationError, ValueError):
        raise HTTPException(
            422,
            detail={
                "code": "invalid_place_request",
                "message": "Invalid place request.",
                "fields": [],
            },
        ) from None


def owned(request: Request, session_id: str) -> tuple[PlaceSessions, PlaceSession]:
    registry = request.app.state.place_sessions
    authorization = request.headers.get("authorization", "")
    token = authorization[7:] if authorization.startswith("Bearer ") else ""
    return registry, registry.get(session_id, token)


def current(request: Request, session: PlaceSession, run_id: str) -> None:
    request.app.state.place_sessions.require_active(session)
    if session.run_id != run_id or session.revision != request.app.state.artifact_revision:
        raise PlaceSessionError("stale_selection")


def snapshot(session: PlaceSession) -> dict[str, Any]:
    return {"run_id": session.run_id, **session.result}


def fallback(registry: PlaceSessions, session: PlaceSession) -> dict[str, Any]:
    if not session.query or session.osm is None:
        raise PlaceSessionError("name_required", 422)
    _LOG.info("place_fallback", extra={"reason": session.osm.status if session.osm else "manual"})
    session.source = "google"
    session.options = {}
    session.coordinate_bindings = {}
    task = registry.issue(session, "search", {"query": session.query, "bounds": GB_BOUNDS})
    session.result = {"status": "pending", "task": task}
    return snapshot(session)


@router.post("")
def create_session(request: Request) -> dict[str, Any]:
    session = request.app.state.place_sessions.create()
    return {"session_id": session.session_id, "token": session.token, "expires_in": 600}


@router.post("/{session_id}/resolve")
async def resolve(session_id: str, request: Request) -> dict[str, Any]:
    query = await body(request, ResolvePlaceRequest)
    registry, session = owned(request, session_id)
    with registry.lock:
        registry.start(session, request.app.state.artifact_revision)
        session.query = query.query
        started = time.perf_counter()
        session.osm = resolve_place(
            query,
            index=request.app.state.place_name_index,
            max_work=min(100_000, request.app.state.settings.catalog_query_work_budget),
        )
        _LOG.info(
            "place_resolution",
            extra={
                "source": "osm",
                "outcome": session.osm.status,
                "work_used": session.osm.work_used,
                "elapsed_ms": (time.perf_counter() - started) * 1000,
            },
        )
        session.source = "osm"
        session.options = {item.option_ref: item for item in session.osm.options}
        session.result = {"status": session.osm.status}
        if session.osm.status in {"not_found", "unavailable"}:
            fallback(registry, session)
        return {**snapshot(session), "osm": session.osm.model_dump()}


@router.post("/{session_id}/google")
async def google(session_id: str, request: Request) -> dict[str, Any]:
    value = await body(request, Fallback)
    registry, session = owned(request, session_id)
    with registry.lock:
        current(request, session, value.run_id)
        return fallback(registry, session)


@router.get("/{session_id}/events")
def events(session_id: str, request: Request) -> Response:
    registry, session = owned(request, session_id)
    with registry.lock:
        current(request, session, session.run_id)
        task = session.task
        if task is None or task["done"]:
            return Response(
                "", media_type="text/event-stream", headers={"Cache-Control": "no-store"}
            )
        registry.validate(
            session, task["event"]["task_id"], session.run_id, task["event"]["digest"]
        )
        event = task["event"]
        return Response(
            f"event: browser_task\nid: {event['task_id']}\ndata: " + json.dumps(event) + "\n\n",
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store"},
        )


@router.post("/{session_id}/select")
async def select(session_id: str, request: Request) -> dict[str, Any]:
    value = await body(request, Selection)
    registry, session = owned(request, session_id)
    with registry.lock:
        current(request, session, value.run_id)
        if value.option_ref not in session.options:
            raise PlaceSessionError("unknown_option", 400)
        if session.source == "osm":
            if value.coordinate is not None:
                raise PlaceSessionError("coordinate_override", 400)
            coordinate = session.options[value.option_ref].coordinate
        else:
            coordinate = value.coordinate
            if coordinate is None or not in_scope(coordinate.lat, coordinate.lon):
                raise PlaceSessionError("invalid_coordinate", 400)
        return prepare_walking(registry, session, value.option_ref, coordinate, request)


def prepare_walking(
    registry: PlaceSessions,
    session: PlaceSession,
    option_ref: str,
    coordinate: SelectionCoordinate | Coordinate,
    request: Request,
) -> dict[str, Any]:
    digest = hashlib.sha256(json.dumps([coordinate.lat, coordinate.lon]).encode()).hexdigest()
    previous = session.coordinate_bindings.get(option_ref)
    if previous is not None and previous != digest:
        raise PlaceSessionError("coordinate_binding_mismatch")
    session.coordinate_bindings[option_ref] = digest
    # Same validator, candidate query and configured ceilings as manual endpoint selection.
    candidates = canal_candidates(
        CanalCandidatesRequest(lat=coordinate.lat, lon=coordinate.lon), request
    ).candidates[:5]
    if not candidates:
        session.task = None
        session.result = {"status": "unavailable", "reason": "no_access_candidates"}
        return snapshot(session)
    task = registry.issue(
        session,
        "walking",
        {
            "option_ref": option_ref,
            "mode": "WALK",
            "access_basis": "geometric_unconfirmed",
            "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
        },
    )
    # Google coordinates are processed above, never stored in session/task payloads.
    session.result = {"status": "pending", "task": task}
    return snapshot(session)


@router.post("/{session_id}/manual")
async def manual(session_id: str, request: Request) -> dict[str, Any]:
    value = await body(request, ManualSelection)
    registry, session = owned(request, session_id)
    with registry.lock:
        if value.run_id is None:
            registry.start(session, request.app.state.artifact_revision)
        else:
            current(request, session, value.run_id)
        if not in_scope(value.coordinate.lat, value.coordinate.lon):
            raise PlaceSessionError("invalid_coordinate", 400)
        option_ref = secrets.token_urlsafe(18)
        session.source = "manual"
        session.options = {option_ref: None}
        return prepare_walking(registry, session, option_ref, value.coordinate, request)


@router.post("/{session_id}/tasks/{task_id}/result")
async def complete(session_id: str, task_id: str, request: Request) -> dict[str, Any]:
    value = await body(request, BrowserResult)
    registry, session = owned(request, session_id)
    with registry.lock:
        current(request, session, value.run_id)
        task = registry.validate(session, task_id, value.run_id, value.digest)
        if task["kind"] == "search":
            refs = value.option_refs
            if (
                value.transfers
                or value.status == "complete"
                or len(set(refs)) != len(refs)
                or any(
                    not 1 <= len(ref) <= 128
                    or not ref.isascii()
                    or not all(c.isalnum() or c in "-_" for c in ref)
                    for ref in refs
                )
                or (
                    bool(refs) != (value.status in {"matches", "incomplete"})
                    and value.status != "incomplete"
                )
            ):
                raise PlaceSessionError("invalid_browser_result", 422)
            session.options = dict.fromkeys(refs)
            result = {
                "status": "ambiguous" if value.status == "matches" else value.status,
                "option_refs": refs,
                "source_states": {"osm": session.osm.status, "google": value.status},
            }
            if value.status == "not_found" and session.osm.status == "unavailable":
                result["status"] = "unavailable"
        else:
            expected = {c["candidate_id"] for c in task["payload"]["candidates"]}
            received = [t.candidate_id for t in value.transfers]
            if (
                value.option_refs
                or value.status not in {"complete", "unavailable", "incomplete"}
                or len(set(received)) != len(received)
                or (value.status == "complete" and set(received) != expected)
                or set(received) - expected
            ):
                raise PlaceSessionError("invalid_browser_result", 422)
            result = {
                "status": value.status,
                "option_ref": task["payload"]["option_ref"],
                "access_basis": "geometric_unconfirmed",
                "transfers": [t.model_dump(by_alias=True) for t in value.transfers],
            }
        registry.complete(session, task_id, value.run_id, value.digest, result)
        _LOG.info(
            "place_browser_result",
            extra={
                "task_kind": task["kind"],
                "outcome": value.status,
                "unavailable_directions": sum(
                    (t.outward == "unavailable") + (t.return_state == "unavailable")
                    for t in value.transfers
                ),
            },
        )
        return snapshot(session)


@router.get("/{session_id}/result")
def result(session_id: str, request: Request) -> dict[str, Any]:
    registry, session = owned(request, session_id)
    with registry.lock:
        current(request, session, session.run_id)
        if session.task is not None and not session.task["done"]:
            task = session.task["event"]
            registry.validate(session, task["task_id"], session.run_id, task["digest"])
        return snapshot(session)


@router.delete("/{session_id}")
def cancel(session_id: str, request: Request) -> dict[str, Any]:
    registry, session = owned(request, session_id)
    with registry.lock:
        registry.require_active(session)
        del registry.sessions[session.session_id]
    return {"status": "cancelled"}
