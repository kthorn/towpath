"""Request-time entry point — STUB.

Returns a hardcoded plausible RouteResult for one Oxford Canal leg so the
Agent Core (labyrinth-core / labyrinth-agent) can build against the
`plan_route` contract before the real engine lands.

The leg's est_minutes is computed from the documented cost model (design
§5.2), so it is consistent with the formula the real engine and the
structural-invariant tests (design §7.2) will assert against:
    est_minutes = round(distance_km / CRUISE_KMH * 60 + locks * LOCK_MINUTES)
For distance_km=9.5, locks=2: 9.5/4.8*60 + 2*12 = 142.75 -> 143 min.
Real engine computes this per-edge; the stub hardcodes the inputs and
computes the leg total from the same constants.
"""

from pound.schemas import (
    Amenity,
    CanalConstraints,
    DayPlan,
    RouteLeg,
    RouteResult,
)

CRUISE_KMH = 4.8
LOCK_MINUTES = 12


def _leg_minutes(distance_km: float, locks: int) -> int:
    """Cost model for a single leg (design §5.2). Single source of truth for the stub."""
    return round(distance_km / CRUISE_KMH * 60 + locks * LOCK_MINUTES)


def plan_route(constraints: CanalConstraints) -> RouteResult:
    """Stub: return a hardcoded plausible Oxford -> Heyford route.

    Real implementation: snap start/end to the graph, filter edges by boat
    dimensions, run shortest path on time cost, collect amenities. See design §5.
    """
    is_ring = constraints.end is None

    leg = RouteLeg(
        from_place=constraints.start,
        to_place=constraints.end if constraints.end else constraints.start,
        distance_km=9.5,
        locks=2,
        est_minutes=_leg_minutes(9.5, 2),
    )

    day = DayPlan(
        day=1,
        legs=[leg],
        end_near=constraints.end if constraints.end else constraints.start,
        cruising_minutes=leg.est_minutes,
    )

    amenity = Amenity(
        kind="pub",
        name="The Navigation",
        lat=51.75,
        lon=-1.26,
        distance_m=120.0,
        source="osm",
    )

    return RouteResult(
        start=constraints.start,
        end=constraints.end,
        is_ring=is_ring,
        legs=[leg],
        days=[day],
        total_km=leg.distance_km,
        total_locks=leg.locks,
        total_minutes=leg.est_minutes,
        amenities=[amenity],
        warnings=[],
        graph_source_date="2026-06-21",
    )
