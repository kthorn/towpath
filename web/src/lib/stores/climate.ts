import { writable, type Readable } from 'svelte/store';

import {
  CLIMATE_WEEKS,
  DEFAULT_CLIMATE_METRIC,
  DEFAULT_CLIMATE_PERIOD_YEARS,
  DEFAULT_CLIMATE_WEEK_ID,
  createClimateApi,
  type ClimateApi,
  type ClimateLocationResponse,
  type ClimateLocationSummary,
  type ClimateLocationsResponse,
  type ClimateMetric,
  type ClimatePeriodYears,
  type ClimateSource,
} from '../climate';

export interface ClimateState {
  enabled: boolean;
  weekId: number;
  periodYears: ClimatePeriodYears;
  metric: ClimateMetric;
  summaries: ClimateLocationSummary[];
  detail: ClimateLocationResponse | null;
  loading: boolean;
  error: string | null;
  detailLoading: boolean;
  detailError: string | null;
  selection: string | null;
  /** Alias useful to map adapters that name marker selection explicitly. */
  selectedLocationId: string | null;
  revision: string | null;
  endYear: number | null;
  source: ClimateSource | null;
  weekLabel: string;
}

export interface ClimateStore extends Readable<ClimateState> {
  setEnabled(enabled: boolean): Promise<void>;
  setWeek(weekId: number): Promise<void>;
  setPeriod(periodYears: ClimatePeriodYears): Promise<void>;
  setMetric(metric: ClimateMetric): Promise<void>;
  selectLocation(location: string | ClimateLocationSummary): Promise<void>;
  closeDetail(): void;
  refresh(): Promise<void>;
  retryDetail(): Promise<void>;
}

export interface ClimateStoreDependencies {
  api?: ClimateApi;
  climateApi?: ClimateApi;
  fetch?: typeof fetch;
  fetchFn?: typeof fetch;
}

const initialState = (): ClimateState => ({
  enabled: false,
  weekId: DEFAULT_CLIMATE_WEEK_ID,
  periodYears: DEFAULT_CLIMATE_PERIOD_YEARS,
  metric: DEFAULT_CLIMATE_METRIC,
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
  weekLabel: CLIMATE_WEEKS[DEFAULT_CLIMATE_WEEK_ID].label,
});

const errorMessage = (error: unknown): string => (
  error instanceof Error ? error.message : 'Climate data unavailable.'
);

const sameQuery = (
  response: ClimateLocationsResponse,
  state: ClimateState,
): boolean => (
  response.week_id === state.weekId &&
  response.period_years === state.periodYears &&
  response.metric === state.metric
);

