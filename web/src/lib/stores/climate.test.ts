import { get } from 'svelte/store';
import { describe, expect, it, vi } from 'vitest';

import type {
  ClimateLocationResponse,
  ClimateLocationsResponse,
  ClimateSummaryDistribution,
} from '../climate';
import { createClimateStore } from './climate';

const source = {
  name: 'Open-Meteo',
  url: 'https://open-meteo.com/',
  attribution: 'Open-Meteo and ERA5-Land',
  timezone: 'Europe/London',
  model: 'ERA5-Land',
};

const distribution = (overrides: Partial<ClimateSummaryDistribution> = {}): ClimateSummaryDistribution => ({
  available: true,
  missing_years: [],
  start_year: 2001,
  end_year: 2025,
  n_days: 175,
  n_years: 25,
  p10: 15,
  median: 20,
  p90: 25,
  ...overrides,
});

const locationsResponse = (overrides: Partial<ClimateLocationsResponse> = {}): ClimateLocationsResponse => ({
  revision: 'r1',
  end_year: 2025,
  source,
  week_id: 8,
  week_label: 'June 26–July 2',
  period_years: 25,
  metric: 'high',
  locations: [{
    id: 'oxford',
    name: 'Oxford',
    coordinate: { lat: 51.752, lon: -1.257 },
    distribution: distribution(),
  }],
  ...overrides,
});

const detailResponse: ClimateLocationResponse = {
  revision: 'r1',
  end_year: 2025,
  source,
  week_id: 8,
  week_label: 'June 26–July 2',
  location: {
    id: 'oxford',
    name: 'Oxford',
    coordinate: { lat: 51.752, lon: -1.257 },
    source_coordinate: { lat: 51.75, lon: -1.25 },
    elevation: 64,
  },
  high: { '25': distribution({ samples: [10, 20, 30] }), '5': distribution({ n_days: 35, n_years: 5, samples: [12, 22] }) },
  low: { '25': distribution({ samples: [2, 5, 8] }), '5': distribution({ n_days: 35, n_years: 5, samples: [3, 6] }) },
};

function api(overrides: Partial<{
  locations: (request: { week_id: number; period_years: 5 | 25; metric: 'high' | 'low' }) => Promise<ClimateLocationsResponse>;
  location: (id: string, request: { week_id: number }) => Promise<ClimateLocationResponse>;
}> = {}) {
  return {
    locations: vi.fn(async () => locationsResponse()),
    location: vi.fn(async () => detailResponse),
    ...overrides,
  };
}

