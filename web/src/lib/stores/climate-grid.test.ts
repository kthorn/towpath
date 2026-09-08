import { get } from 'svelte/store';
import { describe, expect, it, vi } from 'vitest';

import type { ClimateLocationResponse } from '../climate';
import type { ClimateGridApi, ClimateGridSurface } from '../climate-grid';
import { createClimateGridStore } from './climate-grid';

const source = {
  name: 'Open-Meteo',
  url: 'https://open-meteo.com/',
  attribution: 'Open-Meteo and ERA5-Land',
  timezone: 'Europe/London',
  model: 'ERA5-Land',
};

const surface = (overrides: Partial<ClimateGridSurface> = {}): ClimateGridSurface => ({
  revision: 'r1',
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
  ...overrides,
});

const detail: ClimateLocationResponse = {
  revision: 'r1',
  end_year: 2025,
  source,
  week_id: 8,
  week_label: 'June 26–July 2',
  location: {
    id: 'uk-1', name: 'UK grid uk-1', coordinate: { lat: 51.5, lon: -1 },
    source_coordinate: null, elevation: null,
  },
  high: {
    '25': { available: true, missing_years: [], start_year: 2001, end_year: 2025, n_days: 175, n_years: 25, p10: 15, median: 20, p90: 30, samples: [15, 20, 30] },
    '5': { available: true, missing_years: [], start_year: 2021, end_year: 2025, n_days: 35, n_years: 5, p10: 16, median: 21, p90: 31, samples: [16, 21, 31] },
  },
  low: {
    '25': { available: true, missing_years: [], start_year: 2001, end_year: 2025, n_days: 175, n_years: 25, p10: 4, median: 8, p90: 12, samples: [4, 8, 12] },
    '5': { available: true, missing_years: [], start_year: 2021, end_year: 2025, n_days: 35, n_years: 5, p10: 5, median: 9, p90: 13, samples: [5, 9, 13] },
  },
};

function api(overrides: Partial<ClimateGridApi> = {}): ClimateGridApi {
  return {
    grid: vi.fn(async () => surface()),
    cell: vi.fn(async () => detail),
    ...overrides,
  };
}

describe('createClimateGridStore', () => {
  it('starts disabled with the approved grid defaults', () => {
    const store = createClimateGridStore({ api: api() });

    expect(get(store)).toMatchObject({
      enabled: false,
      weekId: 8,
      periodYears: 25,
      view: 'high_p90',
      thresholdC: 30,
      opacity: 0.4,
      surface: null,
      detail: null,
      selection: null,
    });
  });

  it('loads the surface when enabled and keeps response metadata', async () => {
    const climateApi = api();
    const store = createClimateGridStore({ api: climateApi });

    await store.setEnabled(true);

    expect(climateApi.grid).toHaveBeenCalledWith({ week_id: 8, period_years: 25, view: 'high_p90' });
    expect(get(store)).toMatchObject({ enabled: true, surface: surface(), loading: false, error: null });
  });

  it('clears the old surface and ignores a stale response after the week changes', async () => {
    let resolveFirst!: (value: ClimateGridSurface) => void;
    const first = new Promise<ClimateGridSurface>((resolve) => { resolveFirst = resolve; });
    const climateApi = api({
      grid: vi.fn().mockReturnValueOnce(first).mockResolvedValueOnce(surface({ week_id: 9, week_label: 'July 3–9' })),
    });
    const store = createClimateGridStore({ api: climateApi });

    const enabling = store.setEnabled(true);
    await store.setWeek(9);
    resolveFirst(surface());
    await enabling;

    expect(get(store)).toMatchObject({ weekId: 9, surface: surface({ week_id: 9, week_label: 'July 3–9' }), error: null });
  });

  it('rejects a response whose query metadata does not match current state', async () => {
    const climateApi = api({ grid: vi.fn(async () => surface({ period_years: 5 })) });
    const store = createClimateGridStore({ api: climateApi });

    await store.setEnabled(true);

    expect(get(store)).toMatchObject({ surface: null, error: expect.stringMatching(/did not match/i) });
  });

  it('discards stale detail failures when the selected week changes', async () => {
    let rejectDetail!: (reason?: unknown) => void;
    const pending = new Promise<ClimateLocationResponse>((_resolve, reject) => { rejectDetail = reject; });
    const climateApi = api({ cell: vi.fn().mockReturnValueOnce(pending) });
    const store = createClimateGridStore({ api: climateApi });
    await store.setEnabled(true);

    const selecting = store.selectCell('uk-1');
    await store.setWeek(9);
    rejectDetail(new Error('obsolete failure'));
    await selecting;

    expect(get(store)).toMatchObject({ weekId: 9, selection: null, detail: null, detailError: null });
  });

  it('recovers a revision-mismatched detail through refresh and retry', async () => {
    const climateApi = api({
      grid: vi.fn().mockResolvedValueOnce(surface()).mockResolvedValueOnce(surface({ revision: 'r2' })),
      cell: vi.fn().mockRejectedValueOnce(new Error('temporary detail failure')).mockResolvedValueOnce({ ...detail, revision: 'r2' }),
    });
    const store = createClimateGridStore({ api: climateApi });
    await store.setEnabled(true);
    await store.selectCell('uk-1');
    expect(get(store).detailError).toBe('temporary detail failure');

    await store.retryDetail();

    expect(climateApi.grid).toHaveBeenCalledTimes(2);
    expect(climateApi.cell).toHaveBeenCalledTimes(2);
    expect(get(store)).toMatchObject({ detail: { revision: 'r2' }, detailError: null });
  });

  it('refreshes the exceedance view with strict threshold changes', async () => {
    const climateApi = api({ grid: vi.fn().mockResolvedValue(surface({ view: 'high_exceedance', unit: 'probability', threshold_c: 30 })) });
    const store = createClimateGridStore({ api: climateApi });
    await store.setEnabled(true);
    await store.setView('high_exceedance');
    await store.setThreshold(31);

    expect(climateApi.grid).toHaveBeenLastCalledWith({ week_id: 8, period_years: 25, view: 'high_exceedance', threshold_c: 31 });
    expect(get(store).thresholdC).toBe(31);
  });

  it('clamps opacity and validates threshold bounds', async () => {
    const store = createClimateGridStore({ api: api() });

    await store.setOpacity(1.5);
    expect(get(store).opacity).toBe(1);
    await expect(store.setThreshold(51)).rejects.toThrow(/threshold/i);
    await expect(store.setThreshold(-21)).rejects.toThrow(/threshold/i);
  });
});