export function createClimateStore(
  dependencies: ClimateStoreDependencies | typeof fetch = {},
): ClimateStore {
  const options = typeof dependencies === 'function' ? { fetchFn: dependencies } : dependencies;
  const api = options.api ?? options.climateApi ?? createClimateApi(
    options.fetchFn ?? options.fetch ?? fetch,
  );
  const inner = writable(initialState());
  let state: ClimateState = initialState();
  inner.subscribe((value) => { state = value; });

  let summaryGeneration = 0;
  let detailGeneration = 0;

  const setState = (update: (current: ClimateState) => ClimateState): void => {
    inner.update(update);
  };

  const refresh = async (): Promise<void> => {
    if (!state.enabled) return;
    const generation = ++summaryGeneration;
    const query = {
      week_id: state.weekId,
      period_years: state.periodYears,
      metric: state.metric,
    };
    setState((current) => ({ ...current, loading: true, error: null }));

    try {
      const response = await api.locations(query);
      if (generation !== summaryGeneration || !state.enabled) return;
      if (!sameQuery(response, state)) {
        setState((current) => ({
          ...current,
          loading: false,
          error: 'Climate response did not match the selected week, period, and metric.',
        }));
        return;
      }

      const revisionChanged = state.revision !== null && state.revision !== response.revision;
      setState((current) => ({
        ...current,
        summaries: response.locations,
        loading: false,
        error: null,
        revision: response.revision,
        endYear: response.end_year,
        source: response.source,
        weekLabel: response.week_label,
        ...(revisionChanged
          ? { detail: null, selection: null, selectedLocationId: null, detailLoading: false, detailError: null }
          : {}),
      }));
    } catch (error) {
      if (generation !== summaryGeneration || !state.enabled) return;
      setState((current) => ({ ...current, loading: false, error: errorMessage(error) }));
    }
  };

  const changeQuery = async (patch: Partial<Pick<ClimateState, 'weekId' | 'periodYears' | 'metric'>>): Promise<void> => {
    const nextWeekId = patch.weekId ?? state.weekId;
    const nextPeriodYears = patch.periodYears ?? state.periodYears;
    const nextMetric = patch.metric ?? state.metric;
    const weekChanged = nextWeekId !== state.weekId;
    if (nextWeekId === state.weekId && nextPeriodYears === state.periodYears && nextMetric === state.metric) return;

    ++summaryGeneration;
    if (weekChanged) ++detailGeneration;
    const nextLabel = CLIMATE_WEEKS[nextWeekId]?.label ?? state.weekLabel;
    setState((current) => ({
      ...current,
      weekId: nextWeekId,
      periodYears: nextPeriodYears,
      metric: nextMetric,
      summaries: [],
      loading: false,
      error: null,
      ...(weekChanged
        ? {
            detail: null,
            detailLoading: false,
            detailError: null,
            selection: null,
            selectedLocationId: null,
            revision: null,
            endYear: null,
            source: null,
            weekLabel: nextLabel,
          }
        : {}),
    }));

    if (state.enabled) await refresh();
  };

  const selectLocation = async (location: string | ClimateLocationSummary): Promise<void> => {
    if (!state.enabled) return;
    const id = typeof location === 'string' ? location : location.id;
    if (
      state.selection === id &&
      state.detail?.location.id === id &&
      state.detail.week_id === state.weekId
    ) return;

    const generation = ++detailGeneration;
    const weekId = state.weekId;
    const revision = state.revision;
    setState((current) => ({
      ...current,
      selection: id,
      selectedLocationId: id,
      detail: null,
      detailLoading: true,
      detailError: null,
    }));

    try {
      const response = await api.location(id, { week_id: weekId });
      if (generation !== detailGeneration || state.weekId !== weekId || state.selection !== id) return;
      if (response.week_id !== weekId || response.location.id !== id) {
        setState((current) => ({
          ...current,
          detail: null,
          detailLoading: false,
          detailError: 'Climate response did not match the selected location or week.',
        }));
        return;
      }
      if (revision !== null && response.revision !== revision) {
        setState((current) => ({
          ...current,
          detail: null,
          detailLoading: false,
          detailError: 'Climate data changed; refresh the layer.',
        }));
        return;
      }
      setState((current) => ({
        ...current,
        detail: response,
        detailLoading: false,
        detailError: null,
        revision: response.revision,
        endYear: response.end_year,
        source: response.source,
        weekLabel: response.week_label,
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
      ++summaryGeneration;
      ++detailGeneration;
      if (!enabled) {
        setState((current) => ({
          ...current,
          enabled: false,
          summaries: [],
          loading: false,
          error: null,
          detail: null,
          detailLoading: false,
          detailError: null,
          selection: null,
          selectedLocationId: null,
          revision: null,
          endYear: null,
          source: null,
          weekLabel: CLIMATE_WEEKS[current.weekId]?.label ?? current.weekLabel,
        }));
        return;
      }

      setState((current) => ({ ...current, enabled: true, error: null }));
      await refresh();
    },
    setWeek: (weekId) => {
      if (!Number.isInteger(weekId) || weekId < 0 || weekId >= CLIMATE_WEEKS.length) {
        return Promise.reject(new Error('Invalid climate week.'));
      }
      return changeQuery({ weekId });
    },
    setPeriod: (periodYears) => {
      if (periodYears !== 5 && periodYears !== 25) return Promise.reject(new Error('Invalid climate period.'));
      return changeQuery({ periodYears });
    },
    setMetric: (metric) => {
      if (metric !== 'high' && metric !== 'low') return Promise.reject(new Error('Invalid climate metric.'));
      return changeQuery({ metric });
    },
    selectLocation,
    closeDetail: () => {
      ++detailGeneration;
      setState((current) => ({
        ...current,
        selection: null,
        selectedLocationId: null,
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
      // Refresh may clear selection when the artifact changes. Only explicit user
      // detail/query actions invalidate this continuation, not the new revision.
      if (!state.enabled || detailGeneration !== generation || state.weekId !== weekId) return;
      await selectLocation(id);
    },
  };
}
