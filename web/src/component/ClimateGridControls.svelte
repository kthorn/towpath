<script lang="ts">
  import {
    CLIMATE_COLOR_LIMITS,
    CLIMATE_WEEKS,
    climateColor,
    type ClimateMetric,
  } from '../lib/climate';
  import type {
    ClimateGridCell,
    ClimateGridSurface,
    ClimateGridView,
  } from '../lib/climate-grid';
  import type { ClimateGridState, ClimateGridStore } from '../lib/stores/climate-grid';

  export interface ClimateGridControlsProps {
    store?: ClimateGridStore;
    state?: ClimateGridState;
    onEnabledChange?: (enabled: boolean) => void;
    onWeekChange?: (weekId: number) => void;
    onPeriodChange?: (periodYears: 5 | 25) => void;
    onViewChange?: (view: ClimateGridView) => void;
    onThresholdChange?: (thresholdC: number) => void;
    onOpacityChange?: (opacity: number) => void;
    onCellChange?: (id: string) => void;
    onRetry?: () => void;
  }

  const fallbackState: ClimateGridState = {
    enabled: false,
    weekId: 8,
    periodYears: 25,
    view: 'high_p90',
    thresholdC: 30,
    opacity: 0.4,
    surface: null,
    detail: null,
    loading: false,
    error: null,
    detailLoading: false,
    detailError: null,
    selection: null,
  };

  const PAGE_SIZE = 200;
  let props: ClimateGridControlsProps = $props();
  let observedState = $state<ClimateGridState | null>(null);
  let searchTerm = $state('');
  let page = $state(0);

  $effect(() => {
    if (!props.store) {
      observedState = null;
      return;
    }
    return props.store.subscribe((value) => { observedState = value; });
  });

  const currentState = $derived(props.state ?? observedState ?? fallbackState);
  const week = $derived(CLIMATE_WEEKS[currentState.weekId] ?? CLIMATE_WEEKS[8]);
  const sortedCells = $derived.by(() => [...(currentState.surface?.cells ?? [])].sort((left, right) => (
    left.id.localeCompare(right.id) || left.coordinate.lat - right.coordinate.lat || left.coordinate.lon - right.coordinate.lon
  )));
  const filteredCells = $derived.by(() => {
    const query = searchTerm.trim().toLowerCase();
    if (!query) return sortedCells;
    return sortedCells.filter((cell) => searchKey(cell).includes(query));
  });
  const pageCount = $derived(Math.max(1, Math.ceil(filteredCells.length / PAGE_SIZE)));
  const visibleCells = $derived(filteredCells.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE));
  const optionCells = $derived.by(() => {
    const selected = sortedCells.find((cell) => cell.id === currentState.selection);
    if (selected && !visibleCells.some((cell) => cell.id === selected.id)) return [selected, ...visibleCells];
    return visibleCells;
  });
  const temperatureMetric = $derived(currentState.view.startsWith('low') ? 'low' as ClimateMetric : 'high' as ClimateMetric);
  const availableCellCount = $derived(currentState.surface?.cells.filter((cell) => cell.value !== null && Number.isFinite(cell.value)).length ?? 0);
  const legendGradient = $derived.by(() => {
    const limits = CLIMATE_COLOR_LIMITS[temperatureMetric];
    const stops = [0, 0.25, 0.5, 0.75, 1]
      .map((position) => climateColor(temperatureMetric, limits.min + position * (limits.max - limits.min)))
      .join(', ');
    return `linear-gradient(90deg, ${stops})`;
  });

  $effect(() => {
    if (page >= pageCount) page = Math.max(0, pageCount - 1);
  });

  function searchKey(cell: ClimateGridCell): string {
    return `${cell.id} ${cell.coordinate.lat.toFixed(3)} ${cell.coordinate.lon.toFixed(3)}`.toLowerCase();
  }

  function cellLabel(cell: ClimateGridCell): string {
    return `${cell.id} — ${cell.coordinate.lat.toFixed(3)}, ${cell.coordinate.lon.toFixed(3)}`;
  }

  function valueLabel(cell: ClimateGridCell): string {
    if (cell.value === null) return 'value unavailable';
    return currentState.surface?.unit === 'probability'
      ? `${(cell.value * 100).toFixed(1)}%`
      : `${cell.value.toFixed(1)}°C`;
  }

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

  function setView(view: ClimateGridView) {
    if (props.onViewChange) props.onViewChange(view);
    else void props.store?.setView(view);
  }

  function setThreshold(thresholdC: number) {
    if (props.onThresholdChange) props.onThresholdChange(thresholdC);
    else void props.store?.setThreshold(thresholdC);
  }

  function setOpacity(opacity: number) {
    if (props.onOpacityChange) props.onOpacityChange(opacity);
    else void props.store?.setOpacity(opacity);
  }

  function selectCell(id: string) {
    if (!id) return;
    if (props.onCellChange) props.onCellChange(id);
    else void props.store?.selectCell(id);
  }

  function retry() {
    if (props.onRetry) props.onRetry();
    else void props.store?.refresh();
  }
