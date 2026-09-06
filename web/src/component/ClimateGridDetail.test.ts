import { fireEvent, render, screen } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import { describe, expect, it, vi } from 'vitest';

import type { ClimateLocationResponse } from '../lib/climate';
import type { ClimateGridState, ClimateGridStore } from '../lib/stores/climate-grid';
import ClimateGridDetail from './ClimateGridDetail.svelte';

const detail: ClimateLocationResponse = {
  revision: 'r1',
  end_year: 2025,
  source: { name: 'Source', url: 'https://example.test', attribution: 'Attribution', timezone: 'UTC', model: 'Model' },
  week_id: 8,
  week_label: 'June 26–July 2',
  location: { id: 'cell-1', name: 'UK grid cell-1', coordinate: { lat: 51, lon: -1 }, source_coordinate: null, elevation: null },
  high: {
    '25': { available: true, missing_years: [], start_year: 2001, end_year: 2025, n_days: 175, n_years: 25, p10: 15, median: 20, p90: 30, samples: [15, 20, 30] },
    '5': { available: true, missing_years: [], start_year: 2021, end_year: 2025, n_days: 35, n_years: 5, p10: 16, median: 21, p90: 31, samples: [16, 21, 31] },
  },
  low: {
    '25': { available: true, missing_years: [], start_year: 2001, end_year: 2025, n_days: 175, n_years: 25, p10: 4, median: 8, p90: 12, samples: [4, 8, 12] },
    '5': { available: true, missing_years: [], start_year: 2021, end_year: 2025, n_days: 35, n_years: 5, p10: 5, median: 9, p90: 13, samples: [5, 9, 13] },
  },
};

const baseState: ClimateGridState = {
  enabled: true, weekId: 8, periodYears: 25, view: 'high_p90', thresholdC: 30, opacity: 0.4,
  surface: null, detail, loading: false, error: null, detailLoading: false, detailError: null, selection: 'cell-1',
};

function fakeStore(initial = baseState): ClimateGridStore {
  const inner = writable(initial);
  return {
    subscribe: inner.subscribe,
    setEnabled: vi.fn(async () => {}), setWeek: vi.fn(async () => {}), setPeriod: vi.fn(async () => {}),
    setView: vi.fn(async () => {}), setThreshold: vi.fn(async () => {}), setOpacity: vi.fn(async () => {}),
    selectCell: vi.fn(async () => {}), closeDetail: vi.fn(), refresh: vi.fn(async () => {}), retryDetail: vi.fn(async () => {}),
  };
}

describe('ClimateGridDetail', () => {
  it('passes grid detail through the existing climate detail presentation', async () => {
    const store = fakeStore();
    render(ClimateGridDetail, { props: { store } });

    expect(screen.getByRole('heading', { name: 'UK grid cell-1' })).toBeInTheDocument();
    expect(screen.getByRole('table', { name: /historical daily temperature distributions/i })).toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: /close temperature details/i }));
    expect(store.closeDetail).toHaveBeenCalledOnce();
  });

  it('shows grid detail retry errors and dispatches retry', async () => {
    const store = fakeStore({ ...baseState, detail: null, detailError: 'Grid data changed; refresh the surface.' });
    render(ClimateGridDetail, { props: { store } });

    expect(screen.getByRole('alert')).toHaveTextContent(/grid data changed/i);
    await fireEvent.click(screen.getByRole('button', { name: /retry temperature grid details/i }));
    expect(store.retryDetail).toHaveBeenCalledOnce();
  });

  it('shows strict exceedance counts for both periods and excludes equality', () => {
    const exceedanceDetail = {
      ...detail,
      high: {
        '25': { ...detail.high['25'], n_days: 35, samples: [29, 30, 31, 32] },
        '5': { ...detail.high['5'], n_days: 35, samples: [29, 30, 31] },
      },
    };
    const store = fakeStore({ ...baseState, view: 'high_exceedance', thresholdC: 30, detail: exceedanceDetail });
    render(ClimateGridDetail, { props: { store } });

    expect(screen.getByText(/25 years: 2 of 35 historical daily highs strictly above 30°C \(5\.7%\)/i)).toBeInTheDocument();
    expect(screen.getByText(/5 years: 1 of 35 historical daily highs strictly above 30°C \(2\.9%\)/i)).toBeInTheDocument();
  });

  it('marks exceedance periods unavailable when they have no valid samples', () => {
    const unavailableDetail = {
      ...detail,
      high: { ...detail.high, '25': { ...detail.high['25'], samples: [] } },
    };
    const store = fakeStore({ ...baseState, view: 'high_exceedance', detail: unavailableDetail });
    render(ClimateGridDetail, { props: { store } });

    expect(screen.getByText(/25 years: exceedance unavailable — no valid daily high samples/i)).toBeInTheDocument();
  });
});
