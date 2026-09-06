"""Pure aggregation for historical daily temperature distributions."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from pound.climate.artifact import ClimateDistribution


def linear_quantile(values: Sequence[float], probability: float) -> float:
    """Return a linearly interpolated quantile using the contract's ``n - 1`` index."""

    if not 0 <= probability <= 1 or not math.isfinite(probability):
        raise ValueError("probability must be finite and between 0 and 1")
    if not values:
        raise ValueError("cannot calculate a quantile for an empty sample")
    sorted_values = sorted(float(value) for value in values)
    if not all(math.isfinite(value) for value in sorted_values):
        raise ValueError("quantile values must be finite")
    index = (len(sorted_values) - 1) * probability
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return sorted_values[lower]
    fraction = index - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


def summarize_distribution(
    values_by_year: Mapping[int, Sequence[float] | None],
    *,
    start_year: int,
    end_year: int,
) -> ClimateDistribution:
    """Build one metric summary from seven values per eligible calendar year.

    A year contributes only when it has exactly seven finite values.  Partial data is
    represented in ``missing_years`` and never exposed as an empirical sample.
    """

    if type(start_year) is not int or type(end_year) is not int or start_year > end_year:
        raise ValueError("start_year must be an integer no greater than end_year")

    missing_years: list[int] = []
    complete_values: list[float] = []
    complete_years = 0
    for year in range(start_year, end_year + 1):
        values = values_by_year.get(year)
        valid = values is not None and len(values) == 7
        if valid:
            try:
                converted = [float(value) for value in values]
            except (TypeError, ValueError):
                valid = False
            else:
                valid = all(math.isfinite(value) for value in converted)
        if not valid:
            missing_years.append(year)
            continue
        complete_years += 1
        complete_values.extend(converted)

    available = not missing_years
    samples = sorted(complete_values) if available else []
    return ClimateDistribution(
        available=available,
        missing_years=missing_years,
        start_year=start_year,
        end_year=end_year,
        n_days=len(complete_values),
        n_years=complete_years,
        p10=linear_quantile(samples, 0.10) if available else None,
        median=linear_quantile(samples, 0.50) if available else None,
        p90=linear_quantile(samples, 0.90) if available else None,
        samples=samples,
    )


def distribution_from_year_values(
    values_by_year: Mapping[int, Sequence[float] | None], start_year: int, end_year: int
) -> ClimateDistribution:
    """Positional convenience wrapper for callers assembling year values."""

    return summarize_distribution(values_by_year, start_year=start_year, end_year=end_year)
