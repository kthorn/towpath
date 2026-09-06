<script lang="ts">
  import {
    type ClimateLocationResponse,
    type ClimateMetric,
    type ClimatePeriodYears,
    type ClimateSummaryDistribution,
  } from '../lib/climate';
  import type { ClimateState, ClimateStore } from '../lib/stores/climate';

  export interface ClimateDetailProps {
    store?: ClimateStore;
    state?: ClimateState;
    detail?: ClimateLocationResponse | null;
    metric?: ClimateMetric;
    onClose?: () => void;
  }

  let props: ClimateDetailProps = $props();
  let observedState = $state<ClimateState | null>(null);

  $effect(() => {
    if (!props.store) {
      observedState = null;
      return;
    }
    return props.store.subscribe((value) => { observedState = value; });
  });

  const currentState = $derived(props.state ?? observedState);
  const detail = $derived(props.detail !== undefined ? props.detail : currentState?.detail ?? null);
  const metric = $derived(props.metric ?? currentState?.metric ?? 'high');
  const periods: readonly ClimatePeriodYears[] = [25, 5];

  function distribution(period: ClimatePeriodYears, selectedMetric: ClimateMetric = metric): ClimateSummaryDistribution | undefined {
    if (!detail) return undefined;
    return detail[selectedMetric][String(period) as `${ClimatePeriodYears}`];
  }

  function formatTemperature(value: number | null | undefined): string {
    return typeof value !== 'number' || !Number.isFinite(value) ? '—' : `${value.toFixed(1)}°C`;
  }

  function periodDates(period: ClimatePeriodYears): string {
    const high = distribution(period, 'high');
    const low = distribution(period, 'low');
    const start = high?.start_year ?? low?.start_year;
    const end = high?.end_year ?? low?.end_year;
    return start !== null && start !== undefined && end !== null && end !== undefined
      ? `${start}–${end}`
      : 'dates unavailable';
  }

  function unavailableMessage(value: ClimateSummaryDistribution | undefined): string {
    if (!value) return 'Unavailable';
    if (!value.missing_years.length) return 'Unavailable for this period';
    return `Unavailable · missing years: ${value.missing_years.join(', ')}`;
  }

  function finiteSamples(value: ClimateSummaryDistribution | undefined): number[] {
    return value?.available
      ? value.samples?.filter((sample) => Number.isFinite(sample)).sort((a, b) => a - b) ?? []
      : [];
  }

  const curves = $derived(periods.map((period) => ({
    period,
    samples: finiteSamples(distribution(period)),
  })).filter(({ samples }) => samples.length > 0));
  const allSamples = $derived(curves.flatMap(({ samples }) => samples));
  const rawAxisMin = $derived(allSamples.length ? Math.min(...allSamples) : 0);
  const rawAxisMax = $derived(allSamples.length ? Math.max(...allSamples) : 1);
  const axisMin = $derived(rawAxisMin === rawAxisMax ? rawAxisMin - 0.5 : rawAxisMin);
  const axisMax = $derived(rawAxisMin === rawAxisMax ? rawAxisMax + 0.5 : rawAxisMax);

  function points(samples: number[]): string {
    if (!samples.length) return '';
    const result: string[] = [`${(((samples[0] - axisMin) / (axisMax - axisMin)) * 100).toFixed(2)},100.00`];
    samples.forEach((sample, index) => {
      const x = ((sample - axisMin) / (axisMax - axisMin)) * 100;
      const before = 100 - ((index / samples.length) * 100);
      const after = 100 - (((index + 1) / samples.length) * 100);
      result.push(`${x.toFixed(2)},${before.toFixed(2)}`, `${x.toFixed(2)},${after.toFixed(2)}`);
      const next = samples[index + 1];
      if (next !== undefined) {
        const nextX = ((next - axisMin) / (axisMax - axisMin)) * 100;
        result.push(`${nextX.toFixed(2)},${after.toFixed(2)}`);
      }
    });
    return result.join(' ');
  }

  function close() {
    if (props.onClose) props.onClose();
    else props.store?.closeDetail();
  }

  async function retryDetail() {
    await props.store?.retryDetail();
  }
</script>

