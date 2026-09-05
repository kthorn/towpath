"""Bounded ephemeral browser work; bearer ownership is independent of model references."""

import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any


class PlaceSessionError(ValueError):
    def __init__(self, code: str, status: int = 409) -> None:
        self.code, self.status = code, status
        super().__init__(code)


@dataclass
class PlaceSession:
    session_id: str
    token: str
    expires: float
    run_id: str = ""
    revision: str = ""
    provider_seconds: float = 0
    task: dict | None = None
    options: dict[str, Any] = field(default_factory=dict)
    coordinate_bindings: dict[str, str] = field(default_factory=dict)
    source: str = "osm"
    osm: Any = None
    query: str = ""
    counters: dict[str, int] = field(default_factory=dict)
    result: dict = field(default_factory=dict)


class PlaceSessions:
    """One-process short-lived task registry, with atomic transitions under its lock."""

    def __init__(self, *, clock=time.monotonic, capacity: int = 1024) -> None:
        self.clock = clock
        self.capacity = capacity
        self.sessions: dict[str, PlaceSession] = {}
        self.lock = threading.RLock()

    def create(self) -> PlaceSession:
        with self.lock:
            now = self.clock()
            self.sessions = {
                key: value for key, value in self.sessions.items() if value.expires > now
            }
            if len(self.sessions) >= self.capacity:
                raise PlaceSessionError("sessions_full", 503)
            session = PlaceSession(secrets.token_urlsafe(24), secrets.token_urlsafe(32), now + 600)
            self.sessions[session.session_id] = session
            return session

    def get(self, session_id: str, token: str) -> PlaceSession:
        with self.lock:
            session = self.sessions.get(session_id)
            if (
                session is None
                or not hmac.compare_digest(session.token.encode(), token.encode())
                or session.expires <= self.clock()
            ):
                if session is not None and session.expires <= self.clock():
                    del self.sessions[session_id]
                raise PlaceSessionError("session_unavailable", 401)
            return session

    def require_active(self, session: PlaceSession) -> None:
        if self.sessions.get(session.session_id) is not session or session.expires <= self.clock():
            raise PlaceSessionError("session_unavailable", 401)

    def start(self, session: PlaceSession, revision: str) -> None:
        self.require_active(session)
        if session.counters.get("resolve", 0) >= 20:
            raise PlaceSessionError("session_budget", 429)
        session.counters["resolve"] = session.counters.get("resolve", 0) + 1
        session.coordinate_bindings = {}
        session.run_id = secrets.token_urlsafe(18)
        session.revision = revision
        session.provider_seconds = 0
        session.task = None
        session.options = {}
        session.osm = None
        session.query = ""
        session.result = {}

    def retire(self, session: PlaceSession) -> None:
        task = session.task
        if task is not None and not task["done"]:
            session.provider_seconds += max(0, min(self.clock(), task["deadline"]) - task["issued"])
            task["done"] = True

    def issue(self, session: PlaceSession, kind: str, payload: dict) -> dict:
        self.require_active(session)
        now = self.clock()
        if now >= session.expires:
            raise PlaceSessionError("session_unavailable", 401)
        self.retire(session)
        remaining = 60 - session.provider_seconds
        if remaining <= 0:
            session.result = {"status": "incomplete", "reason": "operation_budget"}
            raise PlaceSessionError("operation_budget", 429)
        timeout = min(20, remaining, session.expires - now)
        units = len(payload.get("candidates", [])) * 2 if kind == "walking" else 1
        ceiling = 100 if kind == "walking" else 10
        used = session.counters.get(kind, 0)
        if used + units > ceiling:
            session.result = {"status": "incomplete", "reason": "session_budget"}
            raise PlaceSessionError("session_budget", 429)
        session.counters[kind] = used + units
        task = dict(
            task_id=secrets.token_urlsafe(18),
            run_id=session.run_id,
            kind=kind,
            artifact_revision=session.revision,
            payload=payload,
            timeout_ms=int(timeout * 1000),
        )
        task["digest"] = hashlib.sha256(json.dumps(task, sort_keys=True).encode()).hexdigest()
        session.task = {"event": task, "deadline": now + timeout, "issued": now, "done": False}
        return task

    def validate(self, session: PlaceSession, task_id: str, run_id: str, digest: str) -> dict:
        self.require_active(session)
        task = session.task
        if (
            task is None
            or task["done"]
            or session.run_id != run_id
            or task["event"]["task_id"] != task_id
            or not hmac.compare_digest(task["event"]["digest"].encode(), digest.encode())
        ):
            raise PlaceSessionError("stale_task")
        if self.clock() >= task["deadline"]:
            self.retire(session)
            session.result = {"status": "unavailable", "reason": "task_expired"}
            raise PlaceSessionError("task_expired")
        return task["event"]

    def complete(
        self, session: PlaceSession, task_id: str, run_id: str, digest: str, result: dict
    ) -> None:
        with self.lock:
            self.validate(session, task_id, run_id, digest)
            self.retire(session)
            session.result = result
