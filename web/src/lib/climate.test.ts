import { describe, expect, it, vi } from 'vitest';

import {
  ClimateApiError,
  CLIMATE_COLOR_LIMITS,
  climateColor,
  climateColorPosition,
  createClimateApi,
  type ClimateLocationsResponse,
} from './climate';

const locationsResponse: ClimateLocationsResponse = {
  revision: 'climate-2026-01',
  end_year: 2025,
  source: {
    name: 'Open-Meteo',
    url: 'https://open-meteo.com/',
    attribution: 'Open-Meteo and ERA5-Land',
    timezone: 'Europe/London',
    model: 'ERA5-Land',
  },
  week_id: 8,
  week_label: 'June 26–July 2',
  period_years: 25,
  metric: 'high',
  locations: [],
};

describe('createClimateApi', () => {
  it('gets location summaries with the climate query', async () => {
    const fetchFn = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(locationsResponse), { status: 200 }),
    );

    await expect(createClimateApi(fetchFn).locations({
      week_id: 8,
      period_years: 25,
      metric: 'high',
    })).resolves.toEqual(locationsResponse);

    expect(fetchFn).toHaveBeenCalledWith(
      '/api/climate/locations?week_id=8&period_years=25&metric=high',
      { method: 'GET' },
    );
  });

  it('gets one location with its selected week', async () => {
    const fetchFn = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ ...locationsResponse, location: {} }), { status: 200 }),
    );

    await createClimateApi(fetchFn).location('Oxford & Centre', { week_id: 8 });

    expect(fetchFn).toHaveBeenCalledWith(
      '/api/climate/locations/Oxford%20%26%20Centre?week_id=8',
      { method: 'GET' },
    );
  });

  it('exposes structured API errors without leaking an HTTP response body', async () => {
    const fetchFn = vi.fn<typeof fetch>().mockResolvedValue(new Response(
      JSON.stringify({ detail: { code: 'climate_unavailable', message: 'Climate is unavailable.', fields: [] } }),
      { status: 503, headers: { 'Content-Type': 'application/json' } },
    ));

    const promise = createClimateApi(fetchFn).locations({ week_id: 8, period_years: 25, metric: 'high' });

    await expect(promise).rejects.toBeInstanceOf(ClimateApiError);
    await expect(promise).rejects.toMatchObject({
      status: 503,
      code: 'climate_unavailable',
      message: 'Climate is unavailable.',
    });
  });

  it('uses a safe message for non-JSON HTTP errors', async () => {
    const fetchFn = vi.fn<typeof fetch>().mockResolvedValue(
      new Response('<html>gateway details</html>', { status: 502, statusText: 'Bad Gateway' }),
    );

    await expect(createClimateApi(fetchFn).locations({ week_id: 8, period_years: 25, metric: 'high' }))
      .rejects.toMatchObject({ status: 502, code: 'http_error', message: 'Bad Gateway' });
  });
});

describe('climate marker colour scale', () => {
  it('keeps fixed metric limits and visibly clips outliers', () => {
    expect(CLIMATE_COLOR_LIMITS).toEqual({
      high: { min: 0, max: 35 },
      low: { min: -5, max: 25 },
    });
    expect(climateColorPosition('high', -20)).toBe(0);
    expect(climateColorPosition('high', 100)).toBe(1);
    expect(climateColorPosition('low', 10)).toBeCloseTo(0.5);
    expect(climateColor('high', -20)).toBe(climateColor('high', 0));
    expect(climateColor('low', 30)).toBe(climateColor('low', 25));
  });
});