{#if detail}
  <aside class="climate-detail" aria-labelledby="climate-detail-title">
    <div class="climate-detail-heading">
      <div>
        <h2 id="climate-detail-title">{detail.location.name}</h2>
        <p>{detail.week_label}</p>
      </div>
      <button type="button" class="close" aria-label="Close temperature details" onclick={close}>Close</button>
    </div>

    <p class="period-dates">
      <span>25 years: {periodDates(25)}</span>
      <span>5 years: {periodDates(5)}</span>
    </p>

    <div class="provenance">
      <p>Source: <a href={detail.source.url} target="_blank" rel="noreferrer">{detail.source.name}</a></p>
      <p>{detail.source.attribution}; {detail.source.model}; timezone {detail.source.timezone}.</p>
      {#if detail.location.source_coordinate}
        <p>Source grid: {detail.location.source_coordinate.lat.toFixed(3)}, {detail.location.source_coordinate.lon.toFixed(3)}{#if detail.location.elevation !== null}; elevation {detail.location.elevation} m{/if}.</p>
      {/if}
    </div>

    <p class="range-note">Middle 80% of historical daily highs/lows (p10–p90). Values are individual days in the selected seven-day window, rather than a confidence interval or forecast.</p>

    <table aria-label="Historical daily temperature distributions">
      <caption>Daily high and low summaries (middle 80%: p10–p90)</caption>
      <thead>
        <tr><th scope="col">Metric</th><th scope="col">25 years</th><th scope="col">5 years</th></tr>
      </thead>
      <tbody>
        <tr>
          <th scope="row">Daily highs</th>
          {#each periods as period}
            {@const value = distribution(period, 'high')}
            <td>
              {#if value?.available}
                <span>p10 {formatTemperature(value.p10)} · median {formatTemperature(value.median)} · p90 {formatTemperature(value.p90)}</span>
                <small>{value.n_days} days across {value.n_years} summers{#if period === 5}; recent range may vary substantially{/if}</small>
              {:else}
                <strong>{period} years: {unavailableMessage(value)}</strong>
              {/if}
            </td>
          {/each}
        </tr>
        <tr>
          <th scope="row">Daily lows</th>
          {#each periods as period}
            {@const value = distribution(period, 'low')}
            <td>
              {#if value?.available}
                <span>p10 {formatTemperature(value.p10)} · median {formatTemperature(value.median)} · p90 {formatTemperature(value.p90)}</span>
                <small>{value.n_days} days across {value.n_years} summers{#if period === 5}; recent range may vary substantially{/if}</small>
              {:else}
                <strong>{period} years: {unavailableMessage(value)}</strong>
              {/if}
            </td>
          {/each}
        </tr>
      </tbody>
    </table>

    <section class="ecdf" aria-labelledby="ecdf-title">
      <h3 id="ecdf-title">Daily {metric === 'high' ? 'highs' : 'lows'} empirical distribution</h3>
      {#if curves.length}
        <p>Each line uses its own sample count and spans 0–100%; both periods share this temperature axis.</p>
        <svg viewBox="0 0 100 100" role="img" aria-label={`Daily ${metric === 'high' ? 'highs' : 'lows'} empirical distribution`} preserveAspectRatio="none">
          <line x1="0" y1="100" x2="100" y2="100" stroke="currentColor" />
          <line x1="0" y1="0" x2="0" y2="100" stroke="currentColor" />
          {#each curves as curve}
            <polyline
              data-testid="ecdf-line"
              points={points(curve.samples)}
              fill="none"
              stroke="currentColor"
              stroke-width="1.5"
              class:recent={curve.period === 5}
            />
          {/each}
        </svg>
        <div class="axis-labels"><span>{axisMin.toFixed(1)}°C</span><span>{axisMax.toFixed(1)}°C</span></div>
        <div class="line-key"><span><i class="line-sample"></i>25 years</span><span><i class="line-sample recent"></i>5 years</span></div>
        <p class="selected-range">Middle 80% of historical daily {metric === 'high' ? 'highs' : 'lows'}: p10 {formatTemperature(distribution(25)?.p10)} · median {formatTemperature(distribution(25)?.median)} · p90 {formatTemperature(distribution(25)?.p90)}.</p>
      {:else}
        <p class="ecdf-unavailable" role="status">Empirical distribution unavailable: no complete daily samples are available for this metric.</p>
      {/if}
    </section>
  </aside>
{:else if currentState?.detailLoading}
  <aside class="climate-detail" aria-label="Historical temperature details"><p role="status">Loading temperature details…</p></aside>
{:else if currentState?.detailError}
  <aside class="climate-detail" aria-label="Historical temperature details">
    <p role="alert">Temperature details unavailable: {currentState.detailError}</p>
    {#if props.store && currentState.selection}
      <button type="button" onclick={retryDetail}>Retry temperature details</button>
    {/if}
  </aside>
{/if}

<style>
  .climate-detail { display: grid; gap: 0.8rem; background: white; border: 1px solid #dbe2dd; border-radius: 12px; padding: 1rem; box-shadow: 0 2px 10px #173c300c; }
  .climate-detail-heading { display: flex; justify-content: space-between; gap: 1rem; align-items: start; }
  .climate-detail-heading h2, .climate-detail-heading p, .provenance p, .ecdf p { margin: 0; }
  .climate-detail-heading p, .period-dates, .provenance, .range-note, .ecdf p, .selected-range { color: #536861; font-size: 0.82rem; }
  .range-note { margin: 0; }
  .close { padding: 0.4rem 0.6rem; }
  .period-dates { display: flex; gap: 1rem; flex-wrap: wrap; margin: 0; }
  .provenance { display: grid; gap: 0.2rem; }
  .provenance a { color: #075e50; }
  table { border-collapse: collapse; width: 100%; font-size: 0.8rem; }
  th, td { border: 1px solid #dbe2dd; padding: 0.45rem; text-align: left; vertical-align: top; }
  thead th { background: #f2f6f3; }
  td span, td small { display: block; }
  td small { color: #536861; margin-top: 0.3rem; }
  .ecdf { display: grid; gap: 0.35rem; }
  .ecdf h3 { margin: 0; font-size: 0.95rem; }
  svg { display: block; width: 100%; height: 180px; border-left: 1px solid #9aaca6; border-bottom: 1px solid #9aaca6; color: #147d67; background: #f8fbf8; }
  polyline.recent { stroke: #af5c20; stroke-dasharray: 4 2; }
  .axis-labels, .line-key { display: flex; justify-content: space-between; color: #536861; font-size: 0.76rem; }
  .line-key { justify-content: start; gap: 1rem; }
  .line-key span { display: inline-flex; gap: 0.35rem; align-items: center; }
  .line-sample { display: inline-block; width: 1.3rem; border-top: 2px solid #147d67; }
  .line-sample.recent { border-top-color: #af5c20; border-top-style: dashed; }
  .selected-range { margin: 0; }
  .ecdf-unavailable { margin: 0; padding: 0.6rem; background: #fff6dc; border-left: 4px solid #a86608; }
</style>
