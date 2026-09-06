import { fireEvent, render, screen } from '@testing-library/svelte';
import { get, writable } from 'svelte/store';
import { describe, expect, it, vi } from 'vitest';

import type { ClimateState, ClimateStore } from '../lib/stores/climate';
import type { ClimateLocationSummary } from '../lib/climate';
import ClimateControls from './ClimateControls.svelte';

const initialState: ClimateState = {
  enabled: false,
  weekId: 8,
  periodYears: 25,
  metric: 'high',
  summaries: [],
  detail: null,
  loading: false,
  error: null,
  detailLoading: false,
  detailError: null,
  selection: null,
  selectedLocationId: null,
  revision: null,
  endYear: null,
  source: null,
  weekLabel: 'June 26–July 2',
};

function fakeStore(state = initialState): ClimateStore {
  const inner = writable(state);
  return {
    subscribe: inner.subscribe,
    setEnabled: vi.fn(async (enabled) => inner.update((current) => ({ ...current, enabled }))),
    setWeek: vi.fn(async (weekId) => inner.update((current) => ({ ...current, weekId }))),
    setPeriod: vi.fn(async (periodYears) => inner.update((current) => ({ ...current, periodYears }))),
    setMetric: vi.fn(async (metric) => inner.update((current) => ({ ...current, metric }))),
    selectLocation: vi.fn(async () => {}),
    closeDetail: vi.fn(),
    refresh: vi.fn(async () => {}),
    retryDetail: vi.fn(async () => {}),
  };
}

describe('ClimateControls', () => {
  it('shows the climate layer defaults and dispatches controls through the store', async () => {
    const store = fakeStore();
    render(ClimateControls, { props: { store } });

    expect(screen.getByRole('checkbox', { name: /historical temperatures/i })).not.toBeChecked();
    await fireEvent.click(screen.getByRole('checkbox', { name: /historical temperatures/i }));
    expect(screen.getByRole('slider', { name: /summer week/i })).toHaveValue('8');
    expect(screen.getByRole('slider', { name: /summer week/i })).toHaveAttribute('aria-valuetext', 'June 26–July 2');
    expect(screen.getByRole('radio', { name: /daily highs/i })).toBeChecked();
    expect(screen.getByRole('radio', { name: /^25 years$/i })).toBeChecked();
    expect(screen.getByText(/Summer week: June 26–July 2/)).toBeInTheDocument();

    await fireEvent.input(screen.getByRole('slider', { name: /summer week/i }), { target: { value: '9' } });
    await fireEvent.click(screen.getByRole('radio', { name: /daily lows/i }));
    await fireEvent.click(screen.getByRole('radio', { name: /^5 years$/i }));

    expect(store.setEnabled).toHaveBeenCalledWith(true);
    expect(store.setWeek).toHaveBeenCalledWith(9);
    expect(screen.getByRole('slider', { name: /summer week/i })).toHaveAttribute('aria-valuetext', 'July 3–9');
    expect(store.setMetric).toHaveBeenCalledWith('low');
    expect(store.setPeriod).toHaveBeenCalledWith(5);
  });

  it('supports explicit state and callbacks without requiring a store', async () => {
    const onEnabledChange = vi.fn();
    const onWeekChange = vi.fn();
    const onMetricChange = vi.fn();
    const onPeriodChange = vi.fn();
    render(ClimateControls, {
      props: {
        state: { ...initialState, enabled: true },
        onEnabledChange,
        onWeekChange,
        onMetricChange,
        onPeriodChange,
      },
    });

    await fireEvent.click(screen.getByRole('checkbox', { name: /historical temperatures/i }));
    await fireEvent.input(screen.getByRole('slider', { name: /summer week/i }), { target: { value: '7' } });
    await fireEvent.click(screen.getByRole('radio', { name: /daily lows/i }));
    await fireEvent.click(screen.getByRole('radio', { name: /^5 years$/i }));

    expect(onEnabledChange).toHaveBeenCalledWith(false);
    expect(onWeekChange).toHaveBeenCalledWith(7);
    expect(onMetricChange).toHaveBeenCalledWith('low');
    expect(onPeriodChange).toHaveBeenCalledWith(5);
  });

  it('offers a retry action for an unavailable refresh', async () => {
    const onRetry = vi.fn();
    render(ClimateControls, {
      props: { state: { ...initialState, enabled: true, error: 'Service unavailable.' }, onRetry },
    });

    await fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('offers all climate locations alphabetically and dispatches a selected location', async () => {
    const summaries: ClimateLocationSummary[] = [
      {
        id: 'york', name: 'York', coordinate: { lat: 54, lon: -1 },
        distribution: { available: true, missing_years: [], start_year: 2001, end_year: 2025, n_days: 175, n_years: 25, p10: 10, median: 15, p90: 20 },
      },
      {
        id: 'birmingham', name: 'Birmingham', coordinate: { lat: 52, lon: -2 },
        distribution: { available: true, missing_years: [], start_year: 2001, end_year: 2025, n_days: 175, n_years: 25, p10: 10, median: 15, p90: 20 },
      },
    ];
    const store = fakeStore({ ...initialState, enabled: true, summaries, selection: 'birmingham', selectedLocationId: 'birmingham' });
    render(ClimateControls, { props: { store } });

    const select = screen.getByRole('combobox', { name: 'Temperature location' });
    expect(select).toHaveValue('birmingham');
    expect(Array.from((select as HTMLSelectElement).options).map((option) => option.textContent)).toEqual([
      'Choose a location', 'Birmingham', 'York',
    ]);

    await fireEvent.change(select, { target: { value: 'york' } });
    expect(store.selectLocation).toHaveBeenCalledWith('york');
  });

  it('disables the location selector while enabled without summary locations', () => {
    const store = fakeStore({ ...initialState, enabled: true });
    render(ClimateControls, { props: { store } });

    expect(screen.getByRole('combobox', { name: 'Temperature location' })).toBeDisabled();
    expect(screen.getByText(/no temperature locations available/i)).toBeInTheDocument();
  });
});
