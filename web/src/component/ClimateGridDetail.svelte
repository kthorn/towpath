<script lang="ts">
  import ClimateDetail from './ClimateDetail.svelte';
  import { highExceedanceFraction } from '../lib/climate-grid';
  import type {
    ClimateLocationResponse,
    ClimateMetric,
    ClimatePeriodYears,
    ClimateSummaryDistribution,
  } from '../lib/climate';
  import type { ClimateGridState, ClimateGridStore } from '../lib/stores/climate-grid';

  export interface ClimateGridDetailProps {
    store?: ClimateGridStore;
    state?: ClimateGridState;
    detail?: ClimateLocationResponse | null;
    metric?: ClimateMetric;
    onClose?: () => void;
    onRetry?: () => void;
  }

  let props: ClimateGridDetailProps = $props();
  let observedState = $state<ClimateGridState | null>(null);

  $effect(() => {
    if (!props.store) {
      observedState = null;
      return;
    }
    return props.store.subscribe((value) => { observedState = value; });
  });

  const currentState = $derived(props.state ?? observedState);
  const detail = $derived(props.detail !== undefined ? props.detail : currentState?.detail ?? null);
  const metric = $derived(props.metric ?? (currentState?.view.startsWith('low') ? 'low' : 'high'));
  const thresholdC = $derived(currentState?.thresholdC ?? 30);

  type ExceedanceRow =
    | { period: ClimatePeriodYears; unavailable: true }
    | { period: ClimatePeriodYears; unavailable: false; count: number; nDays: number; fraction: number };

  const exceedanceRows = $derived.by((): ExceedanceRow[] => {
    if (!detail || currentState?.view !== 'high_exceedance') return [];
    return ([25, 5] as const).map((period) => {
      const distribution: ClimateSummaryDistribution | undefined = detail.high[String(period) as `${ClimatePeriodYears}`];
      const samples = distribution?.available
        ? distribution.samples?.filter((sample) => Number.isFinite(sample)) ?? []
        : [];
      if (!samples.length || !distribution || distribution.n_days <= 0) return { period, unavailable: true };
      const count = samples.filter((sample) => sample > thresholdC).length;
      return {
        period,
        unavailable: false,
        count,
        nDays: distribution.n_days,
        fraction: highExceedanceFraction(samples, thresholdC, distribution.n_days),
      };
    });
  });

  function close() {
    if (props.onClose) props.onClose();
    else props.store?.closeDetail();
  }

  function retry() {
    if (props.onRetry) props.onRetry();
    else void props.store?.retryDetail();
  }
</script>

{#if detail}
  <ClimateDetail {detail} {metric} onClose={close} />
  {#if currentState?.view === 'high_exceedance'}
    <section class="grid-exceedance" aria-labelledby="grid-exceedance-title">
      <h3 id="grid-exceedance-title">Historical high-day exceedance</h3>
      {#each exceedanceRows as row}
        {#if row.unavailable}
          <p>{row.period} years: exceedance unavailable — no valid daily high samples.</p>
        {:else}
          <p>{row.period} years: {row.count} of {row.nDays} historical daily highs strictly above {thresholdC}°C ({(row.fraction * 100).toFixed(1)}%).</p>
        {/if}
      {/each}
      <p class="grid-exceedance-caveat">This is an empirical count of the stored historical days; zero exceedances does not rule out hotter weather.</p>
    </section>
  {/if}
{:else if currentState?.detailLoading}
  <aside class="climate-grid-detail" aria-label="Historical temperature grid details">
    <p role="status">Loading temperature grid details…</p>
  </aside>
{:else if currentState?.detailError}
  <aside class="climate-grid-detail" aria-label="Historical temperature grid details">
    <p role="alert">Temperature grid details unavailable: {currentState.detailError}</p>
    {#if props.store && currentState.selection}
      <button type="button" onclick={retry}>Retry temperature grid details</button>
    {/if}
  </aside>
{/if}

<style>
  .climate-grid-detail { display: grid; gap: 0.7rem; background: white; border: 1px solid #dbe2dd; border-radius: 12px; padding: 1rem; }
  .climate-grid-detail p { margin: 0; }
  .grid-exceedance { display: grid; gap: 0.35rem; background: white; border: 1px solid #dbe2dd; border-radius: 12px; padding: 1rem; }
  .grid-exceedance h3, .grid-exceedance p { margin: 0; }
  .grid-exceedance p { color: #536861; font-size: 0.82rem; }
  .grid-exceedance-caveat { font-size: 0.76rem; }
</style>
