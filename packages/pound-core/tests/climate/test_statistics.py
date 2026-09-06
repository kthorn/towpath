from __future__ import annotations

from datetime import date

import pytest
from pound.climate.calendar import WEEK_DEFINITIONS, week_dates
from pound.climate.statistics import linear_quantile, summarize_distribution


def test_calendar_exposes_eighteen_stable_seven_day_windows():
    assert len(WEEK_DEFINITIONS) == 18
    assert WEEK_DEFINITIONS[0].label == "May 1–7"
    assert WEEK_DEFINITIONS[0].start == (5, 1)
    assert WEEK_DEFINITIONS[-1].label == "August 28–September 3"
    assert week_dates(2024, 17) == tuple(
        date(2024, 8, day) for day in (28, 29, 30, 31)
    ) + (date(2024, 9, 1), date(2024, 9, 2), date(2024, 9, 3))


def test_linear_quantile_uses_interpolation_on_sorted_daily_values():
    values = [0.0, 10.0, 20.0, 30.0]

    assert linear_quantile(values, 0.10) == pytest.approx(3.0)
    assert linear_quantile(values, 0.50) == pytest.approx(15.0)
    assert linear_quantile(values, 0.90) == pytest.approx(27.0)


def test_distribution_requires_complete_years_and_marks_missing_period_unavailable():
    values_by_year = {year: [float(year + day) for day in range(7)] for year in range(2001, 2026)}
    values_by_year.pop(2010)

    summary = summarize_distribution(values_by_year, start_year=2001, end_year=2025)

    assert summary.available is False
    assert summary.missing_years == [2010]
    assert summary.n_years == 24
    assert summary.n_days == 168
    assert summary.samples == []
    assert summary.p10 is None
    assert summary.median is None


def test_distribution_keeps_sorted_daily_values_and_expected_sample_count():
    values_by_year = {year: [float(year + day) for day in range(7)] for year in range(2021, 2026)}

    summary = summarize_distribution(values_by_year, start_year=2021, end_year=2025)

    assert summary.available is True
    assert summary.n_years == 5
    assert summary.n_days == 35
    assert len(summary.samples) == 35
    assert summary.samples == sorted(summary.samples)
    assert summary.median == pytest.approx(linear_quantile(summary.samples, 0.5))
