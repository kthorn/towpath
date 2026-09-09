"""Runtime validation for the graph's persisted turnaround index.

Turnaround records are produced by :mod:`pound_build`, but the records and
their node references are consumed by core routing code.  Keeping this small
validator in core lets the trusted artifact loader reject malformed records
without importing any build-only modules.
"""

from __future__ import annotations

import math

import networkx as nx

_SOURCE_REQUIRED = {"source", "identity", "source_date", "attribution"}
_RECORD_REQUIRED = {
    "turnaround_id",
    "kind",
    "node_uid",
    "coordinate",
    "display_name",
    "eligibility_basis",
    "sources",
    "turning_limits",
}
_LIMIT_FIELDS = {
    "boat_length_m",
    "boat_beam_m",
    "boat_draft_m",
    "boat_height_m",
    "prohibited",
}


def validate_turnarounds(graph: nx.Graph) -> list[dict]:
    """Validate and return the normalized turnaround index.

    Artifacts built before the turnaround index was introduced remain valid at
    this narrow compatibility layer; callers receive an empty index when the
    graph has no ``turnarounds`` attribute.  If the attribute is present, its
    records are strict because routing must never use an invalid node
    reference or stale coordinate.
    """

    if "turnarounds" not in graph.graph:
        return []
    records = graph.graph["turnarounds"]
    if not isinstance(records, list):
        raise ValueError("turnarounds must be a list")
    previous = None
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != _RECORD_REQUIRED:
            raise ValueError(f"turnaround[{index}] fields are invalid")
        turnaround_id = record["turnaround_id"]
        if not isinstance(turnaround_id, str) or not turnaround_id:
            raise ValueError(f"turnaround[{index}] turnaround_id is invalid")
        if previous is not None and turnaround_id <= previous:
            raise ValueError("turnarounds must be sorted by turnaround_id")
        previous = turnaround_id
        kind = record["kind"]
        if kind not in {"winding_hole", "junction"}:
            raise ValueError(f"turnaround[{index}] kind is invalid")
        expected_basis = (
            "mapped_winding_hole" if kind == "winding_hole" else "junction_assumption"
        )
        if record["eligibility_basis"] != expected_basis:
            raise ValueError(f"turnaround[{index}] eligibility_basis is invalid")

        uid = record["node_uid"]
        if isinstance(uid, bool) or not isinstance(uid, int) or not graph.has_node(uid):
            raise ValueError(f"turnaround[{index}] node_uid reference is invalid")
        coordinate = record["coordinate"]
        if not isinstance(coordinate, dict) or set(coordinate) != {"lat", "lon"}:
            raise ValueError(f"turnaround[{index}] coordinate is invalid")
        for field, lower, upper in (("lat", -90, 90), ("lon", -180, 180)):
            value = coordinate[field]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not lower <= value <= upper
            ):
                raise ValueError(f"turnaround[{index}] coordinate.{field} is invalid")
            if abs(float(value) - float(graph.nodes[uid][field])) > 1e-5:
                raise ValueError(f"turnaround[{index}] coordinate does not match node_uid")

        if not isinstance(record["display_name"], str) or not record["display_name"]:
            raise ValueError(f"turnaround[{index}] display_name is invalid")
        sources = record["sources"]
        if not isinstance(sources, list) or not sources:
            raise ValueError(f"turnaround[{index}] sources are invalid")
        for source in sources:
            if not isinstance(source, dict) or not _SOURCE_REQUIRED <= set(source):
                raise ValueError(f"turnaround[{index}] source is invalid")
            if any(
                not isinstance(source[field], str) or not source[field]
                for field in _SOURCE_REQUIRED
            ):
                raise ValueError(f"turnaround[{index}] source fields are invalid")
            for field in set(source) - _SOURCE_REQUIRED:
                if field not in {"tags", "evidence"} or not isinstance(source[field], dict):
                    raise ValueError(f"turnaround[{index}] source evidence is invalid")

        limits = record["turning_limits"]
        if not isinstance(limits, dict) or not set(limits) <= _LIMIT_FIELDS:
            raise ValueError(f"turnaround[{index}] turning_limits are invalid")
        for field, value in limits.items():
            if field == "prohibited":
                if type(value) is not bool:
                    raise ValueError(f"turnaround[{index}] prohibited is invalid")
            elif (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"turnaround[{index}] turning limit is invalid")
    return records
