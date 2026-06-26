"""Lock-aware time cost model — design §5.2.

Single source of truth for traversal time and dimension eligibility. Imported
by the planner (route/plan.py) and by the structural-invariant tests (§7.2).
Pure: no graph, no network.
"""

from pound.ingest.ir import WayDimensions

CRUISE_KMH = 4.8  # ~3 mph, standard canal cruising assumption
LOCK_MINUTES = 12  # typical single-lock, single-boat time
BRIDGE_MINUTES = 5  # movable bridge penalty (optional, off by default at planner)


def time_min(length_m: float, locks: int, movable_bridges: int = 0) -> float:
    """Traversal time in minutes for an edge of length_m metres.

    time = (length_m / 1000) / CRUISE_KMH * 60 + locks * LOCK_MINUTES
           + movable_bridges * BRIDGE_MINUTES
    """
    return (
        (length_m / 1000.0) / CRUISE_KMH * 60.0
        + locks * LOCK_MINUTES
        + movable_bridges * BRIDGE_MINUTES
    )


def is_eligible(
    boat_length_m: float | None,
    boat_beam_m: float | None,
    boat_draft_m: float | None,
    boat_height_m: float | None,
    edge_dims: WayDimensions,
) -> tuple[bool, bool]:
    """Dimension eligibility for an edge.

    Missing edge tag => assume passable, but flag unknown=True so the planner
    can caveat the result. Boat dim None => that dimension is not constrained.
    Returns (eligible, flagged_unknown_dims).
    """
    unknown = False
    checks = [
        (boat_beam_m, edge_dims.max_beam_m),
        (boat_length_m, edge_dims.max_length_m),
        (boat_draft_m, edge_dims.max_draft_m),
        (boat_height_m, edge_dims.max_height_m),
    ]
    for boat, edge in checks:
        if boat is None:
            continue
        if edge is None:
            unknown = True
            continue
        if boat > edge:
            return False, False
    return True, unknown
