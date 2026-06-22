"""Request-time entry point — STUB.

Returns a hardcoded plausible RouteResult for one Oxford Canal leg so the
Agent Core (labyrinth-core / labyrinth-agent) can build against the
`plan_route` contract before the real engine lands.

The numbers are consistent with the documented cost model (design §5.2):
    est_minutes = distance_km / 4.8 * 60 + locks * 12
9.5 km / 4.8 * 60 = 118.75 ; + 2 locks * 12 = 142.75 -> 143 min (rounded).
The stub uses 131 for a shorter leg so the totals arithmetic stays exact
across the structural tests. Real engine computes this; the stub hardcodes it.
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
        est_minutes=131,
    )

    day = DayPlan(
        day=1,
        legs=[leg],
        end_near=constraints.end if constraints.end else constraints.start,
        cruising_minutes=131,
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
