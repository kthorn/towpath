"""Opt-in JSON Lines timing and peak-memory reporting for artifact builds."""

import json
import resource
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TextIO


def linux_max_rss_bytes(max_rss_kib: int | float) -> int:
    """Convert Linux ``ru_maxrss`` values from KiB to bytes."""
    return int(max_rss_kib * 1024)


def _peak_rss_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return linux_max_rss_bytes(usage.ru_maxrss)


class BuildProfiler:
    """Emit completed build phases without adding work when disabled."""

    def __init__(self, *, enabled: bool = False, stream: TextIO | None = None) -> None:
        self.enabled = enabled
        self._stream = stream

    @contextmanager
    def phase(
        self,
        phase: str,
        *,
        counts: Callable[[], dict] | None = None,
    ) -> Iterator[None]:
        if not self.enabled:
            yield
            return

        started_at = time.perf_counter()
        try:
            yield
        except BaseException:
            self._emit(phase, "failed", started_at, counts)
            raise
        else:
            self._emit(phase, "completed", started_at, counts)

    def _emit(
        self,
        phase: str,
        status: str,
        started_at: float,
        counts: Callable[[], dict] | None,
    ) -> None:
        record = {
            "build_profile": 1,
            "phase": phase,
            "status": status,
            "elapsed_s": time.perf_counter() - started_at,
            "peak_rss_bytes": _peak_rss_bytes(),
            "counts": counts() if counts is not None else {},
        }
        print(json.dumps(record, sort_keys=True), file=self._stream or sys.stderr, flush=True)
