import { fireEvent, render, screen } from '@testing-library/svelte';
import { get, writable } from 'svelte/store';
import { describe, expect, it, vi } from 'vitest';

import type { ClimateGridState, ClimateGridStore } from '../lib/stores/climate-grid';
import ClimateGridControls from './ClimateGridControls.svelte';

const state = (overrides: Partial<ClimateGridState> = {}): ClimateGridState => ({
  enabled: false,
  weekId: 8,
  periodYears: 25,
  view: 'high_p90',
  thresholdC: 30,
  opacity: 0.4, colorRange: null,
  surface: null,
  detail: null,
  loading: false,
  error: null,
  detailLoading: false,
  detailError: null,
  selection: null,
  ...overrides,
});

function fakeStore(initial = state()): ClimateGridStore {
  const inner = writable(initial);
  return {
    subscribe: inner.subscribe,
    setColorRange: vi.fn(async () => {}),
    setEnabled: vi.fn(async (enabled) => inner.update((current) => ({ ...current, enabled }))),
    setWeek: vi.fn(async (weekId) => inner.update((current) => ({ ...current, weekId }))),
    setPeriod: vi.fn(async (periodYears) => inner.update((current) => ({ ...current, periodYears }))),
    setView: vi.fn(async (view) => inner.update((current) => ({ ...current, view }))),
    setThreshold: vi.fn(async (thresholdC) => inner.update((current) => ({ ...current, thresholdC }))),
    setOpacity: vi.fn(async (opacity) => inner.update((current) => ({ ...current, opacity }))),
    selectCell: vi.fn(async () => {}),
    closeDetail: vi.fn(),
    refresh: vi.fn(async () => {}),
    retryDetail: vi.fn(async () => {}),
  };
}

const gridSurface = {
  revision: 'r1', end_year: 2025,
  source: { name: 'Source', url: 'https://example.test', attribution: 'Attribution', timezone: 'UTC', model: 'Model' },
  mask_source: { name: 'UK boundary source', url: 'https://boundaries.example.test', attribution: 'Boundary attribution' },
  week_id: 8, week_label: 'June 26–July 2', period_years: 25 as const, view: 'high_p90' as const,
  threshold_c: null, unit: 'celsius' as const, spacing_km: 10 as const,
  mask: { type: 'Polygon' as const, coordinates: [[[-2, 50], [1, 50], [1, 54], [-2, 54], [-2, 50]]] },
  cells: [
    { id: 'cell-a', coordinate: { lat: 51.5, lon: -1 }, value: 20, n_days: 175 },
    { id: 'cell-b', coordinate: { lat: 52.5, lon: -2 }, value: null, n_days: 0 },
  ],
};

describe('ClimateGridControls', () => {
  it('keeps the grid compact while disabled and exposes all views when enabled', async () => {
    const store = fakeStore();
    render(ClimateGridControls, { props: { store } });

    expect(screen.getByRole('checkbox', { name: /uk temperature overlay/i })).not.toBeChecked();
    expect(screen.queryByRole('radiogroup', { name: /grid view/i })).not.toBeInTheDocument();

    await fireEvent.click(screen.getByRole('checkbox', { name: /uk temperature overlay/i }));
    expect(screen.getByRole('radio', { name: /high p90/i })).toBeChecked();
    expect(screen.getByRole('radio', { name: /high median/i })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /low median/i })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /low p10/i })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /high days above threshold/i })).toBeInTheDocument();
  });

  it('dispatches view, threshold, opacity, period, week, and retry controls', async () => {
    const store = fakeStore({ ...state(), enabled: true, error: 'Unavailable' });
    render(ClimateGridControls, { props: { store } });

    await fireEvent.click(screen.getByRole('radio', { name: /high days above threshold/i }));
    await fireEvent.input(screen.getByRole('slider', { name: /exceedance threshold/i }), { target: { value: '31' } });
    await fireEvent.input(screen.getByRole('slider', { name: /grid opacity/i }), { target: { value: '0.7' } });
    await fireEvent.click(screen.getByRole('radio', { name: /^5 years$/i }));
    await fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    expect(store.setView).toHaveBeenCalledWith('high_exceedance');
    expect(store.setThreshold).toHaveBeenCalledWith(31);
    expect(store.setOpacity).toHaveBeenCalledWith(0.7);
    expect(store.setPeriod).toHaveBeenCalledWith(5);
    expect(store.refresh).toHaveBeenCalledOnce();
  });

  it('offers a searchable paginated cell selector with coordinate labels', async () => {
    const store = fakeStore({ ...state(), enabled: true, surface: gridSurface });
    render(ClimateGridControls, { props: { store } });

    const select = screen.getByRole('combobox', { name: /temperature grid cell/i });
    expect(screen.getByText(/51\.500, -1\.000/)).toBeInTheDocument();
    expect(screen.getByText(/52\.500, -2\.000/)).toBeInTheDocument();
    await fireEvent.change(select, { target: { value: 'cell-b' } });
    expect(store.selectCell).toHaveBeenCalledWith('cell-b');
    expect(screen.getByRole('searchbox', { name: /search grid cells/i })).toBeInTheDocument();
  });

  it('keeps every cell reachable through pagination or an ID search', async () => {
    const cells = Array.from({ length: 401 }, (_, index) => ({
      id: `cell-${index}`,
      coordinate: { lat: 50 + index / 100, lon: -5 + index / 100 },
      value: 20,
      n_days: 175,
    }));
    const store = fakeStore({ ...state(), enabled: true, surface: { ...gridSurface, cells } });
    render(ClimateGridControls, { props: { store } });

    expect(screen.getByText(/showing 1–200 of 401/i)).toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByText(/cell-400/)).toBeInTheDocument();

    await fireEvent.input(screen.getByRole('searchbox', { name: /search grid cells/i }), { target: { value: 'cell-399' } });
    expect(screen.getByText(/cell-399/)).toBeInTheDocument();
  });

  it('shows the historical-count interpretation and unavailable state', () => {
    render(ClimateGridControls, { props: { state: state({ enabled: true, surface: gridSurface, view: 'high_exceedance' }) } });

    expect(screen.getByText(/fraction of historical daily highs strictly above/i)).toBeInTheDocument();
    expect(screen.getByText(/smoothed display/i)).toBeInTheDocument();
  });

  it('shows weather and boundary attribution links plus available cell counts', () => {
    render(ClimateGridControls, { props: { state: state({ enabled: true, surface: gridSurface }) } });

    expect(screen.getByRole('link', { name: 'Source' })).toHaveAttribute('href', 'https://example.test');
    expect(screen.getByText(/Attribution/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'UK boundary source' })).toHaveAttribute('href', 'https://boundaries.example.test');
    expect(screen.getByText(/Boundary attribution/)).toBeInTheDocument();
    expect(screen.getByText(/1 available of 2 cells/i)).toBeInTheDocument();
  });
});