describe('createClimateStore', () => {
  it('starts disabled with the approved historical-temperature defaults', () => {
    const store = createClimateStore({ api: api() });

    expect(get(store)).toMatchObject({
      enabled: false,
      weekId: 8,
      periodYears: 25,
      metric: 'high',
      summaries: [],
      detail: null,
      loading: false,
      error: null,
      detailError: null,
      selection: null,
    });
  });

  it('loads summaries when enabled and retains response provenance', async () => {
    const climateApi = api();
    const store = createClimateStore({ api: climateApi });

    await store.setEnabled(true);

    expect(climateApi.locations).toHaveBeenCalledWith({ week_id: 8, period_years: 25, metric: 'high' });
    expect(get(store)).toMatchObject({
      enabled: true,
      summaries: locationsResponse().locations,
      revision: 'r1',
      endYear: 2025,
      source,
      weekLabel: 'June 26–July 2',
      loading: false,
      error: null,
    });
  });

  it('clears summaries before a changed query and fetches the new selection', async () => {
    const climateApi = api({
      locations: vi.fn()
        .mockResolvedValueOnce(locationsResponse())
        .mockResolvedValueOnce(locationsResponse({ metric: 'low' })),
    });
    const store = createClimateStore({ api: climateApi });
    await store.setEnabled(true);
    await store.setMetric('low');

    expect(get(store).summaries).toEqual(locationsResponse().locations);
    expect(climateApi.locations).toHaveBeenNthCalledWith(2, { week_id: 8, period_years: 25, metric: 'low' });
  });

  it('discards an obsolete summaries response after the week changes', async () => {
    let resolveFirst: ((value: ClimateLocationsResponse) => void) | undefined;
    const first = new Promise<ClimateLocationsResponse>((resolve) => { resolveFirst = resolve; });
    const climateApi = api({
      locations: vi.fn()
        .mockReturnValueOnce(first)
        .mockResolvedValueOnce(locationsResponse({ week_id: 9, week_label: 'July 3–9' })),
    });
    const store = createClimateStore({ api: climateApi });

    const enabling = store.setEnabled(true);
    await store.setWeek(9);
    resolveFirst?.(locationsResponse());
    await enabling;

    expect(get(store)).toMatchObject({ weekId: 9, weekLabel: 'July 3–9' });
    expect(get(store).summaries).toHaveLength(1);
  });

  it('retains the last valid overlay when refreshing the same query fails', async () => {
    const climateApi = api({
      locations: vi.fn()
        .mockResolvedValueOnce(locationsResponse())
        .mockRejectedValueOnce(new Error('temporary outage')),
    });
    const store = createClimateStore({ api: climateApi });
    await store.setEnabled(true);
    await store.refresh();

    expect(get(store)).toMatchObject({
      summaries: locationsResponse().locations,
      loading: false,
      error: 'temporary outage',
    });
  });

  it('loads and closes selected location detail', async () => {
    const climateApi = api();
    const store = createClimateStore({ api: climateApi });
    await store.setEnabled(true);
    await store.selectLocation('oxford');

    expect(climateApi.location).toHaveBeenCalledWith('oxford', { week_id: 8 });
    expect(get(store)).toMatchObject({ selection: 'oxford', detail: detailResponse, detailLoading: false });

    store.closeDetail();
    expect(get(store)).toMatchObject({ selection: null, detail: null, detailLoading: false });
  });

  it('discards obsolete detail when the selected week changes', async () => {
    let resolveDetail: ((value: ClimateLocationResponse) => void) | undefined;
    const pending = new Promise<ClimateLocationResponse>((resolve) => { resolveDetail = resolve; });
    const climateApi = api({ location: vi.fn().mockReturnValueOnce(pending) });
    const store = createClimateStore({ api: climateApi });
    await store.setEnabled(true);

    const selecting = store.selectLocation('oxford');
    await store.setWeek(9);
    resolveDetail?.(detailResponse);
    await selecting;

    expect(get(store)).toMatchObject({ weekId: 9, selection: null, detail: null });
  });
});

it('ignores location selection while the climate layer is disabled', async () => {
  const climateApi = api();
  const store = createClimateStore({ api: climateApi });
  await store.selectLocation('oxford');
  expect(climateApi.location).not.toHaveBeenCalled();
  expect(get(store).detail).toBeNull();
});

it.each(['disable', 'close', 'week'])('cancels deferred detail retry after %s', async (action) => {
  let resolveRefresh!: (value: ClimateLocationsResponse) => void;
  const pending = new Promise<ClimateLocationsResponse>((resolve) => { resolveRefresh = resolve; });
  const climateApi = api({
    locations: vi.fn().mockResolvedValueOnce(locationsResponse()).mockReturnValueOnce(pending)
      .mockResolvedValue(locationsResponse({ week_id: 9, week_label: 'July 3–9' })),
    location: vi.fn().mockRejectedValueOnce(new Error('retry needed')).mockResolvedValue(detailResponse),
  });
  const store = createClimateStore({ api: climateApi });
  await store.setEnabled(true);
  await store.selectLocation('oxford');
  const retrying = store.retryDetail();
  if (action === 'disable') await store.setEnabled(false);
  else if (action === 'close') store.closeDetail();
  else await store.setWeek(9);
  resolveRefresh(locationsResponse({ revision: 'r2' }));
  await retrying;
  expect(climateApi.location).toHaveBeenCalledTimes(1);
  expect(get(store).detail).toBeNull();
});
