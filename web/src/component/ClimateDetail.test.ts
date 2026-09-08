import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { describe, expect, it, vi } from 'vitest';

import type { ClimateLocationResponse } from '../lib/climate';
import { createClimateStore } from '../lib/stores/climate';
import ClimateDetail from './ClimateDetail.svelte';

const detail: ClimateLocationResponse = {
  revision: 'r1',
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
  location: {
    id: 'oxford',
    name: 'Oxford',
    coordinate: { lat: 51.752, lon: -1.257 },
    source_coordinate: { lat: 51.75, lon: -1.25 },
    elevation: 64,
  },
  high: {
    '25': { available: true, missing_years: [], start_year: 2001, end_year: 2025, n_days: 175, n_years: 25, p10: 15.1, median: 20, p90: 25.2, samples: [15, 20, 25] },
    '5': { available: true, missing_years: [], start_year: 2021, end_year: 2025, n_days: 35, n_years: 5, p10: 16.2, median: 21, p90: 24.5, samples: [16, 21, 24] },
  },
  low: {
    '25': { available: true, missing_years: [], start_year: 2001, end_year: 2025, n_days: 175, n_years: 25, p10: 6.1, median: 10, p90: 14.2, samples: [6, 10, 14] },
    '5': { available: false, missing_years: [2022], start_year: 2021, end_year: 2025, n_days: 28, n_years: 4, p10: null, median: null, p90: null, samples: [] },
  },
};

describe('ClimateDetail', () => {
  it('compares both periods and metrics with an accessible selected-metric ECDF', async () => {
    const onClose = vi.fn();
    render(ClimateDetail, { props: { detail, metric: 'high', onClose } });

    expect(screen.getByRole('heading', { name: 'Oxford' })).toBeInTheDocument();
    expect(screen.getByText('June 26–July 2')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /open-meteo/i })).toHaveAttribute('href', detail.source.url);
    expect(screen.getByText(/25 years: 2001–2025/i)).toBeInTheDocument();
    expect(screen.getByText(/5 years: 2021–2025/i)).toBeInTheDocument();
    expect(screen.getByRole('table', { name: /historical daily temperature distributions/i })).toHaveTextContent('20.0');
    expect(screen.getByRole('img', { name: /daily highs empirical distribution/i })).toBeInTheDocument();
    expect(screen.getAllByTestId('ecdf-line')).toHaveLength(2);
    expect(screen.getAllByTestId('ecdf-line')[0]).toHaveAttribute(
      'points', expect.stringContaining('0.00,100.00 0.00,66.67'),
    );
    expect(screen.getAllByText(/Middle 80% of historical daily highs/i)).toHaveLength(2);
    expect(screen.getByRole('button', { name: /close temperature details/i })).toBeInTheDocument();

    await fireEvent.click(screen.getByRole('button', { name: /close temperature details/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('labels an unavailable period instead of rendering zero values', () => {
    render(ClimateDetail, { props: { detail, metric: 'low', onClose: vi.fn() } });

    expect(screen.getByRole('img', { name: /daily lows empirical distribution/i })).toBeInTheDocument();
    expect(screen.getByText(/5 years.*unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/missing years: 2022/i)).toBeInTheDocument();
    expect(screen.queryByText('0.0')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('ecdf-line')).toHaveLength(1);
  });

  it('offers revision recovery by refreshing summaries before retrying the selected detail', async () => {
    const refreshed = { ...detail, revision: 'r2' };
    const climateApi = {
      locations: vi.fn()
        .mockResolvedValueOnce({
          revision: 'r1', end_year: 2025, source: detail.source, week_id: 8,
          week_label: detail.week_label, period_years: 25, metric: 'high', locations: [],
        })
        .mockResolvedValueOnce({
          revision: 'r2', end_year: 2025, source: detail.source, week_id: 8,
          week_label: detail.week_label, period_years: 25, metric: 'high', locations: [],
        }),
      location: vi.fn()
        .mockResolvedValueOnce({ ...detail, revision: 'r2' })
        .mockResolvedValueOnce(refreshed),
    };
    const store = createClimateStore({ api: climateApi });
    await store.setEnabled(true);
    await store.selectLocation('oxford');

    expect(get(store)).toMatchObject({ detail: null, detailError: 'Climate data changed; refresh the layer.', selection: 'oxford' });
    render(ClimateDetail, { props: { store } });

    await fireEvent.click(screen.getByRole('button', { name: /retry temperature details/i }));
    await waitFor(() => expect(get(store).detail).toEqual(refreshed));

    expect(climateApi.locations).toHaveBeenCalledTimes(2);
    expect(climateApi.location).toHaveBeenCalledTimes(2);
    expect(get(store).detailError).toBeNull();
  });

  it('shows an explicit unavailable state without a fake axis when no samples exist', () => {
    const noSamples: ClimateLocationResponse = {
      ...detail,
      high: {
        '25': { ...detail.high['25'], available: false, p10: null, median: null, p90: null, samples: [] },
        '5': { ...detail.high['5'], available: false, p10: null, median: null, p90: null, samples: [] },
      },
    };
    render(ClimateDetail, { props: { detail: noSamples, metric: 'high', onClose: vi.fn() } });

    expect(screen.getByText(/empirical distribution unavailable/i)).toBeInTheDocument();
    expect(screen.queryByTestId('ecdf-line')).not.toBeInTheDocument();
    expect(screen.queryByText(/Middle 80% of historical daily highs: p10/i)).not.toBeInTheDocument();
    expect(screen.queryByText('0.0°C')).not.toBeInTheDocument();
    expect(screen.queryByText('25 years')).toBeInTheDocument();
  });
});

it('keeps accessible names distinct when grid and city details coexist', () => {
  render(ClimateDetail, { props: { detail, metric: 'high' } });
  render(ClimateDetail, { props: { detail: { ...detail, location: { ...detail.location, name: 'Grid sample' } }, metric: 'low' } });
  expect(screen.getByRole('complementary', { name: 'Oxford' })).toBeInTheDocument();
  expect(screen.getByRole('complementary', { name: 'Grid sample' })).toBeInTheDocument();
  const headings = screen.getAllByRole('heading');
  const ids = headings.map((heading) => heading.id).filter(Boolean);
  expect(new Set(ids).size).toBe(ids.length);
});
