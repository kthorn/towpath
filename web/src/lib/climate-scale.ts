import { CLIMATE_COLOR_LIMITS } from './climate';
import type { ClimateGridView } from './climate-grid';

export interface ClimateColorRange { min: number; max: number }

export function climateScaleDomain(view: ClimateGridView): ClimateColorRange {
  return view === 'high_exceedance' ? {min: 0, max: 1} : {min: -50, max: 60};
}

export function validClimateScale(view: ClimateGridView, range: ClimateColorRange): boolean {
  const domain = climateScaleDomain(view);
  return Number.isFinite(range.min) && Number.isFinite(range.max) && range.min < range.max
    && range.min >= domain.min && range.max <= domain.max;
}

/** Use all available UK cells, never the viewport or the interpolated screen pixels. */
export function resolveClimateScale(
  view: ClimateGridView,
  cells: readonly {value: number | null}[],
  manual?: ClimateColorRange | null,
): ClimateColorRange {
  if (manual && validClimateScale(view, manual)) return manual;
  if (view !== 'high_exceedance') return CLIMATE_COLOR_LIMITS[view.startsWith('low') ? 'low' : 'high'];
  const values = cells.map(c => c.value).filter((v): v is number => v !== null && Number.isFinite(v) && v >= 0 && v <= 1).sort((a, b) => a - b);
  const percentile = values[Math.max(0, Math.ceil(values.length * 0.999) - 1)] ?? 0;
  // If almost all cells are zero, retain the isolated nonzero cells in the scale.
  return {min: 0, max: percentile || values.at(-1) || 0.01};
}

export function zoomClimateScale(view: ClimateGridView, range: ClimateColorRange, factor: number): ClimateColorRange {
  const domain = climateScaleDomain(view);
  const center = (range.min + range.max) / 2;
  const half = (range.max - range.min) * factor / 2;
  return {min: Math.max(domain.min, center - half), max: Math.min(domain.max, center + half)};
}
