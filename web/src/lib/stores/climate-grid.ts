import { writable, type Readable } from 'svelte/store';

import {
  CLIMATE_WEEKS,
  DEFAULT_CLIMATE_PERIOD_YEARS,
  DEFAULT_CLIMATE_WEEK_ID,
  type ClimateLocationResponse,
  type ClimatePeriodYears,
} from '../climate';
import {
  createClimateGridApi,
  type ClimateGridApi,
  type ClimateGridRequest,
  type ClimateGridSurface,
  type ClimateGridView,
} from '../climate-grid';

export interface ClimateGridState {
  enabled: boolean;
  weekId: number;
  periodYears: ClimatePeriodYears;
  view: ClimateGridView;
  thresholdC: number;
  opacity: number;
  surface: ClimateGridSurface | null;
  detail: ClimateLocationResponse | null;
  loading: boolean;
  error: string | null;
  detailLoading: boolean;
  detailError: string | null;
  selection: string | null;
}

export interface ClimateGridStore extends Readable<ClimateGridState> {
  setEnabled(enabled: boolean): Promise<void>;
  setWeek(weekId: number): Promise<void>;
  setPeriod(periodYears: ClimatePeriodYears): Promise<void>;
  setView(view: ClimateGridView): Promise<void>;
  setThreshold(thresholdC: number): Promise<void>;
  setOpacity(opacity: number): Promise<void>;
  selectCell(id: string): Promise<void>;
  closeDetail(): void;
  refresh(): Promise<void>;
  retryDetail(): Promise<void>;
}

export interface ClimateGridStoreDependencies {
  api?: ClimateGridApi;
  fetch?: typeof fetch;
  fetchFn?: typeof fetch;
}

export const DEFAULT_CLIMATE_GRID_VIEW: ClimateGridView = 'high_p90';
export const DEFAULT_CLIMATE_GRID_THRESHOLD_C = 30;
export const DEFAULT_CLIMATE_GRID_OPACITY = 0.4;
export const MIN_CLIMATE_GRID_THRESHOLD_C = -20;
export const MAX_CLIMATE_GRID_THRESHOLD_C = 50;

const initialState = (): ClimateGridState => ({
  enabled: false,
  weekId: DEFAULT_CLIMATE_WEEK_ID,
  periodYears: DEFAULT_CLIMATE_PERIOD_YEARS,
  view: DEFAULT_CLIMATE_GRID_VIEW,
  thresholdC: DEFAULT_CLIMATE_GRID_THRESHOLD_C,
  opacity: DEFAULT_CLIMATE_GRID_OPACITY,
  surface: null,
  detail: null,
  loading: false,
  error: null,
  detailLoading: false,
  detailError: null,
  selection: null,
});

const errorMessage = (error: unknown): string => (
  error instanceof Error ? error.message : 'Climate grid data unavailable.'
);

function requestedGrid(state: ClimateGridState): ClimateGridRequest {
  const request: ClimateGridRequest = {
    week_id: state.weekId,
    period_years: state.periodYears,
    view: state.view,
  };
  if (state.view === 'high_exceedance') request.threshold_c = state.thresholdC;
  return request;
}

function matchesRequest(response: ClimateGridSurface, request: ClimateGridRequest): boolean {
  const expectedThreshold = request.view === 'high_exceedance' ? request.threshold_c ?? null : null;
  return response.week_id === request.week_id &&
    response.period_years === request.period_years &&
    response.view === request.view &&
    response.threshold_c === expectedThreshold;
}

function validThreshold(value: number): boolean {
  return Number.isInteger(value) && value >= MIN_CLIMATE_GRID_THRESHOLD_C && value <= MAX_CLIMATE_GRID_THRESHOLD_C;
}

