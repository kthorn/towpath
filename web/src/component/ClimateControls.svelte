<script lang="ts">
  import {
    CLIMATE_COLOR_LIMITS,
    CLIMATE_WEEKS,
    climateColor,
    type ClimateMetric,
  } from '../lib/climate';
  import type { ClimateState, ClimateStore } from '../lib/stores/climate';

  export interface ClimateControlsProps {
    store?: ClimateStore;
    state?: ClimateState;
    onEnabledChange?: (enabled: boolean) => void;
    onWeekChange?: (weekId: number) => void;
    onPeriodChange?: (periodYears: 5 | 25) => void;
    onMetricChange?: (metric: ClimateMetric) => void;
    onLocationChange?: (id: string) => void;
    onRetry?: () => void;
  }

  const fallbackState: ClimateState = {
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

  let props: ClimateControlsProps = $props();
  let observedState = $state<ClimateState | null>(null);

  $effect(() => {
    if (!props.store) {
      observedState = null;
      return;
    }
    return props.store.subscribe((value) => { observedState = value; });
  });

  const currentState = $derived(props.state ?? observedState ?? fallbackState);
  const week = $derived(CLIMATE_WEEKS[currentState.weekId] ?? CLIMATE_WEEKS[8]);
  const sortedLocations = $derived([...currentState.summaries].sort((left, right) => (
    left.name.localeCompare(right.name, undefined, { sensitivity: 'base' }) || left.id.localeCompare(right.id)
  )));
  const highLimits = CLIMATE_COLOR_LIMITS.high;
  const lowLimits = CLIMATE_COLOR_LIMITS.low;
  const legendGradient = (metric: ClimateMetric): string => {
    const limits = metric === 'high' ? highLimits : lowLimits;
    const stops = [0, 0.25, 0.5, 0.75, 1]
      .map((position) => climateColor(metric, limits.min + (position * (limits.max - limits.min))))
      .join(', ');
    return `linear-gradient(90deg, ${stops})`;
  };

  function setEnabled(enabled: boolean) {
    if (props.onEnabledChange) props.onEnabledChange(enabled);
    else void props.store?.setEnabled(enabled);
  }

  function setWeek(weekId: number) {
    if (props.onWeekChange) props.onWeekChange(weekId);
    else void props.store?.setWeek(weekId);
  }

  function setPeriod(periodYears: 5 | 25) {
    if (props.onPeriodChange) props.onPeriodChange(periodYears);
    else void props.store?.setPeriod(periodYears);
  }

  function setMetric(metric: ClimateMetric) {
    if (props.onMetricChange) props.onMetricChange(metric);
    else void props.store?.setMetric(metric);
  }

  function setLocation(id: string) {
    if (!id) return;
    if (props.onLocationChange) props.onLocationChange(id);
    else void props.store?.selectLocation(id);
  }
</script>

<section class="climate-controls" aria-label="Historical temperatures">
  <h2>Historical temperatures</h2>
  <label class="climate-toggle">
    <input
      type="checkbox"
      checked={currentState.enabled}
      aria-label="Historical temperatures"
      onchange={(event) => setEnabled((event.currentTarget as HTMLInputElement).checked)}
    />
    Show historical temperatures
  </label>

  {#if currentState.enabled}
    <div class="climate-control-group">
      <label for="climate-location">Temperature location</label>
      <select
        id="climate-location"
        aria-label="Temperature location"
        value={currentState.selection ?? ''}
        disabled={!sortedLocations.length || currentState.loading}
        onchange={(event) => setLocation((event.currentTarget as HTMLSelectElement).value)}
      >
        <option value="">Choose a location</option>
        {#each sortedLocations as location}
          <option value={location.id}>{location.name}</option>
        {/each}
      </select>
      {#if !sortedLocations.length && !currentState.loading && !currentState.error}
        <small class="climate-location-empty">No temperature locations available.</small>
      {/if}
    </div>

    <div class="climate-control-group">
      <label for="climate-week">Summer week: {week.label}</label>
      <input
        id="climate-week"
        type="range"
        min="0"
        max={CLIMATE_WEEKS.length - 1}
        step="1"
        value={currentState.weekId}
        aria-label="Summer week"
        aria-valuetext={week.label}
        oninput={(event) => setWeek(Number((event.currentTarget as HTMLInputElement).value))}
      />
      <div class="climate-range-labels" aria-hidden="true">
        <span>{CLIMATE_WEEKS[0].label}</span>
        <span>{CLIMATE_WEEKS[CLIMATE_WEEKS.length - 1].label}</span>
      </div>
    </div>

    <fieldset class="climate-control-group">
      <legend>Temperature metric</legend>
      <label><input type="radio" name="climate-metric" value="high" checked={currentState.metric === 'high'} onchange={() => setMetric('high')} /> Daily highs</label>
      <label><input type="radio" name="climate-metric" value="low" checked={currentState.metric === 'low'} onchange={() => setMetric('low')} /> Daily lows</label>
    </fieldset>

    <fieldset class="climate-control-group">
      <legend>Marker period</legend>
      <label><input type="radio" name="climate-period" value="25" checked={currentState.periodYears === 25} onchange={() => setPeriod(25)} /> 25 years</label>
      <label><input type="radio" name="climate-period" value="5" checked={currentState.periodYears === 5} onchange={() => setPeriod(5)} /> 5 years</label>
    </fieldset>

    <div class="climate-legend" aria-label="Temperature colour legend">
      <p>Marker colour uses fixed Celsius limits for daily {currentState.metric === 'high' ? 'highs' : 'lows'}.</p>
      {#if currentState.metric === 'high'}
        <div class="climate-legend-row">
          <span>High {highLimits.min}°C</span>
          <span class="climate-swatch" style={`background: ${legendGradient('high')}`} aria-hidden="true"></span>
          <span>{highLimits.max}°C</span>
        </div>
      {:else}
        <div class="climate-legend-row">
          <span>Low {lowLimits.min}°C</span>
          <span class="climate-swatch" style={`background: ${legendGradient('low')}`} aria-hidden="true"></span>
          <span>{lowLimits.max}°C</span>
        </div>
      {/if}
      <small>Values outside these ranges are clipped in colour; their true values appear in text.</small>
    </div>
  {/if}

  {#if currentState.loading}<p role="status">Loading historical temperatures…</p>{/if}
  {#if currentState.error}
    <p class="climate-error" role="alert">Historical temperatures unavailable: {currentState.error}</p>
    <button type="button" onclick={() => props.onRetry ? props.onRetry() : void props.store?.refresh()}>Retry</button>
  {/if}
</section>

<style>
  .climate-controls { display: grid; gap: 0.8rem; background: white; border: 1px solid #dbe2dd; border-radius: 12px; padding: 1rem; box-shadow: 0 2px 10px #173c300c; }
  .climate-controls h2 { margin: 0; }
  .climate-toggle, .climate-control-group label { display: flex; gap: 0.5rem; align-items: center; }
  .climate-control-group select { width: 100%; padding: 0.55rem; border: 1px solid #9aaca6; border-radius: 6px; font: inherit; }
  .climate-control-group { display: grid; gap: 0.4rem; border: 0; padding: 0; margin: 0; }
  .climate-control-group legend { font-weight: 600; font-size: 0.88rem; padding: 0; }
  .climate-range-labels, .climate-legend-row { display: flex; justify-content: space-between; gap: 0.5rem; color: #536861; font-size: 0.78rem; }
  .climate-legend { display: grid; gap: 0.35rem; color: #536861; font-size: 0.78rem; }
  .climate-legend p { margin: 0; }
  .climate-swatch { height: 0.7rem; flex: 1; border-radius: 999px; }
  .climate-error { margin: 0; padding: 0.6rem; background: #fff0ec; border-left: 4px solid #b43b22; }
</style>
