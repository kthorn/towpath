<script lang="ts">
  import type { TripState, TripStore } from '../lib/stores/trip';
  import type { OutAndBackRoute } from '../lib/types';
  let { state, onDaySelect, store }: { state: TripState; onDaySelect: (day: number | null) => void; store?: TripStore } = $props();
  const transfer = (seconds: number, metres: number) => `${Math.round(seconds / 60)} min · ${(metres / 1000).toFixed(1)} km`;
  const hours = (minutes: number) => Number.isInteger(minutes / 60) ? `${minutes / 60} hr` : `${(minutes / 60).toFixed(1)} hr`;
  function onBranchRoute(routeId: string) {
    if (store && store.selectBranchRoute) store.selectBranchRoute(routeId);
  }
  const branchLabel = (candidate: OutAndBackRoute) => candidate.branch_choices.length
    ? candidate.branch_choices.map((choice, index) => `${choice.junction_name ?? `Branch ${index + 1}`} → ${choice.continuation_name ?? `Branch ${index + 1} continuation`}`).join(' · ')
    : 'Direct branch';
  const sourceLabel = (source: Record<string, unknown>) => {
    for (const key of ['attribution', 'source', 'name']) {
      if (typeof source[key] === 'string' && source[key]) return source[key] as string;
    }
    return null;
  };
  const kindLabel = (kind: string) => kind === 'winding_hole' ? 'Winding hole' : 'Canal junction';
  const basisLabel = (basis: string) => basis === 'junction_assumption' ? 'Turning assumed at junction' : 'Mapped turning point';
  const limitLabel = (limits: Record<string, unknown>) => Object.entries(limits)
    .map(([key, value]) => `${key.replace(/^boat_/, '').replaceAll('_m', '').replaceAll('_', ' ')} ${String(value)}${key.includes('_m') ? ' m' : ''}`).join(', ');
</script>

<section class="summary" aria-label="Trip summary">
  <h2>Trip summary</h2>
  <div class="transfers">
    <p><span>Origin transfer</span>{#if state.origin.landRoute}<strong>{transfer(state.origin.landRoute.durationSeconds, state.origin.landRoute.distanceMeters)}</strong>{:else}<strong>Unavailable</strong>{/if}</p>
    {#if state.journeyMode !== 'out_and_back'}
      <p><span>Destination transfer</span>{#if state.destination.landRoute}<strong>{transfer(state.destination.landRoute.durationSeconds, state.destination.landRoute.distanceMeters)}</strong>{:else}<strong>Unavailable</strong>{/if}</p>
    {/if}
  </div>
  {#if state.routing}<p role="status">Planning canal route…</p>{/if}
  {#if state.routeError}<p role="alert">{state.routeError}</p>{/if}
  {#if state.canalRoute}
    {@const route = state.canalRoute.route}
    {#if route.total_km === 0 && route.legs.length === 0}<p class="same-node">No canal travel required</p>
    {:else}
      <div class="metrics"><strong>{route.total_km} km canal</strong><strong>{route.total_locks} locks</strong><strong>{hours(route.total_minutes)} cruising</strong></div>
      {#if route.warnings.length}<ul class="warnings">{#each route.warnings as warning}<li>{warning}</li>{/each}</ul>{/if}
      {#if route.days.length}<ol class="days">{#each route.days as day}<li><button
        type="button"
        class:active={state.selectedDay === day.day}
        aria-pressed={state.selectedDay === day.day}
        onclick={() => onDaySelect(state.selectedDay === day.day ? null : day.day)}
      ><strong>Day {day.day}</strong><span>{hours(day.cruising_minutes)}{#if day.end_near} · end near {day.end_near}{/if}</span></button></li>{/each}</ol>{/if}
    {/if}
  {/if}
  {#if state.journeyMode === 'out_and_back' && (state.outAndBackRoutes?.length || state.outAndBackRejections?.length)}
    <section class="out-and-back-options" aria-label="Out-and-back routes">
      <h3>Out-and-back routes</h3>
      {#if state.outAndBackRoutes?.length}
        <div class="route-options">
          {#each state.outAndBackRoutes as candidate}
            <button type="button" class:active={state.selectedOutAndBackRouteId === candidate.route_id} aria-pressed={state.selectedOutAndBackRouteId === candidate.route_id} onclick={() => onBranchRoute(candidate.route_id)}>
              <strong>{candidate.turnaround.display_name}{#if candidate.route_id === state.defaultOutAndBackRouteId} · Default{/if}</strong>
              <span>{branchLabel(candidate)}</span>
              <small>{kindLabel(candidate.turnaround.kind)} · {basisLabel(candidate.turnaround.eligibility_basis)} · {candidate.outbound_distance_km.toFixed(1)} km outbound · {candidate.journey.route.total_km.toFixed(1)} km total · {Math.round(candidate.budget.remaining_minutes)} min remaining</small>
              {#if candidate.turnaround.sources.length}<small>Source: {candidate.turnaround.sources.map(sourceLabel).filter(Boolean).join(', ')}</small>{/if}
              {#if Object.keys(candidate.turnaround.turning_limits).length}<small>Turning limits: {limitLabel(candidate.turnaround.turning_limits)}</small>{/if}
            </button>
          {/each}
        </div>
      {/if}
      {#if state.outAndBackRejections?.length}
        <ul class="route-rejections">{#each state.outAndBackRejections as rejection}<li>{rejection.message}</li>{/each}</ul>
      {/if}
    </section>
  {/if}
</section>
