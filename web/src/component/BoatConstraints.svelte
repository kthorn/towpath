<script lang="ts">
  import type { TripStore } from '../lib/stores/trip';
  import type { BoatSettingsStore } from '../lib/stores/boat-settings';
  import type { JourneyMode } from '../lib/types';
  import { parseSchedule } from '../lib/schedule';
  let { store, settings, onReset, mode = 'point_to_point', days = $bindable<string | number>(7), hours = $bindable<string | number>(6) }: {
    store: TripStore;
    settings: BoatSettingsStore;
    onReset: () => void;
    mode?: JourneyMode;
    days?: string | number;
    hours?: string | number;
  } = $props();
  let error = $state('');
  let submissionGeneration = 0;
  async function submit() {
    const generation = ++submissionGeneration;
    error = '';
    try {
      await store.planCanalRoute({ ...parseSchedule(days, hours), ...$settings });
    }
    catch (cause) {
      if (generation === submissionGeneration) error = cause instanceof Error ? cause.message : String(cause);
    }
  }
  function reset() {
    submissionGeneration += 1;
    error = '';
    onReset();
  }
</script>

<form novalidate onsubmit={(event) => { event.preventDefault(); submit(); }}>
  <h2>Schedule</h2>
  <p>
    The map shows canal routes that can return to the same hire base within the selected Days and
    Hours per day, capped at 168 cruising hours.
  </p>
  <div class="constraint-grid">
    <label>Days<input type="number" required min="1" max="365" bind:value={days} /></label>
    <label>Hours per day<input type="number" required min="0.1" max="24" step="0.5" bind:value={hours} /></label>
  </div>
  <div class="constraint-actions">
    <button type="submit">{mode === 'out_and_back' ? 'Plan out-and-back journey' : 'Plan canal route'}</button>
    <button type="button" onclick={reset}>Reset trip</button>
  </div>
  {#if error}<p role="alert">{error}</p>{/if}
</form>