it('labels the automatic probability scale and reports cells with recorded hot days', () => {
  render(ClimateGridControls, { props: { state: state({ enabled: true, view: 'high_exceedance', surface: {
    ...gridSurface, view: 'high_exceedance', unit: 'probability', threshold_c: 30,
    cells: [
      { ...gridSurface.cells[0], value: 1 / 175 },
      { ...gridSurface.cells[0], id: 'zero', value: 0 },
      gridSurface.cells[1],
    ],
  } }) } });
  expect(screen.getByRole('spinbutton', {name: /colour scale minimum/i})).toHaveValue(0);
  expect(screen.getByRole('spinbutton', {name: /colour scale maximum/i})).toHaveValue(0.571428571429);
  expect(screen.getByText(/99.9th percentile/i)).toBeInTheDocument();
  expect(screen.getByText(/1 of 2 available cells recorded days above 30°C/i)).toBeInTheDocument();
  expect(screen.getByRole('option', { name: /0.6%/ })).toBeInTheDocument();
});


it('updates both colour bounds, zooms the colour range, and restores Auto', async () => {
  const onColorRangeChange = vi.fn();
  render(ClimateGridControls, { props: { state: state({ enabled: true, view: 'high_exceedance', colorRange: {min: 0, max: 0.1} }), onColorRangeChange } });
  await fireEvent.change(screen.getByRole('spinbutton', {name: /colour scale minimum/i}), {target: {value: '1'}});
  expect(onColorRangeChange).toHaveBeenLastCalledWith({min: 0.01, max: 0.1});
  await fireEvent.change(screen.getByRole('spinbutton', {name: /colour scale maximum/i}), {target: {value: '5'}});
  expect(onColorRangeChange).toHaveBeenLastCalledWith({min: 0, max: 0.05});
  await fireEvent.click(screen.getByRole('button', {name: 'Zoom colour scale in'}));
  expect(onColorRangeChange.mock.lastCall![0].max - onColorRangeChange.mock.lastCall![0].min).toBeCloseTo(0.05);
  await fireEvent.click(screen.getByRole('button', {name: 'Auto colour scale'}));
  expect(onColorRangeChange).toHaveBeenLastCalledWith(null);
});

it('keeps ticks distinct when the probability colour scale is tightly zoomed', () => {
  const {container} = render(ClimateGridControls, {props: {state: state({enabled: true, view: 'high_exceedance', colorRange: {min: 0.00101, max: 0.00104}})}});
  const labels = Array.from(container.querySelectorAll('.probability-ticks span')).map(e => e.textContent);
  expect(new Set(labels).size).toBe(5);
});

it('restores rejected input and clears validation on Auto', async () => {
  const {createClimateGridStore} = await import('../lib/stores/climate-grid');
  const store = createClimateGridStore();
  await store.setView('high_exceedance');
  // Explicit enabled state avoids making a network call while retaining the real store.
  const {rerender} = render(ClimateGridControls, {props: {store, state: {...get(store), enabled: true}}});
  const maximum = screen.getByRole('spinbutton', {name: /colour scale maximum/i});
  await fireEvent.change(maximum, {target: {value: '-1'}});
  expect(screen.getByRole('alert')).toBeInTheDocument();
  await fireEvent.click(screen.getByRole('button', {name: 'Auto colour scale'}));
  expect(maximum).toHaveValue(1);
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  await fireEvent.change(maximum, {target: {value: '-1'}});
  await rerender({store, state: state({enabled: true, view: 'low_p10'})});
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