</script>

<section class="climate-grid-controls" aria-label="UK temperature overlay">
  <h2>UK temperature overlay</h2>
  <label class="grid-toggle">
    <input
      type="checkbox"
      checked={currentState.enabled}
      aria-label="UK temperature overlay"
      onchange={(event) => setEnabled((event.currentTarget as HTMLInputElement).checked)}
    />
    Show UK temperature overlay
  </label>

  {#if currentState.enabled}
    <div class="grid-control-group">
      <label for="climate-grid-cell">Inspect a temperature grid cell</label>
      <input
        id="climate-grid-search"
        type="search"
        aria-label="Search grid cells"
        placeholder="Search cell ID or coordinates"
        value={searchTerm}
        oninput={(event) => { searchTerm = (event.currentTarget as HTMLInputElement).value; page = 0; }}
      />
      <select
        id="climate-grid-cell"
        aria-label="Temperature grid cell"
        value={currentState.selection ?? ''}
        disabled={!currentState.surface || currentState.loading || !sortedCells.length}
        onchange={(event) => selectCell((event.currentTarget as HTMLSelectElement).value)}
      >
        <option value="">Choose a grid cell</option>
        {#each optionCells as cell}
          <option value={cell.id}>{cellLabel(cell)} · {valueLabel(cell)}</option>
        {/each}
      </select>
      {#if currentState.surface && filteredCells.length > PAGE_SIZE}
        <div class="grid-page-controls">
          <span>Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, filteredCells.length)} of {filteredCells.length}</span>
          <button type="button" disabled={page === 0} onclick={() => page -= 1}>Previous</button>
          <button type="button" disabled={page + 1 >= pageCount} onclick={() => page += 1}>Next</button>
        </div>
      {/if}
      {#if !currentState.surface && !currentState.loading && !currentState.error}
        <small>No temperature grid surface is available.</small>
      {/if}
    </div>

    <div class="grid-control-group">
      <label for="climate-grid-week">Summer week: {week.label}</label>
      <input
        id="climate-grid-week"
        type="range"
        min="0"
        max={CLIMATE_WEEKS.length - 1}
        step="1"
        value={currentState.weekId}
        aria-label="Summer week"
        aria-valuetext={week.label}
        oninput={(event) => setWeek(Number((event.currentTarget as HTMLInputElement).value))}
      />
      <div class="grid-range-labels" aria-hidden="true"><span>{CLIMATE_WEEKS[0].label}</span><span>{CLIMATE_WEEKS[CLIMATE_WEEKS.length - 1].label}</span></div>
    </div>

    <fieldset class="grid-control-group" role="radiogroup" aria-label="Grid view">
      <legend>Grid view</legend>
      <label><input type="radio" name="climate-grid-view" checked={currentState.view === 'high_p90'} onchange={() => setView('high_p90')} />High p90</label>
      <label><input type="radio" name="climate-grid-view" checked={currentState.view === 'high_median'} onchange={() => setView('high_median')} />High median</label>
      <label><input type="radio" name="climate-grid-view" checked={currentState.view === 'low_median'} onchange={() => setView('low_median')} />Low median</label>
      <label><input type="radio" name="climate-grid-view" checked={currentState.view === 'low_p10'} onchange={() => setView('low_p10')} />Low p10</label>
      <label><input type="radio" name="climate-grid-view" checked={currentState.view === 'high_exceedance'} onchange={() => setView('high_exceedance')} />High days above threshold</label>
    </fieldset>

    {#if currentState.view === 'high_exceedance'}
      <div class="grid-control-group">
        <label for="climate-grid-threshold">Exceedance threshold: {currentState.thresholdC}°C</label>
        <input
          id="climate-grid-threshold"
          type="range"
          min="-20"
          max="50"
          step="1"
          value={currentState.thresholdC}
          aria-label="Exceedance threshold"
          aria-valuetext={`${currentState.thresholdC}°C`}
          oninput={(event) => setThreshold(Number((event.currentTarget as HTMLInputElement).value))}
        />
        <p class="grid-exceedance-note">Fraction of historical daily highs strictly above {currentState.thresholdC}°C, using the stored daily count; 0–100%.</p>
      </div>
    {/if}

    <fieldset class="grid-control-group period-controls">
      <legend>Historical period</legend>
      <label><input type="radio" name="climate-grid-period" checked={currentState.periodYears === 25} onchange={() => setPeriod(25)} />25 years</label>
      <label><input type="radio" name="climate-grid-period" checked={currentState.periodYears === 5} onchange={() => setPeriod(5)} />5 years</label>
    </fieldset>

    <div class="grid-control-group">
      <label for="climate-grid-opacity">Grid opacity: {(currentState.opacity * 100).toFixed(0)}%</label>
      <input id="climate-grid-opacity" type="range" min="0" max="1" step="0.05" value={currentState.opacity} aria-label="Grid opacity" oninput={(event) => setOpacity(Number((event.currentTarget as HTMLInputElement).value))} />
    </div>

    {#if currentState.view === 'high_exceedance'}
      <div class="grid-legend" aria-label="High exceedance legend">
        <span>0%</span><span class="legend-swatch" style={`background: ${legendGradient}`}></span><span>100%</span>
      </div>
    {:else}
      <div class="grid-legend" aria-label={`${temperatureMetric === 'high' ? 'High' : 'Low'} temperature legend`}>
        <span>{CLIMATE_COLOR_LIMITS[temperatureMetric].min}°C</span><span class="legend-swatch" style={`background: ${legendGradient}`}></span><span>{CLIMATE_COLOR_LIMITS[temperatureMetric].max}°C</span>
      </div>
    {/if}
    <p class="grid-caveat">The smoothed display interpolates between approximately 10 km grid cells; it does not represent finer-resolution observations. Fixed colours clip at the legend limits.</p>
    {#if currentState.surface}
      <div class="grid-provenance">
        <p>Weather: <a href={currentState.surface.source.url} target="_blank" rel="noreferrer">{currentState.surface.source.name}</a> · {currentState.surface.source.attribution}; {currentState.surface.source.model}; timezone {currentState.surface.source.timezone}.</p>
        {#if currentState.surface.mask_source}
          <p>Boundary: <a href={currentState.surface.mask_source.url} target="_blank" rel="noreferrer">{currentState.surface.mask_source.name}</a> · {currentState.surface.mask_source.attribution}.</p>
        {/if}
      </div>
      <p class="grid-metadata">{availableCellCount} available of {currentState.surface.cells.length} cells · {currentState.surface.spacing_km} km spacing · historical through {currentState.surface.end_year}.</p>
    {/if}
    {#if currentState.error}
      <p class="grid-error" role="alert">Temperature grid unavailable: {currentState.error}</p>
      <button type="button" onclick={retry}>Retry</button>
    {/if}
  {/if}
</section>

<style>
  .climate-grid-controls { display: grid; gap: 0.7rem; background: white; border: 1px solid #dbe2dd; border-radius: 12px; padding: 1rem; box-shadow: 0 2px 10px #173c300c; }
  h2 { margin: 0; font-size: 1rem; }
  .grid-toggle, .grid-control-group label { display: flex; gap: 0.45rem; align-items: center; }
  .grid-control-group { display: grid; gap: 0.35rem; }
  .grid-control-group > label[for] { display: block; }
  .grid-control-group input[type='search'], .grid-control-group select { box-sizing: border-box; width: 100%; padding: 0.45rem; }
  fieldset { border: 1px solid #dbe2dd; border-radius: 8px; padding: 0.55rem; }
  fieldset label { margin-top: 0.3rem; }
  fieldset label:first-of-type { margin-top: 0; }
  legend { padding: 0 0.25rem; font-weight: 600; }
  input[type='range'] { width: 100%; accent-color: #147d67; }
  .grid-range-labels, .grid-page-controls, .grid-legend { display: flex; justify-content: space-between; gap: 0.4rem; color: #536861; font-size: 0.76rem; }
  .grid-page-controls { align-items: center; flex-wrap: wrap; }
  .grid-page-controls button { padding: 0.25rem 0.45rem; }
  .grid-legend { align-items: center; }
  .legend-swatch { height: 0.75rem; flex: 1; border-radius: 99px; border: 1px solid #c4d0ca; }
  .grid-exceedance-note, .grid-caveat, .grid-metadata, .grid-error, .grid-provenance p { margin: 0; color: #536861; font-size: 0.78rem; }
  .grid-provenance { display: grid; gap: 0.2rem; }
  .grid-provenance a { color: #075e50; }
  .grid-error { color: #963b2d; }
</style>