export function createClimateGridStore(
  dependencies: ClimateGridStoreDependencies | typeof fetch = {},
): ClimateGridStore {
  const options = typeof dependencies === 'function' ? { fetchFn: dependencies } : dependencies;
  const api = options.api ?? createClimateGridApi(options.fetchFn ?? options.fetch ?? fetch);
  const inner = writable(initialState());
  let state: ClimateGridState = initialState();
  inner.subscribe((value) => { state = value; });

  let surfaceGeneration = 0;
  let detailGeneration = 0;
  let knownRevision: string | null = null;

  const setState = (update: (current: ClimateGridState) => ClimateGridState): void => {
    inner.update(update);
  };

  const refresh = async (): Promise<void> => {
    if (!state.enabled) return;
    const generation = ++surfaceGeneration;
    const request = requestedGrid(state);
    setState((current) => ({ ...current, loading: true, error: null }));

    try {
      const response = await api.grid(request);
      if (generation !== surfaceGeneration || !state.enabled) return;
      if (!matchesRequest(response, request)) {
        setState((current) => ({
          ...current,
          loading: false,
          error: 'Climate grid response did not match the selected week, period, view, or threshold.',
        }));
        return;
      }

      const revisionChanged = knownRevision !== null && knownRevision !== response.revision;
      knownRevision = response.revision;
      setState((current) => ({
        ...current,
        surface: response,
        loading: false,
        error: null,
        ...(revisionChanged
          ? { detail: null, selection: null, detailLoading: false, detailError: null }
          : {}),
      }));
    } catch (error) {
      if (generation !== surfaceGeneration || !state.enabled) return;
      setState((current) => ({ ...current, loading: false, error: errorMessage(error) }));
    }
  };

  const changeQuery = async (
    patch: Partial<Pick<ClimateGridState, 'weekId' | 'periodYears' | 'view'>>,
  ): Promise<void> => {
    const nextWeekId = patch.weekId ?? state.weekId;
    const nextPeriodYears = patch.periodYears ?? state.periodYears;
    const nextView = patch.view ?? state.view;
    const weekChanged = nextWeekId !== state.weekId;
    if (nextWeekId === state.weekId && nextPeriodYears === state.periodYears && nextView === state.view) return;

    ++surfaceGeneration;
    if (weekChanged) ++detailGeneration;
    setState((current) => ({
      ...current,
      weekId: nextWeekId,
      periodYears: nextPeriodYears,
      view: nextView,
      surface: null,
      loading: false,
      error: null,
      ...(weekChanged
        ? { detail: null, detailLoading: false, detailError: null, selection: null }
        : {}),
    }));

    if (state.enabled) await refresh();
  };

  const selectCell = async (id: string): Promise<void> => {
    if (!state.enabled || !id) return;
    if (
      state.selection === id &&
      state.detail?.location.id === id &&
      state.detail.week_id === state.weekId
    ) return;

    const generation = ++detailGeneration;
    const weekId = state.weekId;
    const revision = state.surface?.revision ?? knownRevision;
    setState((current) => ({
      ...current,
      selection: id,
      detail: null,
      detailLoading: true,
      detailError: null,
    }));

    try {
      const response = await api.cell(id, { week_id: weekId });
      if (generation !== detailGeneration || state.weekId !== weekId || state.selection !== id) return;
      if (response.week_id !== weekId || response.location.id !== id) {
        setState((current) => ({
          ...current,
          detail: null,
          detailLoading: false,
          detailError: 'Climate grid response did not match the selected cell or week.',
        }));
        return;
      }
      if (revision !== null && response.revision !== revision) {
        setState((current) => ({
          ...current,
          detail: null,
          detailLoading: false,
          detailError: 'Climate grid data changed; refresh the surface.',
        }));
        return;
      }
      setState((current) => ({
        ...current,
        detail: response,
        detailLoading: false,
        detailError: null,
      }));
    } catch (error) {
      if (generation !== detailGeneration || state.weekId !== weekId || state.selection !== id) return;
      setState((current) => ({ ...current, detailLoading: false, detailError: errorMessage(error) }));
    }
  };

  return {
    subscribe: inner.subscribe,
    setEnabled: async (enabled) => {
      if (state.enabled === enabled) return;
      ++surfaceGeneration;
      ++detailGeneration;
      if (!enabled) {
        knownRevision = null;
        setState((current) => ({
          ...current,
          enabled: false,
          surface: null,
          loading: false,
          error: null,
          detail: null,
          detailLoading: false,
          detailError: null,
          selection: null,
        }));
        return;
      }

      setState((current) => ({ ...current, enabled: true, error: null }));
      await refresh();
    },
    setWeek: (weekId) => {
      if (!Number.isInteger(weekId) || weekId < 0 || weekId >= CLIMATE_WEEKS.length) {
        return Promise.reject(new Error('Invalid climate grid week.'));
      }
      return changeQuery({ weekId });
    },
    setPeriod: (periodYears) => {
      if (periodYears !== 5 && periodYears !== 25) return Promise.reject(new Error('Invalid climate grid period.'));
      return changeQuery({ periodYears });
    },
    setView: (view) => {
      if (!['high_median', 'high_p90', 'low_median', 'low_p10', 'high_exceedance'].includes(view)) {
        return Promise.reject(new Error('Invalid climate grid view.'));
      }
      return changeQuery({ view });
    },
    setThreshold: async (thresholdC) => {
      if (!validThreshold(thresholdC)) return Promise.reject(new Error('Invalid climate grid threshold.'));
      if (state.thresholdC === thresholdC) return;
      const shouldRefresh = state.view === 'high_exceedance' && state.enabled;
      if (shouldRefresh) ++surfaceGeneration;
      setState((current) => ({
        ...current,
        thresholdC,
        ...(shouldRefresh ? { surface: null, loading: false, error: null } : {}),
      }));
      if (shouldRefresh) await refresh();
    },
    setOpacity: async (opacity) => {
      if (!Number.isFinite(opacity)) return Promise.reject(new Error('Invalid climate grid opacity.'));
      setState((current) => ({ ...current, opacity: Math.min(1, Math.max(0, opacity)) }));
    },
    selectCell,
    closeDetail: () => {
      ++detailGeneration;
      setState((current) => ({
        ...current,
        selection: null,
        detail: null,
        detailLoading: false,
        detailError: null,
      }));
    },
    refresh,
    retryDetail: async () => {
      const id = state.selection;
      if (!state.enabled || !id) return;
      const generation = detailGeneration;
      const weekId = state.weekId;
      await refresh();
      if (!state.enabled || detailGeneration !== generation || state.weekId !== weekId) return;
      await selectCell(id);
    },
  };
}
