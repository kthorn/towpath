"""Stable seven-day summer windows used by the climate overlay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class WeekDefinition:
    week_id: int
    label: str
    start: tuple[int, int]


def _month_day_label(start: date, end: date) -> str:
    if start.month == end.month:
        return f"{start.strftime('%B')} {start.day}–{end.day}"
    return f"{start.strftime('%B')} {start.day}–{end.strftime('%B')} {end.day}"


def _build_definitions() -> tuple[WeekDefinition, ...]:
    definitions: list[WeekDefinition] = []
    anchor = date(2001, 5, 1)
    for week_id in range(18):
        start = anchor + timedelta(days=week_id * 7)
        end = start + timedelta(days=6)
        definitions.append(
            WeekDefinition(
                week_id=week_id,
                label=_month_day_label(start, end),
                start=(start.month, start.day),
            )
        )
    return tuple(definitions)


WEEK_DEFINITIONS = _build_definitions()
WEEK_COUNT = len(WEEK_DEFINITIONS)


def _definition(week_id: int) -> WeekDefinition:
    if type(week_id) is not int or not 0 <= week_id < WEEK_COUNT:
        raise ValueError(f"week_id must be an integer from 0 through {WEEK_COUNT - 1}")
    return WEEK_DEFINITIONS[week_id]


def week_label(week_id: int) -> str:
    """Return the stable human-readable label for a supported week."""

    return _definition(week_id).label


def week_dates(year: int, week_id: int) -> tuple[date, ...]:
    """Return the seven calendar dates for a fixed summer window."""

    definition = _definition(week_id)
    start = date(year, definition.start[0], definition.start[1])
    return tuple(start + timedelta(days=offset) for offset in range(7))
