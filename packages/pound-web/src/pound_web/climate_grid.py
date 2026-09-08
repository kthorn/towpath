"""Bounded historical temperature surfaces and exact grid-point details."""

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from pound.climate.grid import ClimateGrid, GridView, InvalidClimateGridError

from pound_web.api import _climate_response, _error

router = APIRouter(prefix="/api/climate/grid")


def _grid(request: Request) -> ClimateGrid:
    grid = getattr(request.app.state, "climate_grid", None)
    if grid is None:
        raise _error(
            503,
            code="climate_grid_unavailable",
            message="Historical temperature grid is unavailable.",
        )
    return grid


@router.get("")
def surface(
    request: Request,
    week_id: Annotated[int, Query(ge=0, le=17)] = 8,
    period_years: int = 25,
    view: GridView = "high_p90",
    threshold_c: Annotated[float, Query(ge=-20, le=50, allow_inf_nan=False)] = 30,
) -> Response:
    """One scalar per grid point, never empirical sample arrays."""
    if period_years not in (5, 25):
        raise _error(422, code="invalid_period", message="period_years must be 5 or 25.")
    try:
        data = _grid(request).surface(week_id, period_years, view, threshold_c)
    except InvalidClimateGridError as exc:
        raise _error(
            503,
            code="climate_grid_unavailable",
            message="Historical temperature grid is unavailable.",
        ) from exc
    key = f"grid:{week_id}:{period_years}:{view}"
    if view == "high_exceedance":
        key += f":{threshold_c!r}"
    return _climate_response(request, data, key)


@router.get("/cells/{cell_id}")
def detail(
    request: Request, cell_id: str, week_id: Annotated[int, Query(ge=0, le=17)] = 8
) -> Response:
    """Both periods and both daily metrics at an original sample location."""
    try:
        data = _grid(request).detail(cell_id, week_id)
    except InvalidClimateGridError as exc:
        raise _error(
            503,
            code="climate_grid_unavailable",
            message="Historical temperature grid is unavailable.",
        ) from exc
    if data is None:
        raise _error(404, code="climate_cell_not_found", message="Temperature grid cell not found.")
    return _climate_response(request, data, f"grid-cell:{cell_id}:{week_id}")
