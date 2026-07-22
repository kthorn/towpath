<script lang="ts">
  import type { TripState } from '../lib/stores/trip';
  let { state, onDaySelect }: { state: TripState; onDaySelect: (day: number | null) => void } = $props();
  const transfer = (seconds: number, metres: number) => `${Math.round(seconds / 60)} min · ${(metres / 1000).toFixed(1)} km`;
  const hours = (minutes: number) => Number.isInteger(minutes / 60) ? `${minutes / 60} hr` : `${(minutes / 60).toFixed(1)} hr`;
</script>

<section class="summary" aria-label="Trip summary">
  <h2>Trip summary</h2>
  <div class="transfers">
    <p><span>Origin transfer</span>{#if state.origin.landRoute}<strong>{transfer(state.origin.landRoute.durationSeconds, state.origin.landRoute.distanceMeters)}</strong>{:else}<strong>Unavailable</strong>{/if}</p>
    <p><span>Destination transfer</span>{#if state.destination.landRoute}<strong>{transfer(state.destination.landRoute.durationSeconds, state.destination.landRoute.distanceMeters)}</strong>{:else}<strong>Unavailable</strong>{/if}</p>
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
</section>
