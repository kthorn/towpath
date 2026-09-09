import { describe, expect, it, vi } from 'vitest';

import {
  ClimateGridApiError,
  createClimateGridApi,
  highExceedanceFraction,
  type ClimateGridSurface,
} from './climate-grid';

const source = {
  name: 'Open-Meteo',
  url: 'https://open-meteo.com/',
  attribution: 'Open-Meteo and ERA5-Land',
  timezone: 'Europe/London',
  model: 'ERA5-Land',
};

const surface: ClimateGridSurface = {
  revision: 'grid-r1',
  end_year: 2025,
  source,
  week_id: 8,
  week_label: 'June 26–July 2',
  period_years: 25,
  view: 'high_p90',
  threshold_c: null,
  unit: 'celsius',
  spacing_km: 10,
  mask: { type: 'Polygon', coordinates: [[[-2, 50], [1, 50], [1, 54], [-2, 54], [-2, 50]]] },
  cells: [{ id: 'uk-1', coordinate: { lat: 51.5, lon: -1 }, value: 27.5, n_days: 175 }],
};

describe('createClimateGridApi', () => {
  it('gets a temperature surface with the exact grid query', async () => {
    const fetchFn = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(surface), { status: 200 }),
    );

    await expect(createClimateGridApi(fetchFn).grid({
      week_id: 8,
      period_years: 25,
      view: 'high_p90',
    })).resolves.toEqual(surface);

    expect(fetchFn).toHaveBeenCalledWith(
      '/api/climate/grid?week_id=8&period_years=25&view=high_p90',
      { method: 'GET' },
    );
  });

  it('includes the strict exceedance threshold only for the exceedance view', async () => {
    const fetchFn = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ ...surface, view: 'high_exceedance', threshold_c: 30, unit: 'probability' }), { status: 200 }),
    );

    await createClimateGridApi(fetchFn).grid({
      week_id: 8,
      period_years: 5,
      view: 'high_exceedance',
      threshold_c: 30,
    });

    expect(fetchFn).toHaveBeenCalledWith(
      '/api/climate/grid?week_id=8&period_years=5&view=high_exceedance&threshold_c=30',
      { method: 'GET' },
    );
  });

  it('gets one grid cell through the existing climate detail endpoint', async () => {
    const fetchFn = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ ...surface, location: {} }), { status: 200 }),
    );

    await createClimateGridApi(fetchFn).cell('island/1', { week_id: 8 });

    expect(fetchFn).toHaveBeenCalledWith(
      '/api/climate/grid/cells/island%2F1?week_id=8',
      { method: 'GET' },
    );
  });

  it('returns safe structured errors without exposing an HTTP body', async () => {
    const fetchFn = vi.fn<typeof fetch>().mockResolvedValue(new Response(
      JSON.stringify({ detail: { code: 'grid_unavailable', message: 'Grid is unavailable.', fields: [] } }),
      { status: 503, headers: { 'Content-Type': 'application/json' } },
    ));

    await expect(createClimateGridApi(fetchFn).grid({ week_id: 8, period_years: 25, view: 'high_p90' }))
      .rejects.toMatchObject({ status: 503, code: 'grid_unavailable', message: 'Grid is unavailable.' });
    await expect(createClimateGridApi(fetchFn).grid({ week_id: 8, period_years: 25, view: 'high_p90' }))
      .rejects.toBeInstanceOf(ClimateGridApiError);
  });
});

describe('high exceedance fraction', () => {
  it('counts values strictly above the threshold using the stored day count', () => {
    expect(highExceedanceFraction([30, 30.1, 31, 29], 30, 4)).toBe(0.5);
    expect(highExceedanceFraction([30, 30], 30, 2)).toBe(0);
    expect(highExceedanceFraction([35], 30, 0)).toBe(0);
  });
});
